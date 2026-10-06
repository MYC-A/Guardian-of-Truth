"""Runner: python -m experiments.guardian_semantic.run --set dev --variant C --rep 1 [--ids a,b] [--live] [--workers 2]
Record per row -> outputs/guardian_semantic/runs/<set>/<variant>_rep<k>.jsonl (append; rows with a technical failure are
re-run on resume, never silently). Offline (default): caches only, misses are NOT_EXECUTED. --live: misses go to Mistral
through the study budget (budget.sender: reservation per try, caps 250 requests / 2M tokens / $20, no hidden retries)."""
import argparse, json, os, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from guardian_truth.integrated import Transport
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import ARMS, run_v5
from guardian_truth.v6fix.pipeline import Layers, decide

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
    if r.get('error'):
        return True
    steps = (r.get('rec') or {}).get('A', {}).get('steps') or []
    pre = r.get('pre_steps') or []
    bad = lambda s: s.get('raw_content') is None and str((s.get('transport') or {}).get('status')) not in ('200',)
    return any(bad(s) for s in pre) or any(s.get('tag') == 'review' and bad(s) for s in steps)


def compact(f):
    return dict(layer=f['layer'], kind=f['kind'], target_id=f['target_id'], status=f['status'], fact=f['fact'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', required=True); ap.add_argument('--variant', required=True, choices=sorted(VARIANTS))
    ap.add_argument('--rep', type=int, default=1); ap.add_argument('--ids'); ap.add_argument('--live', action='store_true')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--retry-failed', type=int, default=0, help='explicit, logged re-send of a key whose earlier try failed (e.g. 429 give-up)')
    a = ap.parse_args()
    v = VARIANTS[a.variant]
    client = client_for(v['model'], a.live, a.retry_failed)
    layers = Layers(ReadThrough('mistral', SMALL, [LAYER_CACHE], live=None), SMALL, budget=20000, attempts=(0, 1))
    path = OUT / 'runs' / a.set / f'{a.variant}_rep{a.rep}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    have = {}
    if path.exists():
        for x in path.read_text(encoding='utf-8').splitlines():
            r = json.loads(x); have[r['id']] = r
    todo = [r for r in rows(a.set) if (not a.ids or r['id'] in a.ids.split(',')) and (r['id'] not in have or failed_rec(have[r['id']]))]
    lock = threading.Lock()

    def one(row):
        hook = Hook(client, v['pre'], v['model'])
        out = dict(id=row['id'], set=a.set, variant=a.variant, rep=a.rep, model=v['model'], pre=v['pre'])
        try:
            rec = run_v5(row, hook, flags=ARMS['R_fix'], model=v['model'], attempt=a.rep - 1)
            lay = layers.findings(row)
            d = decide(rec, lay['findings'])
            out.update(rec=rec, pre_steps=hook.log, executions=hook.executions, layer_findings=[compact(f) for f in lay['findings']],
                       binary=d['binary'], owner=d['decision_owner'], accusation=d['accusation'])
        except Exception as e:
            out.update(error=f'{type(e).__name__}: {e}'[:400], pre_steps=hook.log)
        with lock:
            with open(path, 'a', encoding='utf-8', newline='\n') as f:
                f.write(json.dumps(out, ensure_ascii=False, default=str) + '\n'); f.flush(); os.fsync(f.fileno())
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, todo))
    print(a.set, a.variant, a.rep, 'rows', len(todo), dict(client.counts), 'missing', len(client.missing), 'budget', budget.totals(), flush=True)


if __name__ == '__main__':
    main()
