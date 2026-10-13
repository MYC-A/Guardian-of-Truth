"""GPU stage of the single-pass judge: offline vLLM, one forward pass per row.

Input JSON lines {"key", "prompt", "response", "hints"}. Output JSON lines (fsync after every chunk):
{"event": "ready"}, one record per row, {"event": "done"} (or {"event": "failed"}).

Score. The answer token is restricted to the YES/NO token ids (allowed_token_ids) and logprobs are
read in processed mode, i.e. after that restriction, so both answers always get an explicit
probability: score = log P(YES) - log P(NO) over exactly these tokens (exact=true). A start-up probe
verifies this on the running engine. If this vLLM does not honour it, the stage stops when
require_exact_scores is true (default); otherwise it falls back to bounded log-odds from the raw
top-20: a missing answer is placed at the lowest returned logprob, which keeps the ordering
(exact=false on every such record).

Context budget. Every row is rendered once at full length before inference. One per-row token cap is
planned from the total token count, the time left and planning_tokens_per_second, and applied to all
rows. Only if the measured throughput would miss --stop-at is the cap lowered for the remaining rows
(event emergency_cap; every record carries its cap). The system block (policy + tools) is never
trimmed unless it alone exceeds the cap (policy_trimmed=true).
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

STARTED = time.time()
ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / 'src')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from guardian_truth.judge.prompting import build_prompt, render, system_block  # noqa: E402

ANSWERS = {'yes': ('YES', 'Yes', 'yes', ' YES', ' Yes', ' yes'),
           'no': ('NO', 'No', 'no', ' NO', ' No', ' no')}


def log(event, **values):
    print('GUARDIAN_JUDGE_STAGE ' + json.dumps(dict(t=round(time.time() - STARTED, 1), event=event, **values),
                                               default=str), flush=True)


def emit(stream, records):
    for record in records:
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
    stream.flush()
    os.fsync(stream.fileno())


def engine_kwargs(model, cfg):
    """Only arguments this vLLM version knows; unknown ones are dropped and logged, never fatal."""
    from vllm.engine.arg_utils import EngineArgs
    allowed = {f.name for f in dataclasses.fields(EngineArgs)}
    wanted = dict(model=model, tokenizer=model, max_model_len=int(cfg['max_model_len']),
                  gpu_memory_utilization=float(cfg['gpu_memory_utilization']),
                  enable_prefix_caching=bool(cfg.get('enable_prefix_caching', True)),
                  enable_chunked_prefill=True, max_num_seqs=int(cfg['max_num_seqs']),
                  max_num_batched_tokens=int(cfg['max_num_batched_tokens']), max_logprobs=20, seed=0,
                  logprobs_mode='processed_logprobs')
    if cfg.get('dtype'):
        wanted['dtype'] = cfg['dtype']
    if cfg.get('multimodal'):
        if 'language_model_only' in allowed:
            wanted['language_model_only'] = True
        else:
            wanted['limit_mm_per_prompt'] = {'image': 0, 'video': 0}
    wanted.update(cfg.get('engine_overrides') or {})
    dropped = sorted(k for k in wanted if k not in allowed)
    return {k: v for k, v in wanted.items() if k in allowed}, dropped


def answer_ids(tok):
    ids = {}
    for label, words in ANSWERS.items():
        found = set()
        for word in words:
            encoded = tok.encode(word, add_special_tokens=False)
            if len(encoded) == 1:
                found.add(encoded[0])
        ids[label] = found
    if not ids['yes'] or not ids['no'] or ids['yes'] & ids['no']:
        raise RuntimeError('ANSWER_TOKENS_UNRESOLVED')
    return ids['yes'], ids['no']


def _lse(values):
    top = max(values)
    return top + math.log(sum(math.exp(v - top) for v in values))


def answer_score(output, yes_ids, no_ids):
    """-> (log P(YES) - log P(NO), exact). Exact when both answers carry an explicit logprob.
    Otherwise the missing answer is bounded by the lowest returned logprob (ordering preserved)."""
    sample = output.outputs[0] if output.outputs else None
    if sample is None or not sample.logprobs:
        return None, False
    finite = {tid: e.logprob for tid, e in sample.logprobs[0].items()
              if e.logprob is not None and math.isfinite(e.logprob)}
    if not finite:
        return None, False
    ys = [lp for tid, lp in finite.items() if tid in yes_ids]
    ns = [lp for tid, lp in finite.items() if tid in no_ids]
    if ys and ns:
        return _lse(ys) - _lse(ns), True
    floor = min(finite.values())
    if ys:
        return _lse(ys) - floor, False
    if ns:
        return floor - _lse(ns), False
    return None, False


def sigmoid(x):
    x = max(-60.0, min(60.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def probe(llm, tok, params, yes_ids, no_ids):
    """True when the engine returns logprobs normalised over exactly the allowed answer tokens."""
    text = render(tok, '⟦USER⟧\nHello.', '⟦ASSISTANT⟧\nHello! How can I help you today?', [])
    sample = llm.generate([text], params, use_tqdm=False)[0].outputs[0]
    entries = sample.logprobs[0] if sample.logprobs else {}
    allowed = yes_ids | no_ids
    finite = {tid: e.logprob for tid, e in entries.items() if e.logprob is not None and math.isfinite(e.logprob)}
    mass = sum(math.exp(lp) for tid, lp in finite.items() if tid in allowed)
    outside = sum(1 for tid in finite if tid not in allowed)
    chosen = bool(sample.token_ids) and sample.token_ids[0] in allowed
    exact = chosen and outside == 0 and abs(mass - 1.0) < 1e-3
    return exact, dict(mass_allowed=round(mass, 6), outside_tokens=outside, chosen_allowed=chosen)


def solve_cap(estimates, budget, low, high):
    """Largest cap in [low, high] with sum(min(e, cap)) <= budget (low if even that does not fit)."""
    if sum(min(e, high) for e in estimates) <= budget:
        return high
    lo, hi = low, high
    while hi - lo > 256:
        mid = (lo + hi) // 2
        if sum(min(e, mid) for e in estimates) <= budget:
            lo = mid
        else:
            hi = mid
    return lo


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', required=True)
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--config', required=True)
    ap.add_argument('--stop-at', type=float, required=True, help='wall-clock epoch; no chunk may end after it')
    a = ap.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding='utf-8'))
    rows = [json.loads(line) for line in Path(a.input).read_text(encoding='utf-8').splitlines() if line.strip()]
    max_len = int(cfg['max_model_len'])
    cap_max, cap_min = max_len - 8, int(cfg.get('min_cap_tokens', 8000))
    chunk = int(cfg.get('chunk', 48))

    import vllm
    from vllm import LLM, SamplingParams
    kwargs, dropped = engine_kwargs(a.model, cfg)
    log('engine_start', vllm=getattr(vllm, '__version__', '?'), dropped=dropped,
        kwargs={k: v for k, v in kwargs.items() if k not in ('model', 'tokenizer')})
    llm = LLM(**kwargs)
    tok = llm.get_tokenizer()
    yes_ids, no_ids = answer_ids(tok)
    params = SamplingParams(temperature=1.0, top_p=1.0, max_tokens=1, logprobs=20, seed=0,
                            allowed_token_ids=sorted(yes_ids | no_ids))
    exact_mode, probe_info = probe(llm, tok, params, yes_ids, no_ids)
    log('probe', exact=exact_mode, yes_ids=sorted(yes_ids), no_ids=sorted(no_ids), **probe_info)
    if not exact_mode and cfg.get('require_exact_scores', True):
        with open(a.output, 'a', encoding='utf-8') as out:
            emit(out, [dict(event='failed', reason='EXACT_SCORES_UNAVAILABLE', **probe_info)])
        log('failed', reason='EXACT_SCORES_UNAVAILABLE')
        sys.stdout.flush()
        os._exit(3)

    order = sorted(range(len(rows)), key=lambda i: (
        hashlib.sha1(system_block(rows[i]['prompt']).encode('utf-8', 'replace')).hexdigest(), rows[i]['prompt']))
    prepared = time.time()
    built = {i: build_prompt(tok, rows[i], cap_max) for i in order}
    full = {i: built[i][1] for i in order}
    budget = (a.stop_at - time.time() - 20) * float(cfg.get('planning_tokens_per_second', 6000)) * 0.9
    cap = solve_cap(list(full.values()), budget, cap_min, cap_max)
    log('plan', cap=cap, total_tokens=sum(full.values()), rows_over_cap=sum(1 for v in full.values() if v > cap),
        prepare_seconds=round(time.time() - prepared, 1))

    stats = dict(scored=0, inexact=0, no_score=0, trimmed=0, policy_trimmed=0, skipped=0, tokens=0,
                 gpu_seconds=0.0, emergency_caps=0, planned_cap=cap)
    with open(a.output, 'a', encoding='utf-8') as out:
        emit(out, [dict(event='ready', startup_s=round(time.time() - STARTED, 1), rows=len(rows), cap=cap,
                        exact=exact_mode)])
        position, last_dt = 0, 0.0
        while position < len(order):
            now = time.time()
            if now + last_dt * 1.15 > a.stop_at:
                log('stop_deadline', remaining=len(order) - position)
                break
            if stats['gpu_seconds'] > 30 and stats['tokens']:
                tps = stats['tokens'] / stats['gpu_seconds']
                remaining = order[position:]
                if now + sum(min(full[i], cap) for i in remaining) / tps > a.stop_at - 10:
                    new_cap = solve_cap([full[i] for i in remaining], (a.stop_at - now - 10) * tps * 0.9, cap_min, cap)
                    if new_cap < cap:
                        stats['emergency_caps'] += 1
                        log('emergency_cap', cap=new_cap, previous=cap, tokens_per_s=round(tps),
                            remaining=len(remaining))
                        cap = new_cap
            batch = order[position:position + chunk]
            records, prompts, metas = [], [], []
            for i in batch:
                text, n, trimmed, policy_trimmed = built.pop(i)
                if n > cap:
                    try:
                        text, n, trimmed, policy_trimmed = build_prompt(tok, rows[i], cap)
                    except Exception as error:
                        stats['skipped'] += 1
                        records.append(dict(key=rows[i]['key'], score=None, error=type(error).__name__))
                        continue
                if n > max_len - 2:
                    stats['skipped'] += 1
                    records.append(dict(key=rows[i]['key'], score=None, error='TOO_LONG', tokens=n))
                    continue
                prompts.append(text)
                metas.append((i, n, trimmed, policy_trimmed))
            if prompts:
                t0 = time.time()
                outputs = llm.generate(prompts, params, use_tqdm=False)
                dt = time.time() - t0
                # vLLM keeps prompt order; verify instead of trusting it.
                if len(outputs) != len(prompts) or any(
                        getattr(o, 'prompt', None) not in (None, t) for o, t in zip(outputs, prompts)):
                    raise RuntimeError('JUDGE_OUTPUT_ORDER_MISMATCH')
                for (i, n, trimmed, policy_trimmed), o in zip(metas, outputs):
                    score, exact = answer_score(o, yes_ids, no_ids)
                    if score is None:
                        stats['no_score'] += 1
                    else:
                        stats['scored'] += 1
                        stats['inexact'] += not exact
                    stats['trimmed'] += bool(trimmed)
                    stats['policy_trimmed'] += bool(policy_trimmed)
                    records.append(dict(key=rows[i]['key'], score=score,
                                        p=None if score is None else round(sigmoid(score), 6), exact=exact,
                                        tokens=n, trimmed=bool(trimmed), policy_trimmed=bool(policy_trimmed),
                                        cap=cap))
                stats['tokens'] += sum(m[1] for m in metas)
                stats['gpu_seconds'] += dt
                last_dt = dt
            emit(out, records)
            position += len(batch)
            log('chunk', done=position, of=len(order), seconds=round(last_dt, 1), cap=cap)
        stats['gpu_seconds'] = round(stats['gpu_seconds'], 1)
        stats['tokens_per_second'] = round(stats['tokens'] / stats['gpu_seconds']) if stats['gpu_seconds'] else None
        emit(out, [dict(event='done', seconds=round(time.time() - STARTED, 1), **stats)])
        log('done', **stats)
    try:
        llm.llm_engine.engine_core.shutdown()
    except Exception as error:
        log('shutdown_warning', error=type(error).__name__)


if __name__ == '__main__':
    main()
    sys.stdout.flush()
    os._exit(0)
