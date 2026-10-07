"""Runner: python -m experiments.guardian_semantic.run --set dev --variant C --rep 1 [--ids a,b] [--live] [--workers 2]
Record per row -> outputs/guardian_contract_fix/guardian_semantic/<set>/<variant>_rep<k>.jsonl (append; rows with a technical failure are
re-run on resume, never silently). Offline (default): caches only, misses are NOT_EXECUTED. --live: misses go to Mistral
through the study budget (budget.sender: reservation per try, caps 250 requests / 2M tokens / $20, no hidden retries)."""
import argparse, json, os, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from guardian_truth.file_lock import process_lock
from guardian_truth.integrated import Transport
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import ARMS, run_v5
from guardian_truth.v6fix.pipeline import Layers, decide
from experiments.research_records import failed_record, expected_manifest, load_records, freeze_phase, technical_gaps

from . import budget
from .variants import VARIANTS, SMALL, Hook

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/guardian_semantic'
REUSE = {SMALL: [ROOT / 'outputs/guardian_semantic/cache/replay_frozen120']}
LAYER_CACHE = ROOT / 'outputs/guardian_v6_fix/cache/frules'


def rows(name):
    return [json.loads(x) for x in (OUT / 'data' / f'{name}_inputs.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]


def client_for(model, live, retry_failed=0):
    t = Transport('mistral', model, OUT / 'cache' / model, max_calls=250, retry_failed=retry_failed, sender=budget.sender) if live else None
    return ReadThrough('mistral', model, REUSE.get(model, []) + [OUT / 'cache' / model], live=t)


def failed_rec(r):
    return failed_record(r)


def compact(f):
    return dict(layer=f['layer'], kind=f['kind'], target_id=f['target_id'], status=f['status'], fact=f['fact'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', required=True); ap.add_argument('--variant', required=True, choices=sorted(VARIANTS))
    ap.add_argument('--rep', type=int, default=1); ap.add_argument('--ids'); ap.add_argument('--live', action='store_true')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--max-request-bytes', type=int, default=60000)
    ap.add_argument('--runs-dir', default='outputs/guardian_contract_fix/guardian_semantic', help='new phase output; historical directories refused')
    ap.add_argument('--retry-failed', type=int, default=0, help='explicit, logged re-send of a key whose earlier try failed (e.g. 429 give-up)')
    a = ap.parse_args()
    v = VARIANTS[a.variant]
    client = client_for(v['model'], a.live, a.retry_failed)
    layers = Layers(ReadThrough('mistral', SMALL, [LAYER_CACHE], live=None), SMALL, budget=20000, attempts=(0, 1))
    run_root = Path(a.runs_dir).resolve()
    historical = [(ROOT / 'outputs' / x / 'runs').resolve() for x in ('guardian_semantic', 'guardian_addons')]
    if any(run_root == h or h in run_root.parents for h in historical):
        raise ValueError('HISTORICAL_OUTPUT_DIRECTORY_REFUSED')
    path = run_root / a.set / f'{a.variant}_rep{a.rep}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = [r for r in rows(a.set) if not a.ids or r['id'] in a.ids.split(',')]
    if a.ids and (len(a.ids.split(',')) != len(set(a.ids.split(','))) or set(a.ids.split(',')) != {r['id'] for r in selected}):
        raise ValueError('UNKNOWN_OR_DUPLICATE_REQUESTED_IDS')
    with process_lock(path.with_suffix('.run.lock')):
        freeze_phase(path, ROOT, dict(variant=a.variant, rep=a.rep, set=a.set, model=v['model'], pre=v['pre'],
                                     max_request_bytes=a.max_request_bytes, blind_budget_bytes=20000, layer_budget_bytes=20000,
                                     flags=sorted(ARMS['R_fix'])), [{k:r[k] for k in ('id','prompt','response')} for r in selected])
        expected = expected_manifest(path, [r['id'] for r in selected])
        have, _ = load_records(path, expected, allow_missing=True)
        todo = [r for r in selected if r['id'] not in have or failed_record(have[r['id']])]
        lock = threading.Lock()

        def one(row):
            hook = Hook(client, v['pre'], v['model'], original_row=row, max_request_bytes=a.max_request_bytes)
            out = dict(id=row['id'], set=a.set, variant=a.variant, rep=a.rep, model=v['model'], pre=v['pre'])
            try:
                rec = run_v5(row, hook, flags=ARMS['R_fix'], model=v['model'], attempt=a.rep - 1)
                lay = layers.findings(row)
                d = decide(rec, lay['findings'])
                out.update(rec=rec, pre_steps=hook.log, executions=hook.executions, layer_findings=[compact(f) for f in lay['findings']],
                           binary=d['binary'], owner=d['decision_owner'], accusation=d['accusation'], layer_trace=lay)
            except Exception as e:
                out.update(error=f'{type(e).__name__}: {e}'[:400], pre_steps=hook.log)
            out['technical_gaps'] = technical_gaps(out)
            with lock:
                with open(path, 'a', encoding='utf-8', newline='\n') as f:
                    f.write(json.dumps(out, ensure_ascii=False, default=str) + '\n'); f.flush(); os.fsync(f.fileno())
        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(one, todo))
        print(a.set, a.variant, a.rep, 'rows', len(todo), dict(client.counts), 'missing', len(client.missing), 'budget', budget.totals(), flush=True)


if __name__ == '__main__':
    main()
