"""L variant: OLD v6fix from the detached control worktree wt-v6fix-5330dcc4.

Old code import: this script inserts the OLD src directory first on sys.path
BEFORE importing guardian_truth, so every guardian_truth symbol resolves to the
pinned control version 5330dcc4 (research/guardian-v6-fix-20261008) while the
row data and the output tree live in THIS branch. The old worktree itself is
never modified. No pre-pass: L = R_fix + old v6fix layers on the same rows and
the same local model (new inference: old wire, local backend).

Deliberately self-contained: no imports from run_local/variants (those pull NEW
guardian_truth symbols that may not exist in the old tree under this sys.path).

Usage (from the branch root; do NOT set PYTHONPATH=src for this script):
  python experiments/guardian_local_a100/l_v6fix_old.py --set dev --backend vllm \
      --model-id 'ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0' [--rep 1]

Output: outputs/guardian_local_a100/<backend>/<model_dir>/runs/<set>/L_rep<k>.jsonl
"""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD_SRC = Path('/workspace/guardian/repos/wt-v6fix-5330dcc4/src')
if not (OLD_SRC / 'guardian_truth' / 'v6fix' / 'pipeline.py').exists():
    raise SystemExit(f'OLD WORKTREE MISSING: {OLD_SRC}')
sys.path.insert(0, str(OLD_SRC))          # guardian_truth -> OLD 5330dcc4 from here on

from guardian_truth.integrated import Transport            # noqa: E402 (old code)
from guardian_truth.repair.clients import ReadThrough      # noqa: E402 (old code)
from guardian_truth.repair.v5 import ARMS, run_v5, decide as decide_v5  # noqa: E402 (old code)
from guardian_truth.v6fix.pipeline import Layers, decide   # noqa: E402 (old code)

from experiments.guardian_local_a100.providers import register_local_providers  # noqa: E402

OUTROOT = ROOT / 'outputs/guardian_local_a100'
SEM = ROOT / 'outputs/guardian_semantic/data'
ADD = ROOT / 'outputs/guardian_addons/data'
F120 = ROOT / 'outputs/guardian_v6_fix/frozen120'
HOLDOUT2 = ROOT / 'outputs/guardian_v6/holdout2'


def rows(name):
    """Same set routing as run_local (duplicated to avoid transitive NEW imports)."""
    if name.startswith('f120'):
        split = name.split(':', 1)[1] if ':' in name else 'dev'
        gold = json.loads((F120 / 'GOLD_frozen.json').read_text(encoding='utf-8'))
        out = [json.loads(x) for x in (F120 / 'inputs.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
        return [r for r in out if gold[r['id']]['split'] == split]
    if name == 'holdout2':
        return [json.loads(x) for x in (HOLDOUT2 / 'inputs.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    d = ADD if name == 'contrast' else SEM
    return [json.loads(x) for x in (d / f'{name}_inputs.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]


def model_dir(model_id):
    return model_id.replace('/', '_')


def client_for(provider, model_id, cache_dir, *, max_calls=50000, timeout=600, retry_failed=0):
    register_local_providers()  # registers into the OLD transport's PROVIDERS (same contract)
    t = Transport(provider, model_id, cache_dir, max_calls=max_calls, timeout=timeout, retry_failed=retry_failed)
    return ReadThrough(provider, model_id, [], live=t)


def compact(f):
    return dict(layer=f['layer'], kind=f['kind'], target_id=f['target_id'], status=f['status'], fact=f['fact'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', required=True)
    ap.add_argument('--backend', required=True, choices=('vllm', 'llamacpp'))
    ap.add_argument('--model-id', required=True)
    ap.add_argument('--rep', type=int, default=1)
    ap.add_argument('--ids')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--max-request-bytes', type=int, default=60000)
    ap.add_argument('--max-calls', type=int, default=50000)
    ap.add_argument('--layer-budget-bytes', type=int, default=20000)
    ap.add_argument('--retry-failed', type=int, default=0)
    a = ap.parse_args()
    provider = f'local-{a.backend}'
    base = OUTROOT / a.backend / model_dir(a.model_id)
    client = client_for(provider, a.model_id, base / 'cache' / 'review_old_v6fix', max_calls=a.max_calls,
                        retry_failed=a.retry_failed)
    layers = Layers(client_for(provider, a.model_id, base / 'cache' / 'frules_old_v6fix', max_calls=a.max_calls),
                    a.model_id, budget=a.layer_budget_bytes, attempts=(0, 1))
    path = base / 'runs' / a.set / f'L_rep{a.rep}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = [r for r in rows(a.set) if not a.ids or r['id'] in a.ids.split(',')]
    if a.ids and (len(a.ids.split(',')) != len(set(a.ids.split(','))) or set(a.ids.split(',')) != {r['id'] for r in selected}):
        raise ValueError('UNKNOWN_OR_DUPLICATE_REQUESTED_IDS')
    lock = threading.Lock()
    phase = dict(variant='L', rep=a.rep, set=a.set, backend=a.backend, provider=provider,
                 model_id=a.model_id, old_src=str(OLD_SRC), old_head='5330dcc4c48967dadf6792e6951ac92b06ee4d47',
                 pre=None, max_request_bytes=a.max_request_bytes, layer_budget_bytes=a.layer_budget_bytes,
                 workers=a.workers, flags=sorted(ARMS['R_fix']))
    manifest = path.with_suffix('.phase.json')
    if path.exists():
        prior = json.loads(manifest.read_text(encoding='utf-8'))
        if prior != phase:
            raise ValueError('PHASE_MANIFEST_MISMATCH: refusing to append to a run with a different phase')
    else:
        manifest.write_text(json.dumps(dict(phase, inputs=[{k: r[k] for k in ('id', 'prompt', 'response')} for r in selected],
                                           expected_ids=[r['id'] for r in selected]), ensure_ascii=False, indent=1),
                            encoding='utf-8', newline='\n')

    def one(row):
        out = dict(id=row['id'], set=a.set, variant='L', rep=a.rep, model=a.model_id,
                   backend=a.backend, provider=provider, old_head='5330dcc4')
        try:
            rec = run_v5(row, client, flags=ARMS['R_fix'], provider=provider, model=a.model_id, attempt=a.rep - 1)
            d_rfix, acc_rfix = decide_v5(rec)
            lay = layers.findings(row)
            d = decide(rec, lay['findings'])
            out.update(rec=rec, layer_findings=[compact(f) for f in lay['findings']], layer_trace=lay,
                       binary=d['binary'], owner=d['decision_owner'], accusation=d['accusation'],
                       binary_rfix=d_rfix, owner_rfix=(acc_rfix or {}).get('origin'), accusation_rfix=acc_rfix)
        except Exception as e:
            out.update(error=f'{type(e).__name__}: {e}'[:400])
        with lock:
            with open(path, 'a', encoding='utf-8', newline='\n') as f:
                f.write(json.dumps(out, ensure_ascii=False, default=str) + '\n')
                f.flush()
                os.fsync(f.fileno())

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, selected))
    print(a.set, 'L', a.rep, 'rows', len(selected), dict(client.counts), 'layer_counts', dict(layers.client.counts), flush=True)


if __name__ == '__main__':
    main()
