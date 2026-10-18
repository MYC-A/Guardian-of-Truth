"""GPU stage of the single-pass judge: offline vLLM, one forward pass per row (plus optional extras).

Input JSON lines {"key", "prompt", "response", "hints"}. Output JSON lines (fsync after every portion):
{"event": "ready"}, one primary record per row, optional extra records, {"event": "done"} (or "failed").

Score. The answer token is restricted to the YES/NO token ids (allowed_token_ids) and logprobs are
read in processed mode, i.e. after that restriction, so both answers always get an explicit
probability: score = log P(YES) - log P(NO) over exactly these tokens (exact=true). A start-up probe
verifies this on the running engine; without it the stage stops when require_exact_scores is true.
With require_exact_scores every individual result must be exact too: an inexact primary result is
written as score=null with bounded_score and error INEXACT_SCORE. An inexact extra always goes to "bounded"
(never into "scores"), so per-key scores used by aggregates are exact only.

Score keys (v3). prompting.score_keys(cfg): cfg['questions'] x cfg['hint_modes'] -> '<question>@<mode>',
default ['overall'] x ['on'] = overall@on. The FIRST key is the primary score and its prompt is rendered
for that key (question and hint mode). All variants of a row come from ONE built prompt (same trimmed
transcript, cap and response) and differ only in the hint block and the final question.

Priority. Primary records of a chunk are written and fsynced before anything else runs. Extra keys never
delay primary coverage: with extras_schedule 'after_primary' (default) they run only after every row has
a primary score; with 'per_chunk' (offline experiments, prefix cache still warm) they run after a chunk
only when the projected time of the remaining primary rows still fits, otherwise the rows are deferred.
Every extras portion is preceded by a time check from MEASURED extras cost (pessimistic before the first
measurement), optionally capped by extras_max_seconds. An extras failure is logged and ends the extras;
primary scores are never lost. Extra records: {"key", "extra": true, "scores", "bounded"}.

Diagnostics in the done event, separately for primary and extras: prompts, prompt / generated / cached
tokens and wall seconds. cached is "unavailable" when the engine does not report it (never a measured 0).

Context budget. Every row is rendered once at full length before inference. One per-row token cap is
planned from the total primary token count, the time left and planning_tokens_per_second. Only if the
measured primary throughput would miss --stop-at is the cap lowered for the remaining rows (event
emergency_cap). The system block (policy + tools) is never trimmed unless it alone exceeds the cap.

Rows. stage_input is split on LF only (read_jsonl): splitlines() also breaks on U+2028, U+2029 and U+0085,
which json.dumps(ensure_ascii=False) keeps inside strings. A row whose prompt cannot be built, or that
the engine rejects, gets its own score=null record (error PROMPT_BUILD_ERROR / GENERATE_ERROR) and the
other rows are still scored. A grouping failure only disables prefix grouping for that row. A failing
batch is retried row by row; only when every row fails and the
known-good probe prompt fails too is the engine treated as broken and the stage stops (the supervisor
keeps the mechanical answer for the rows without a score).

Context. cfg context_mode: 'legacy' (default: the bounded transcript builder of prompting), 'u2' (U2
exact-source packet, lexical ranking) or 'u2_dense' (the same packer plus the pinned local multilingual
encoder as a ranking signal). For u2 modes the stage starts guardian_truth.judge.u2_context as its own CPU
process before the engine (packing overlaps the model start-up) with a fresh run id, waits for it after
the probe at most u2_wait_seconds and always stops it (finally). A packet record is used only for the same
run id, the same stage_input SHA256 and the same row hash. A row uses its packet in place of the transcript
only when the rendered prompt, with the turn under review WHOLE, fits the planned cap; otherwise, and for
every row the packer rejected, did not finish or that failed a check, the legacy builder runs on the full
transcript with the reason in the record (legacy:<reason>). One model call per row in every mode.

Caps. cap is the planned per-row token cap (time plan); the model context (max_model_len minus the question
margin) is the hard limit. A prompt over the planned cap is sent only within the hard limit, marked over_cap,
and its extra tokens enter the time forecast of the remaining rows. response_trimmed marks every row whose
turn under review is not shown whole (legacy builder: head + tail only when even no dialogue leaves room).
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import dataclasses
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

STARTED = time.time()
ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / 'src')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from guardian_truth.judge.prompting import (build_prompt, count_tokens, hints_shown,  # noqa: E402
                                            question_margin, render, score_keys, system_block, variant_text)
from guardian_truth.judge.blind_review import validate_review_config  # noqa: E402

SCHEDULES = ('after_primary', 'per_chunk')
CONTEXT_MODES = ('legacy', 'u2', 'u2_dense')
_SLEEP = time.sleep

ANSWERS = {'yes': ('YES', 'Yes', 'yes', ' YES', ' Yes', ' yes'),
           'no': ('NO', 'No', 'no', ' NO', ' No', ' no')}

PROBE_PROMPT = '\u27e6USER\u27e7\nHello.'
PROBE_RESPONSE = '\u27e6ASSISTANT\u27e7\nHello! How can I help you today?'


class RowDeadline(Exception):
    """A row that was not submitted or retried because --stop-at had passed."""


def log(event, **values):
    print('GUARDIAN_JUDGE_STAGE ' + json.dumps(dict(t=round(time.time() - STARTED, 1), event=event, **values),
                                               default=str), flush=True)


def emit(stream, records):
    for record in records:
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
    stream.flush()
    os.fsync(stream.fileno())


def read_jsonl(path):
    """Records of a JSONL file, split on LF only. CRLF and blank lines are tolerated (JSON allows the
    trailing CR). Unicode line separators inside strings stay inside their record."""
    with open(path, encoding='utf-8', newline='') as stream:
        text = stream.read()
    return [json.loads(line) for line in text.split('\n') if line.strip()]


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
    """-> (log P(YES) - log P(NO), exact). exact=True only when THIS result meets the whole scoring contract
    (the start-up probe checks it once, every result is checked again): both answers carry a finite logprob,
    no token outside the allowed answers has a finite logprob, the allowed answers carry the whole mass
    (|sum - 1| < 1e-3) and the sampled token is an allowed answer. A result with both answers that breaks the
    contract keeps its log-odds but exact=False. With one answer missing, it is bounded by the lowest returned
    logprob (ordering preserved), exact=False."""
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
        allowed = yes_ids | no_ids
        outside = any(tid not in allowed for tid in finite)
        mass = sum(math.exp(lp) for tid, lp in finite.items() if tid in allowed)
        tokens = getattr(sample, 'token_ids', None)
        chosen = bool(tokens) and tokens[0] in allowed
        return _lse(ys) - _lse(ns), (not outside) and abs(mass - 1.0) < 1e-3 and chosen
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
    text = render(tok, PROBE_PROMPT, PROBE_RESPONSE, [])
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


class Usage:
    """Prompt / generated / cached tokens and wall time of one kind of call."""

    def __init__(self):
        self.prompts = self.prompt_tokens = self.generated_tokens = 0
        self.cached_tokens, self.cache_reported, self.wall = 0, True, 0.0

    def add(self, outputs, seconds):
        self.wall += seconds
        for o in outputs:
            self.prompts += 1
            ids = getattr(o, 'prompt_token_ids', None)
            self.prompt_tokens += len(ids) if ids is not None else 0
            sample = o.outputs[0] if getattr(o, 'outputs', None) else None
            self.generated_tokens += len(getattr(sample, 'token_ids', None) or []) if sample is not None else 0
            cached = getattr(o, 'num_cached_tokens', None)
            if isinstance(cached, int) and not isinstance(cached, bool):
                self.cached_tokens += cached
            else:
                self.cache_reported = False

    def report(self):
        known = self.cache_reported and self.prompts > 0
        return dict(prompts=self.prompts, prompt_tokens=self.prompt_tokens, generated_tokens=self.generated_tokens,
                    cached_tokens=self.cached_tokens if known else 'unavailable',
                    uncached_tokens=self.prompt_tokens - self.cached_tokens if known else 'unavailable',
                    cache_hit=round(self.cached_tokens / self.prompt_tokens, 4) if known and self.prompt_tokens
                    else 'unavailable', wall_seconds=round(self.wall, 2))


def check_order(outputs, prompts):
    # vLLM keeps prompt order; verify instead of trusting it.
    if len(outputs) != len(prompts) or any(
            getattr(o, 'prompt', None) not in (None, t) for o, t in zip(outputs, prompts)):
        raise RuntimeError('JUDGE_OUTPUT_ORDER_MISMATCH')


def _error_text(error):
    return ('%s: %s' % (type(error).__name__, error))[:300]


def generate_rows(llm, prompts, params, deadline, healthy):
    """-> (one output or Exception per prompt, batch error or None). A failing batch is retried prompt by
    prompt, so an input the engine rejects costs only its own row. When every retried prompt fails and
    the known-good probe fails too, raise the batch error. No new call, including the probe, starts at
    or after the deadline. In-flight calls are bounded by the supervisor."""
    if time.time() >= deadline:
        return [RowDeadline('STOP_AT_PASSED') for _ in prompts], None
    try:
        outputs = llm.generate(prompts, params, use_tqdm=False)
        check_order(outputs, prompts)
        return list(outputs), None
    except Exception as error:  # noqa: BLE001 - decided below: a bad row or a broken engine
        batch_error = error
    results = []
    for text in prompts:
        if time.time() >= deadline:
            results.append(RowDeadline('STOP_AT_PASSED'))
            continue
        try:
            one = llm.generate([text], params, use_tqdm=False)
            check_order(one, [text])
            results.append(one[0])
        except Exception as error:  # noqa: BLE001 - recorded for this row only
            results.append(error)
    failed = [r for r in results if isinstance(r, Exception) and not isinstance(r, RowDeadline)]
    if failed and len(failed) == len(results) and time.time() < deadline and not healthy():
        raise batch_error
    return results, batch_error


def build_row(tok, row, cap):
    """-> (text, n_tokens, trimmed, policy_trimmed, context). The turn under review is shown whole whenever
    the prompt fits the cap with it: first with the U2 packet (row['context']) in place of the transcript, then
    through the legacy builder, which gives up dialogue and hints before it touches the turn (then turn head +
    tail, then policy); context says which path was taken (u2 label, legacy, legacy:<reason>)."""
    hints = list(row.get('hints') or [])
    packet = row.get('context')
    if packet is not None:
        text = render(tok, packet, row['response'], hints)
        n = count_tokens(tok, text)
        if n <= cap:
            return text, n, False, False, row.get('context_label') or 'u2'
        reason = 'legacy:PACKET_OVER_CAP'
    else:
        reason = row.get('context_reason') or 'legacy'
    return tuple(build_prompt(tok, row, cap)) + (reason,)


def row_digest(prompt, response):
    """Same as guardian_truth.judge.u2_context.row_digest (kept here so that the stage does not import the packer)."""
    return hashlib.sha256((str(prompt) + '\x00' + str(response)).encode('utf-8', 'surrogatepass')).hexdigest()


def file_sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.sha256(stream.read()).hexdigest()


U2_OPTION_FLAGS = (('u2_action_policy', '--action-policy', bool), ('u2_action_synonyms', '--action-synonyms', bool),
                   ('u2_dense_passage_pieces', '--dense-passage-pieces', bool),
                   ('u2_dense_fusion', '--dense-fusion', ('rrf', 'remainder')),
                   ('u2_dense_scope', '--dense-scope', ('all', 'policy')),
                   ('u2_dense_query_chars', '--dense-query-chars', int))


def u2_packer_flags(cfg):
    """Packer flags for the u2_* option keys (absent or None: packer default). An invalid value raises
    ValueError('U2_OPTIONS_INVALID') BEFORE the packer starts: the stage logs packer_start_failed and every row keeps
    the legacy context, instead of a packer process that dies in argparse."""
    flags = []
    for key, flag, kind in U2_OPTION_FLAGS:
        value = cfg.get(key)
        if value is None:
            continue
        if kind is bool:
            if not isinstance(value, bool):
                raise ValueError('U2_OPTIONS_INVALID: %s=%r' % (key, value))
            flags += [flag] if value else []
        elif kind is int:
            if isinstance(value, bool) or not isinstance(value, int) or value < 32:
                raise ValueError('U2_OPTIONS_INVALID: %s=%r' % (key, value))
            flags += [flag, str(value)]
        elif value not in kind:
            raise ValueError('U2_OPTIONS_INVALID: %s=%r' % (key, value))
        else:
            flags += [flag, value]
    return flags


def start_packer(a, cfg, mode, packets_path, run_id):
    """U2 packing as its own CPU process (same process group as the stage)."""
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT / 'src'), str(ROOT)] + ([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
    command = [sys.executable, '-m', 'guardian_truth.judge.u2_context', '--input', str(a.input),
               '--output', str(packets_path), '--run-id', run_id, '--deadline', repr(a.stop_at),
               '--budget-bytes', str(int(cfg.get('u2_budget_bytes', 20000))),
               '--embed-seconds-per-row', str(float(cfg.get('u2_embed_seconds_per_row', 2.0))),
               '--embed-total-seconds', str(float(cfg.get('u2_embed_total_seconds', 240.0)))]
    if not cfg.get('u2_full_catalog', True):
        command.append('--no-full-catalog')
    command += u2_packer_flags(cfg)
    if mode == 'u2_dense':
        encoder = Path(cfg.get('u2_encoder_dir', 'model/encoder'))
        command += ['--dense-encoder', str(encoder if encoder.is_absolute() else ROOT / encoder)]
    with open(Path(packets_path).with_suffix('.log'), 'w', encoding='utf-8') as stream:
        return subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env)


def stop_packer(packer):
    if packer is None or packer.poll() is not None:
        return
    try:
        packer.kill()
        packer.wait(5)
    except Exception:  # noqa: BLE001 - cleanup must not raise
        pass


def collect_packets(packer, packets_path, wait_until, run_id, input_sha256):
    """-> ({row key: packet record}, status, done event). Waits for the packer at most until wait_until, then
    stops it. Records of another run or another stage_input are rejected; a torn last line is ignored."""
    while packer.poll() is None and time.time() < wait_until:
        _SLEEP(0.2)
    code = packer.poll()
    status = 'DONE' if code == 0 else ('STOPPED_AT_WAIT_LIMIT' if code is None else 'EXITED_%d' % code)
    stop_packer(packer)
    items = []
    try:
        with open(packets_path, encoding='utf-8', newline='') as stream:
            lines = stream.read().split('\n')
    except OSError:
        lines = []
    for line in lines:
        try:
            item = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(item, dict):
            items.append(item)
    start = items[0] if items and items[0].get('event') == 'start' else None
    if start is None or start.get('run_id') != run_id or start.get('input_sha256') != input_sha256:
        return {}, status + ':REJECTED_RUN_OR_INPUT', None
    records = {i['key']: i for i in items[1:] if 'key' in i and i.get('run_id') == run_id and 'event' not in i}
    done = next((i for i in items if i.get('event') == 'done' and i.get('run_id') == run_id), None)
    return records, status, done


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', required=True)
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--config', required=True)
    ap.add_argument('--stop-at', type=float, required=True, help='wall-clock epoch; no new primary call starts after it')
    a = ap.parse_args(argv)
    packers = []
    try:
        return _main(a, packers)
    finally:
        for packer in packers:
            stop_packer(packer)


def _main(a, packers):
    cfg = json.loads(Path(a.config).read_text(encoding='utf-8'))
    rows = read_jsonl(a.input)
    keys = score_keys(cfg)
    primary_key, primary_q, primary_m = keys[0]
    extras_keys = keys[1:]
    schedule = cfg.get('extras_schedule', 'after_primary')
    if schedule not in SCHEDULES:
        raise ValueError('BAD_EXTRAS_SCHEDULE: %s' % schedule)
    extras_cap = cfg.get('extras_max_seconds')
    require_exact = bool(cfg.get('require_exact_scores', True))
    try:
        review_settings = validate_review_config(cfg)
    except ValueError as error:
        log('review_config_invalid', error=str(error), using='off')
        review_settings = validate_review_config({})
    if all(m == 'off' for _, _, m in keys):
        for row in rows:
            row['hints'] = []
    max_len = int(cfg['max_model_len'])
    chunk = int(cfg.get('chunk', 48))
    context_mode = cfg.get('context_mode', 'legacy')
    if context_mode not in CONTEXT_MODES:
        log('context_mode_invalid', value=context_mode, using='legacy')
        context_mode = 'legacy'
    run_id = uuid.uuid4().hex
    packets_path = Path(a.output).with_name('packets-%s.jsonl' % run_id)
    packer, packer_error, input_sha256 = None, None, None
    if context_mode != 'legacy':
        try:
            input_sha256 = file_sha256(a.input)
            packer = start_packer(a, cfg, context_mode, packets_path, run_id)
            packers.append(packer)
        except Exception as error:  # noqa: BLE001 - without a packer every row keeps the legacy context
            packer_error = _error_text(error)
            log('packer_start_failed', error=packer_error)
    if review_settings['review_mode'] != 'off' and input_sha256 is None:
        input_sha256 = file_sha256(a.input)

    import vllm
    from vllm import LLM, SamplingParams
    kwargs, dropped = engine_kwargs(a.model, cfg)
    log('engine_start', vllm=getattr(vllm, '__version__', '?'), dropped=dropped, keys=[k for k, _, _ in keys],
        schedule=schedule, kwargs={k: v for k, v in kwargs.items() if k not in ('model', 'tokenizer')})
    llm = LLM(**kwargs)
    tok = llm.get_tokenizer()
    yes_ids, no_ids = answer_ids(tok)
    params = SamplingParams(temperature=1.0, top_p=1.0, max_tokens=1, logprobs=20, seed=0,
                            allowed_token_ids=sorted(yes_ids | no_ids))
    exact_mode, probe_info = probe(llm, tok, params, yes_ids, no_ids)
    log('probe', exact=exact_mode, yes_ids=sorted(yes_ids), no_ids=sorted(no_ids), **probe_info)
    if not exact_mode and require_exact:
        with open(a.output, 'a', encoding='utf-8') as out:
            emit(out, [dict(event='failed', reason='EXACT_SCORES_UNAVAILABLE', **probe_info)])
        log('failed', reason='EXACT_SCORES_UNAVAILABLE')
        for process in packers:
            stop_packer(process)
        sys.stdout.flush()
        os._exit(3)
    margin = question_margin(tok, keys)
    cap_max = max_len - 8 - margin - review_settings['review_input_reserve_tokens']
    cap_min = min(int(cfg.get('min_cap_tokens', 8000)), cap_max)
    probe_text = render(tok, PROBE_PROMPT, PROBE_RESPONSE, [])
    hard_cap = max_len - 2 - margin
    context_stats = dict(mode=context_mode)
    if context_mode != 'legacy':
        if packer is None:
            packets, packer_status, packer_done = {}, 'NOT_STARTED', None
        else:
            packets, packer_status, packer_done = collect_packets(
                packer, packets_path, min(time.time() + float(cfg.get('u2_wait_seconds', 90)), a.stop_at - 60),
                run_id, input_sha256)
        sizes = []
        for row in rows:
            packet = packets.get(row.get('key'))
            if packet is None:
                row['context_reason'] = 'legacy:PACKET_NOT_READY'
            elif packet.get('row_sha256') != row_digest(row.get('prompt'), row.get('response')):
                row['context_reason'] = 'legacy:PACKET_ROW_MISMATCH'
            elif packet.get('mode') == 'u2' and isinstance(packet.get('text'), str):
                row['context'] = packet['text']
                fallback = packet.get('dense_fallback')
                row['context_label'] = ('u2_dense' if packet.get('ranking') == 'dense' else
                                        'u2(dense_fallback:%s)' % fallback.split(':')[0] if fallback else 'u2')
                sizes.append(int(packet.get('source_bytes') or 0))
            elif packet.get('mode') == 'full_input':
                row['context_reason'] = 'full_input'
            else:
                row['context_reason'] = 'legacy:%s' % (packet.get('reason') or packet.get('mode'))
        context_stats.update(run_id=run_id, packer=packer_status, packer_error=packer_error, packets=len(packets),
                             packer_seconds=(packer_done or {}).get('seconds'),
                             packer_modes=(packer_done or {}).get('modes'),
                             packer_rankings=(packer_done or {}).get('rankings'),
                             encoder=(packer_done or {}).get('encoder'),
                             encoder_stats=(packer_done or {}).get('encoder_stats'), packet_rows=len(sizes),
                             packet_source_bytes_max=max(sizes) if sizes else None,
                             packet_source_bytes_total=sum(sizes))
        u2_options = {k: cfg[k] for k, _, _ in U2_OPTION_FLAGS if k in cfg}
        if u2_options:
            context_stats['u2_options'] = u2_options
        log('packets', **context_stats)

    def healthy():
        try:
            check_order(llm.generate([probe_text], params, use_tqdm=False), [probe_text])
            return True
        except Exception:  # noqa: BLE001 - the engine itself is broken
            return False

    group_errors = []

    def group_key(i):
        try:
            return hashlib.sha1(system_block(rows[i]['prompt']).encode('utf-8', 'replace')).hexdigest()
        except Exception:  # noqa: BLE001 - an ungroupable row is still scored, only without prefix grouping
            group_errors.append(i)
            return ''

    order = sorted(range(len(rows)), key=lambda i: (group_key(i), str(rows[i].get('prompt', ''))))
    prepared = time.time()
    built, row_errors = {}, {}
    for i in order:
        try:
            built[i] = build_row(tok, rows[i], cap_max)
        except Exception as error:  # noqa: BLE001 - one bad row must not cost the other rows
            row_errors[i] = _error_text(error)
    full = {i: built[i][1] if i in built else 0 for i in order}
    plan_tps = float(cfg.get('planning_tokens_per_second', 6000))
    budget = (a.stop_at - time.time() - 20) * plan_tps * 0.9
    cap = solve_cap(list(full.values()), budget, cap_min, cap_max)
    log('plan', cap=cap, margin=margin, total_tokens=sum(full.values()),
        rows_over_cap=sum(1 for v in full.values() if v > cap), prepare_seconds=round(time.time() - prepared, 1),
        prompt_build_errors=len(row_errors), group_errors=len(group_errors),
        first_build_error=next(iter(row_errors.values()), None))

    primary_use, extras_use = Usage(), Usage()
    stats = dict(scored=0, inexact=0, no_score=0, trimmed=0, policy_trimmed=0, skipped=0, tokens=0,
                 emergency_caps=0, planned_cap=cap, hints_shown=0, row_errors=0, deadline_rows=0,
                 group_errors=len(group_errors), over_cap=0, over_cap_tokens=0, response_trimmed=0, contexts={},
                 hard_cap=hard_cap)
    xstats = dict(rows_done=0, rows_deferred=0, rows_skipped_deadline=0, inexact=0, row_errors=0, failed=None)
    bases, pending = {}, []

    def primary_tps():
        return stats['tokens'] / primary_use.wall if primary_use.wall > 30 and stats['tokens'] else plan_tps

    def extras_seconds(n_rows):
        n = n_rows * len(extras_keys)
        if extras_use.prompts:
            return extras_use.wall / extras_use.prompts * n * 1.15
        per_row = (primary_use.wall / primary_use.prompts) if primary_use.prompts else 0.0
        return max(per_row, sum(bases[i][1] for i in pending[:1]) / plan_tps if pending else 0.0) * n * 1.15

    def extras_allowed(n_rows, reserve_primary):
        if xstats['failed'] or not n_rows:
            return False
        need = extras_seconds(n_rows)
        if extras_cap is not None and extras_use.wall + need > float(extras_cap):
            return False
        return time.time() + need + reserve_primary <= a.stop_at - 10

    def run_extras(out, idx):
        prompts, where = [], []
        for i in idx:
            text = bases[i][0]
            for key, question, mode in extras_keys:
                prompts.append(variant_text(text, question, mode))
                where.append((i, key))
        t0 = time.time()
        try:
            outputs = llm.generate(prompts, params, use_tqdm=False)
            check_order(outputs, prompts)
        except Exception as error:  # noqa: BLE001 - extras must never cost the primary scores
            xstats['failed'] = '%s: %s' % (type(error).__name__, error)
            log('extras_failed', error=xstats['failed'])
            return
        extras_use.add(outputs, time.time() - t0)
        per = {i: (dict(), dict()) for i in idx}
        status, hashes, errors = ({i: {} for i in idx} for _ in range(3))
        for (i, key), text, o in zip(where, prompts, outputs):
            hashes[i][key] = hashlib.sha256(text.encode('utf-8')).hexdigest()
            try:
                score, exact = answer_score(o, yes_ids, no_ids)
                if score is not None and not math.isfinite(score):
                    raise ValueError('NON_FINITE_SCORE')
            except Exception as error:
                xstats['row_errors'] += 1
                status[i][key] = 'error'
                errors[i][key] = _error_text(error)
                continue
            if score is None:
                status[i][key] = 'missing'
                continue
            if exact:
                status[i][key] = 'exact'
                per[i][0][key] = score
            else:                       # never mixed with exact scores, whatever require_exact says
                status[i][key] = 'inexact'
                per[i][1][key] = score
                xstats['inexact'] += 1
        emit(out, [dict(key=rows[i]['key'], extra=True, scores=per[i][0], bounded=per[i][1],
                        score_status=status[i], model_input_sha256=hashes[i], errors=errors[i]) for i in idx])
        xstats['rows_done'] += len(idx)
        for i in idx:
            bases.pop(i, None)

    with open(a.output, 'a', encoding='utf-8') as out, ExitStack() as review_files:
        primary_inputs = None
        primary_input_meta = {}
        if review_settings['review_mode'] != 'off':
            from guardian_truth.judge.review_stage import PrimaryInputs
            try:
                primary_inputs = review_files.enter_context(PrimaryInputs(
                    Path(a.output).with_name('primary-inputs-%s.jsonl' % run_id), run_id, input_sha256))
                emit(out, [dict(event='primary_inputs', path=str(primary_inputs.path),
                                run_id=run_id, input_sha256=input_sha256)])
            except Exception as error:
                log('primary_inputs_unavailable', error=_error_text(error))
        emit(out, [dict(event='ready', startup_s=round(time.time() - STARTED, 1), rows=len(rows), cap=cap,
                        exact=exact_mode, keys=[k for k, _, _ in keys], schedule=schedule)])
        review_parts, deferred_review, review_timing = [], [], {}

        def review_batch(portion, reserve_primary=0.0):
            from guardian_truth.judge.review_stage import ReviewContext, run_review
            per_row = primary_use.wall / primary_use.prompts if primary_use.prompts else 5.0
            if time.time() >= a.stop_at - reserve_primary - 10:
                return False
            gen_params = SamplingParams(temperature=float(review_settings['prepass_temperature']), top_p=1.0,
                                        max_tokens=int(review_settings['prepass_max_tokens']),
                                        seed=int(review_settings['prepass_seed']))
            def record_review(records):
                for record in records:
                    if record.get('event') == 'review_done':
                        record['event'] = 'review_portion_done'
                emit(out, records)
            log('review_start', arm=review_settings['review_mode'], content=review_settings['review_content'],
                rows=len(portion), reserve_primary_seconds=round(reserve_primary, 2))
            try:
                part = run_review(ReviewContext(
                    llm=llm, tok=tok, rows=rows, order=portion, settings=review_settings, score_params=params,
                    gen_params=gen_params, yes_ids=yes_ids, no_ids=no_ids, answer_score=answer_score,
                    generate_rows=generate_rows, healthy=healthy, emit=record_review,
                    stop_at=a.stop_at - reserve_primary, hard_cap=hard_cap, prepass_cap=max_len - 8,
                    chunk=chunk, log=log, primary_inputs=primary_inputs, usage=Usage,
                    primary_seconds_per_row=per_row, timing=review_timing,
                    primary_tokens_per_row=stats['tokens']/max(primary_use.prompts,1),
                    defer_on_budget=reserve_primary > 0))
                if part.get('deferred_rows'):
                    return False
                review_parts.append(part)
            except Exception as error:
                # Earlier portions stay durable; an engine failure cannot erase them.
                log('review_portion_failed', error=_error_text(error))
            return True

        position, last_dt = 0, 0.0
        while position < len(order):
            now = time.time()
            if now + last_dt * 1.15 >= a.stop_at:
                remaining = order[position:]
                stats['deadline_rows'] += len(remaining)
                stats['skipped'] += len(remaining)
                emit(out, [dict(key=rows[i]['key'], score=None, error='DEADLINE') for i in remaining])
                log('stop_deadline', remaining=len(remaining))
                break
            if primary_use.wall > 30 and stats['tokens']:
                tps = primary_tps()
                remaining = order[position:]
                # rows sent over the planned cap so far: assume the same mean excess for the rest
                extra = stats['over_cap_tokens'] / max(primary_use.prompts, 1) * len(remaining)
                if now + (sum(min(full[i], cap) for i in remaining) + extra) / tps > a.stop_at - 10:
                    new_cap = solve_cap([full[i] for i in remaining], (a.stop_at - now - 10) * tps * 0.9 - extra,
                                        cap_min, cap)
                    if new_cap < cap:
                        stats['emergency_caps'] += 1
                        log('emergency_cap', cap=new_cap, previous=cap, tokens_per_s=round(tps),
                            remaining=len(remaining))
                        cap = new_cap
            batch = order[position:position + chunk]
            records, prompts, metas = [], [], []
            for i in batch:
                if i in row_errors:
                    stats['skipped'] += 1
                    stats['row_errors'] += 1
                    records.append(dict(key=rows[i]['key'], score=None, error='PROMPT_BUILD_ERROR',
                                        detail=row_errors[i]))
                    continue
                text, n, trimmed, policy_trimmed, context = built.pop(i)
                if n > cap:
                    try:
                        text, n, trimmed, policy_trimmed, context = build_row(tok, rows[i], cap)
                    except Exception as error:
                        stats['skipped'] += 1
                        stats['row_errors'] += 1
                        records.append(dict(key=rows[i]['key'], score=None, error='PROMPT_BUILD_ERROR',
                                            detail=_error_text(error)))
                        continue
                if n > hard_cap:
                    stats['skipped'] += 1
                    records.append(dict(key=rows[i]['key'], score=None, error='TOO_LONG', tokens=n, context=context))
                    continue
                over = n > cap
                response_trimmed = rows[i]['response'] not in text
                try:
                    ptext = variant_text(text, primary_q, primary_m)
                    n_p = n if ptext == text else count_tokens(tok, ptext)
                    shown = hints_shown(text)
                except Exception as error:  # noqa: BLE001 - one bad row must not cost the chunk
                    stats['skipped'] += 1
                    stats['row_errors'] += 1
                    records.append(dict(key=rows[i]['key'], score=None, error='PROMPT_BUILD_ERROR',
                                        detail=_error_text(error)))
                    continue
                if extras_keys:
                    bases[i] = (text, n)
                primary_input_meta[i] = dict(model_input_sha256=hashlib.sha256(ptext.encode('utf-8')).hexdigest())
                if primary_inputs is not None:
                    try:
                        primary_input_meta[i] = primary_inputs.put(rows[i], ptext, tok, cap, trimmed, policy_trimmed)
                    except Exception as error:
                        log('primary_input_write_error', key=rows[i]['key'], error=_error_text(error))
                prompts.append(ptext)
                metas.append((i, n_p, trimmed, policy_trimmed, shown, context, over, response_trimmed))
                stats['contexts'][context] = stats['contexts'].get(context, 0) + 1
            if prompts:
                t0 = time.time()
                outputs, batch_error = generate_rows(llm, prompts, params, a.stop_at, healthy)
                if batch_error is not None:
                    log('chunk_error', error=_error_text(batch_error), rows=len(prompts),
                        failed_rows=sum(1 for o in outputs if isinstance(o, Exception)))
                last_dt = time.time() - t0
                primary_use.add([o for o in outputs if not isinstance(o, Exception)], last_dt)
                for (i, n, trimmed, policy_trimmed, shown, context, over, response_trimmed), o in zip(metas, outputs):
                    if isinstance(o, Exception):
                        stats['skipped'] += 1
                        late = isinstance(o, RowDeadline)
                        stats['deadline_rows' if late else 'row_errors'] += 1
                        bases.pop(i, None)
                        records.append(dict(key=rows[i]['key'], score=None, tokens=n, cap=cap,
                                            error='DEADLINE' if late else 'GENERATE_ERROR', detail=_error_text(o)))
                        continue
                    try:
                        score, exact = answer_score(o, yes_ids, no_ids)
                        if score is not None and not math.isfinite(score):
                            raise ValueError('NON_FINITE_SCORE')
                    except Exception as error:
                        stats['row_errors'] += 1
                        records.append(dict(key=rows[i]['key'], score=None, exact=False,
                                            error='PRIMARY_SCORE_ERROR', detail=_error_text(error)))
                        continue
                    record = dict(key=rows[i]['key'], score_key=primary_key, tokens=n, trimmed=bool(trimmed),
                                  policy_trimmed=bool(policy_trimmed), hints_shown=bool(shown), cap=cap,
                                  context=context, over_cap=bool(over), response_trimmed=bool(response_trimmed))
                    record.update(primary_input_meta.get(i, {}))
                    stats['over_cap'] += bool(over)
                    stats['over_cap_tokens'] += max(0, n - cap)
                    stats['response_trimmed'] += bool(response_trimmed)
                    if score is not None and not exact and require_exact:
                        stats['inexact'] += 1
                        record.update(score=None, bounded_score=score, exact=False, error='INEXACT_SCORE')
                        bases.pop(i, None)
                    elif score is None:
                        stats['no_score'] += 1
                        record.update(score=None, exact=False)
                        bases.pop(i, None)
                    else:
                        stats['scored'] += 1
                        stats['inexact'] += not exact
                        record.update(score=score, p=round(sigmoid(score), 6), exact=exact, scores={primary_key: score})
                        if i in bases:
                            pending.append(i)
                    stats['trimmed'] += bool(trimmed)
                    stats['policy_trimmed'] += bool(policy_trimmed)
                    stats['hints_shown'] += bool(shown)
                    records.append(record)
                stats['tokens'] += sum(m[1] for m, o in zip(metas, outputs) if not isinstance(o, Exception))
            emit(out, records)          # primary results are durable before any extra call
            if primary_inputs is not None:
                try:
                    primary_inputs.flush()
                except Exception as error:
                    log('primary_input_flush_error', error=_error_text(error))
            position += len(batch)
            log('chunk', done=position, of=len(order), seconds=round(last_dt, 1), cap=cap)
            if review_settings['review_mode'] != 'off' and review_settings['review_schedule'] == 'per_chunk':
                reserve = sum(min(full[i], cap) for i in order[position:]) / primary_tps() * 1.15
                if not review_batch(batch, reserve):
                    deferred_review.extend(batch)
                    log('review_deferred', rows=len(batch), reserve_primary_seconds=round(reserve, 2))
            if schedule == 'per_chunk' and pending:
                current = [i for i in pending if i in batch]
                reserve = sum(min(full[i], cap) for i in order[position:]) / primary_tps()
                if extras_allowed(len(current), reserve):
                    run_extras(out, current)
                    pending = [i for i in pending if i not in current]
                else:
                    xstats['rows_deferred'] += len(current)
        while pending and not xstats['failed']:
            portion = pending[:chunk]
            if not extras_allowed(len(portion), 0.0):
                break
            run_extras(out, portion)
            pending = pending[len(portion):]
        xstats['rows_skipped_deadline'] = len(pending) if not xstats['failed'] else 0
        if pending and not xstats['failed']:
            log('extras_deadline', rows_without_extras=len(pending))
        review_stats = None
        if review_settings['review_mode'] != 'off' and review_settings['review_schedule'] == 'per_chunk':
            from guardian_truth.judge.review_stage import merge_review_stats
            for offset in range(0, len(deferred_review), chunk):
                if not review_batch(deferred_review[offset:offset + chunk]):
                    break
            review_stats = merge_review_stats(review_parts, len(rows), review_settings)
            emit(out, [dict(event='review_done', **review_stats)])
            log('review_done', **review_stats)
        elif review_settings['review_mode'] != 'off':
            from guardian_truth.judge.review_stage import ReviewContext, run_review
            gen_params = SamplingParams(temperature=float(review_settings['prepass_temperature']), top_p=1.0,
                                        max_tokens=int(review_settings['prepass_max_tokens']),
                                        seed=int(review_settings['prepass_seed']))
            log('review_start', arm=review_settings['review_mode'], prepass_max_tokens=gen_params.max_tokens)
            try:
                review_stats = run_review(ReviewContext(
                    llm=llm, tok=tok, rows=rows, order=order, settings=review_settings, score_params=params,
                    gen_params=gen_params, yes_ids=yes_ids, no_ids=no_ids, answer_score=answer_score,
                    generate_rows=generate_rows, healthy=healthy, emit=lambda records: emit(out, records),
                    stop_at=a.stop_at, hard_cap=hard_cap, prepass_cap=max_len - 8, chunk=chunk, log=log,
                    primary_inputs=primary_inputs,
                    usage=Usage, primary_seconds_per_row=(primary_use.wall / primary_use.prompts
                                                          if primary_use.prompts else 5.0)))
            except Exception as error:  # noqa: BLE001 - review must never cost the primary scores
                review_stats = dict(failed=_error_text(error))
                log('review_failed', error=review_stats['failed'])
        report_p, report_x = primary_use.report(), extras_use.report()
        review_wall = sum((review_stats or {}).get(role, {}).get('wall_seconds', 0)
                          for role in ('prepass', 'final'))
        tps = round(stats['tokens'] / primary_use.wall) if primary_use.wall else None
        emit(out, [dict(event='done', seconds=round(time.time() - STARTED, 1), keys=[k for k, _, _ in keys],
                        gpu_seconds=round(primary_use.wall + extras_use.wall + review_wall, 1), tokens_per_second=tps,
                        primary=report_p, extras=dict(report_x, **xstats), context=context_stats, review=review_stats,
                        **stats)])
        log('done', tokens_per_second=tps, primary=report_p, extras=dict(report_x, **xstats), context=context_stats,
            **stats)
    try:
        llm.llm_engine.engine_core.shutdown()
    except Exception as error:
        log('shutdown_warning', error=type(error).__name__)


if __name__ == '__main__':
    main()
    sys.stdout.flush()
    os._exit(0)
