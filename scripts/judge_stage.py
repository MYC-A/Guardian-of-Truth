"""GPU stage of the single-pass judge: offline vLLM, one forward pass per row.

Input JSON lines {"key", "prompt", "response", "hints"}. Output JSON lines (fsync after every chunk):
{"event": "ready"}, one {"key", "p", "tokens", "trimmed", "cap"} per row, {"event": "done"}.
p = P(YES) of the first answer token, renormalised over YES/NO (None if neither is in the top 20).

Rows are ordered so identical system blocks (policy + tools) are adjacent: the shared prefix is
computed once by the prefix cache. After the first chunks the measured throughput sets a per-row
token cap so that every remaining row can still be scored before --stop-at; long rows are trimmed
from the middle (see prompting.trim_prompt). No chunk is started if it would end after --stop-at.
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

from guardian_truth.judge.prompting import build_prompt, system_block  # noqa: E402


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
                  max_num_batched_tokens=int(cfg['max_num_batched_tokens']), max_logprobs=20, seed=0)
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


def p_yes(output, tok):
    sample = output.outputs[0] if output.outputs else None
    if sample is None or not sample.logprobs:
        return None
    mass = {'yes': 0.0, 'no': 0.0}
    for token_id, entry in sample.logprobs[0].items():
        word = getattr(entry, 'decoded_token', None)
        if word is None:
            word = tok.decode([token_id])
        word = word.strip().strip('*"\'.:').lower()
        if word in mass and math.isfinite(entry.logprob):
            mass[word] += math.exp(entry.logprob)
    total = mass['yes'] + mass['no']
    return mass['yes'] / total if total > 0 else None


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
    params = SamplingParams(temperature=0.0, max_tokens=1, logprobs=20)
    order = sorted(range(len(rows)), key=lambda i: (
        hashlib.sha1(system_block(rows[i]['prompt']).encode('utf-8', 'replace')).hexdigest(), rows[i]['prompt']))

    stats = dict(scored=0, no_yes_no=0, trimmed=0, skipped=0, tokens=0, gpu_seconds=0.0)
    with open(a.output, 'a', encoding='utf-8') as out:
        emit(out, [dict(event='ready', startup_s=round(time.time() - STARTED, 1), rows=len(rows))])
        log('ready', rows=len(rows))
        cap, chars, last_dt, position = cap_max, 0, 0.0, 0
        while position < len(order):
            now = time.time()
            if now + last_dt * 1.15 > a.stop_at:
                log('stop_deadline', remaining=len(order) - position)
                break
            remaining = order[position:]
            if stats['gpu_seconds'] > 20 and stats['tokens']:
                tps = stats['tokens'] / stats['gpu_seconds']
                cpt = chars / stats['tokens']
                budget = (a.stop_at - now - 10) * tps * 0.9
                estimates = [(len(rows[i]['prompt']) + len(rows[i]['response']) + 6000) / cpt for i in remaining]
                new_cap = solve_cap(estimates, budget, cap_min, cap_max)
                if new_cap != cap:
                    log('cap', cap=new_cap, tokens_per_s=round(tps), remaining=len(remaining))
                    cap = new_cap
            batch = remaining[:chunk]
            records, prompts, metas = [], [], []
            for i in batch:
                try:
                    text, n, trimmed = build_prompt(tok, rows[i], cap)
                except Exception as error:
                    stats['skipped'] += 1
                    records.append(dict(key=rows[i]['key'], p=None, error=type(error).__name__))
                    continue
                if n > max_len - 2:
                    stats['skipped'] += 1
                    records.append(dict(key=rows[i]['key'], p=None, error='TOO_LONG', tokens=n))
                    continue
                prompts.append(text)
                metas.append((i, n, trimmed))
            if prompts:
                t0 = time.time()
                outputs = llm.generate(prompts, params, use_tqdm=False)
                dt = time.time() - t0
                # vLLM keeps prompt order; verify instead of trusting it.
                if len(outputs) != len(prompts) or any(
                        getattr(o, 'prompt', None) not in (None, t) for o, t in zip(outputs, prompts)):
                    raise RuntimeError('JUDGE_OUTPUT_ORDER_MISMATCH')
                for (i, n, trimmed), o in zip(metas, outputs):
                    p = p_yes(o, tok)
                    stats['no_yes_no'] += p is None
                    stats['scored'] += p is not None
                    stats['trimmed'] += bool(trimmed)
                    records.append(dict(key=rows[i]['key'], p=None if p is None else round(p, 6),
                                        tokens=n, trimmed=bool(trimmed), cap=cap))
                stats['tokens'] += sum(m[1] for m in metas)
                stats['gpu_seconds'] += dt
                chars += sum(len(t) for t in prompts)
                last_dt = dt
            emit(out, records)
            position += len(batch)
            log('chunk', done=position, of=len(order), seconds=round(last_dt, 1), cap=cap)
        stats['gpu_seconds'] = round(stats['gpu_seconds'], 1)
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
