"""Local A100 experiment runner (no paid APIs; single local OpenAI-compatible endpoint).

Same pipeline and receipts as guardian_addons.run2, but every model call goes to a
LOCAL endpoint (vLLM or llama.cpp llama-server) through the same durable Transport
(exact-equivalence cache keyed by provider+endpoint+model+request+attempt).

Variants (one change at a time; the decision rule actually scored is listed):
  AM    : one execution with no pre-pass; TWO decision rules read from the same
          saved primary replies -> A (binary_rfix: R_fix alone) and M (binary:
          R_fix + strict v6fix@403d811e layers). No extra calls for either.
  B     : M + leak-free neutral blind pre-pass ('blind2' from 403d811e): the
          pre-pass sees the original prompt only, never the current move.
  Bopen : equal-call control for B: identical schema/prompt intent but the
          pre-pass SEES the current move ('open').
  T     : B + typed condition_checks in the pre-pass schema ('blind2_typed').
  E     : T + deterministic evaluator over the analysis' own checks
          ('blind2_typed_eval'); only a CONTRADICTION changes the review request.
  L     : OLD v6fix from the detached worktree wt-v6fix-5330dcc4 (5330dcc4) on
          the same rows/model — separate script l_v6fix_old.py (old code import).

Usage:
  python -m experiments.guardian_local_a100.run_local --set dev --variant AM \
      --backend vllm --model-id 'ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0' \
      [--rep 1] [--workers 4] [--ids a,b] [--max-calls 50000]

Sets: dev, devT, frozen, contrast (short diagnostics), f120:regression / f120:dev /
f120:holdout (frozen120 family splits), holdout2, and the REAL sets extracted from the
pinned commit 403d811e into GUARDIAN_DATA_ROOT (default
/workspace/guardian/data_root_403d811e): valid46, lb_long, lb2_long, lb3_long,
ext_tau2 (inputs=tau2, gold=tau2v2: 2 unlabelled rows are executed and counted
in coverage, excluded only from binary metrics), hold_tau2h, hold_holdout2.
Output: outputs/guardian_local_a100/<backend>/<model_dir>/runs/<set>/<variant>_rep<k>.jsonl
"""
import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from guardian_truth.file_lock import process_lock
from guardian_truth.integrated import Transport
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import ARMS, run_v5, decide as decide_v5
from guardian_truth.v6fix.pipeline import Layers, decide

from experiments.research_records import (
    failed_record, expected_manifest, load_records, freeze_phase, technical_gaps)
from experiments.guardian_semantic.variants import Hook
from experiments.guardian_addons.variants2 import Hook2

from .providers import register_local_providers

ROOT = Path(__file__).resolve().parents[2]
OUTROOT = ROOT / 'outputs/guardian_local_a100'
DATA_ROOT = Path(os.environ.get('GUARDIAN_DATA_ROOT', '/workspace/guardian/data_root_403d811e'))

LB = {'lb_long': 'lockbox', 'lb2_long': 'lockbox2', 'lb3_long': 'lockbox3'}
REAL_SETS = ('valid46', 'lb_long', 'lb2_long', 'lb3_long', 'ext_tau2', 'hold_tau2h', 'hold_holdout2')

VARIANTS = {
    'AM': dict(pre=None),
    'B': dict(pre='blind2'),
    'B2': dict(pre='blind2', pre_max_tokens=3400),
    'Bopen': dict(pre='open'),
    'T': dict(pre='blind2_typed'),
    'E': dict(pre='blind2_typed_eval'),
}

SEM = ROOT / 'outputs/guardian_semantic/data'
ADD = ROOT / 'outputs/guardian_addons/data'
F120 = ROOT / 'outputs/guardian_v6_fix/frozen120'
HOLDOUT2 = ROOT / 'outputs/guardian_v6/holdout2'


def data_dir(name):
    if name == 'contrast':
        return ADD
    if name.startswith('f120') or name == 'holdout2':
        return F120 if name.startswith('f120') else HOLDOUT2
    return SEM


def rows(name):
    if name == 'valid46':
        import pandas as pd
        return [dict(id=r.id, prompt=r.prompt, response=r.response)
                for r in pd.read_parquet(DATA_ROOT / 'valid.parquet').itertuples()]
    if name in LB:
        p = DATA_ROOT / 'outputs/verification_v2' / LB[name] / 'long/inputs.jsonl'
        return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
    if name == 'ext_tau2':
        p = DATA_ROOT / 'outputs/verification_v4/external/tau2/inputs.jsonl'
        return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
    if name == 'hold_tau2h':
        p = DATA_ROOT / 'outputs/universal_repair/holdout/tau2h/inputs.jsonl'
        return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
    if name == 'hold_holdout2':
        p = DATA_ROOT / 'outputs/guardian_v6/holdout2/inputs.jsonl'
        return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
    if name.startswith('f120'):
        split = name.split(':', 1)[1] if ':' in name else 'dev'
        gold = json.loads((F120 / 'GOLD_frozen.json').read_text(encoding='utf-8'))
        out = [json.loads(x) for x in (F120 / 'inputs.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
        return [r for r in out if gold[r['id']]['split'] == split]
    return [json.loads(x) for x in (data_dir(name) / f'{name}_inputs.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]


def model_dir(model_id):
    return model_id.replace('/', '_')


def client_for(provider, model_id, cache_dir, *, max_calls=50000, timeout=600, retry_failed=0):
    register_local_providers()
    t = Transport(provider, model_id, cache_dir, max_calls=max_calls, timeout=timeout, retry_failed=retry_failed)
    return ReadThrough(provider, model_id, [], live=t)


def compact(f):
    return dict(layer=f['layer'], kind=f['kind'], target_id=f['target_id'], status=f['status'], fact=f['fact'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', required=True)
    ap.add_argument('--variant', required=True, choices=sorted(VARIANTS))
    ap.add_argument('--backend', required=True, choices=('vllm', 'llamacpp'))
    ap.add_argument('--model-id', required=True,
                    help='served model name == cache identity, e.g. ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0')
    ap.add_argument('--rep', type=int, default=1)
    ap.add_argument('--ids')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--max-request-bytes', type=int, default=60000)
    ap.add_argument('--max-calls', type=int, default=50000, help='safety tripwire on the live transport (local calls are free but finite)')
    ap.add_argument('--layer-budget-bytes', type=int, default=20000)
    ap.add_argument('--retry-failed', type=int, default=0)
    ap.add_argument('--review-max-tokens', type=int, default=None,
                    help='override the main review-call max_tokens (default 1700; reason-capable models: budget 8192)')
    ap.add_argument('--pre-max-tokens', type=int, default=None,
                    help='override the blind pre-pass max_tokens (default: B2 3400, others 1700)')
    ap.add_argument('--frules-max-tokens', type=int, default=None,
                    help='override the F-extraction max_tokens (default 700; reason-capable models need more)')
    a = ap.parse_args()
    provider = f'local-{a.backend}'
    pre = VARIANTS[a.variant]['pre']
    pre_max_tokens = VARIANTS[a.variant].get('pre_max_tokens', 1700)
    if a.pre_max_tokens is not None:
        pre_max_tokens = a.pre_max_tokens
    review_max_tokens = a.review_max_tokens if a.review_max_tokens is not None else 1700
    frules_max_tokens = a.frules_max_tokens if a.frules_max_tokens is not None else 700
    base = OUTROOT / a.backend / model_dir(a.model_id)
    review_cache = base / 'cache' / 'review'
    frules_cache = base / 'cache' / 'frules'
    client = client_for(provider, a.model_id, review_cache, max_calls=a.max_calls, retry_failed=a.retry_failed)
    layers = Layers(client_for(provider, a.model_id, frules_cache, max_calls=a.max_calls),
                    a.model_id, budget=a.layer_budget_bytes, attempts=(0, 1),
                    frules_max_tokens=frules_max_tokens)
    path = base / 'runs' / a.set / f'{a.variant}_rep{a.rep}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = [r for r in rows(a.set) if not a.ids or r['id'] in a.ids.split(',')]
    if a.ids and (len(a.ids.split(',')) != len(set(a.ids.split(','))) or set(a.ids.split(',')) != {r['id'] for r in selected}):
        raise ValueError('UNKNOWN_OR_DUPLICATE_REQUESTED_IDS')
    with process_lock(path.with_suffix('.run.lock')):
        freeze_phase(path, ROOT, dict(variant=a.variant, rep=a.rep, set=a.set, backend=a.backend,
                                      provider=provider, model_id=a.model_id, pre=pre,
                                      pre_max_tokens=pre_max_tokens,
                                      review_max_tokens=review_max_tokens,
                                      frules_max_tokens=frules_max_tokens,
                                      max_request_bytes=a.max_request_bytes, blind_budget_bytes=20000,
                                      layer_budget_bytes=a.layer_budget_bytes, workers=a.workers,
                                      flags=sorted(ARMS['R_fix'])),
                     [{k: r[k] for k in ('id', 'prompt', 'response')} for r in selected])
        expected = expected_manifest(path, [r['id'] for r in selected])
        have, _ = load_records(path, expected, allow_missing=True)
        todo = [r for r in selected if r['id'] not in have or failed_record(have[r['id']])]
        lock = threading.Lock()

        def one(row):
            hook = Hook2(client, pre, a.model_id, original_row=row, max_request_bytes=a.max_request_bytes,
                         max_tokens=pre_max_tokens)
            out = dict(id=row['id'], set=a.set, variant=a.variant, rep=a.rep, model=a.model_id,
                       backend=a.backend, provider=provider, pre=pre)
            try:
                rec = run_v5(row, hook, flags=ARMS['R_fix'], provider=provider, model=a.model_id, attempt=a.rep - 1,
                             review_max_tokens=a.review_max_tokens)
                d_rfix, acc_rfix = decide_v5(rec)
                lay = layers.findings(row)
                d = decide(rec, lay['findings'])
                out.update(rec=rec, pre_steps=hook.log, executions=hook.executions,
                           layer_findings=[compact(f) for f in lay['findings']], layer_trace=lay,
                           binary=d['binary'], owner=d['decision_owner'], accusation=d['accusation'],
                           binary_rfix=d_rfix, owner_rfix=(acc_rfix or {}).get('origin'), accusation_rfix=acc_rfix)
            except Exception as e:
                out.update(error=f'{type(e).__name__}: {e}'[:400], pre_steps=hook.log)
            out['technical_gaps'] = technical_gaps(out)
            with lock:
                with open(path, 'a', encoding='utf-8', newline='\n') as f:
                    f.write(json.dumps(out, ensure_ascii=False, default=str) + '\n')
                    f.flush()
                    os.fsync(f.fileno())

        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(one, todo))
        print(a.set, a.variant, a.rep, 'rows', len(todo), dict(client.counts),
              'missing', len(client.missing), 'layer_counts', dict(layers.client.counts), flush=True)


if __name__ == '__main__':
    main()

