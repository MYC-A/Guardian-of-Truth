"""Replay every visible history step (prose turn or call) as a pseudo-row; report new-rule firings.
History steps are unlabeled but mostly correct agent behaviour: a high firing rate signals FP risk."""
import sys, collections, re
import pandas as pd
from guardian_truth.source_search.store import SourceStore
from guardian_truth.policy_table_v11.service import Gate
d = pd.read_parquet('valid.parquet'); g = Gate(None)
codes = collections.Counter(); examples = collections.defaultdict(list); n = 0
want = set(sys.argv[1:])
for r in d.to_dict('records'):
    s = SourceStore(r); P = r['prompt']
    starts = [m.start() for m in re.finditer(r'⟦ASSISTANT · ход \d+⟧', P)]
    for i, st in enumerate(starts):
        end = starts[i+1] if i+1 < len(starts) else len(P)
        nxt = P.find('\n⟦USER⟧', st, end)
        end = nxt if nxt != -1 else end
        resp = P[st:end]
        # drop inline results from the replayed step (keep only calls / prose)
        keep, inres = [], False
        for l in resp.split('\n'):
            t = l.lstrip()
            if t.startswith('←'): inres = True; continue
            if t.startswith('→'): inres = False
            if not inres: keep.append(l)
        resp = '\n'.join(keep)
        res = g.check({'id': f"{r['id']}@{i}", 'prompt': P[:st], 'response': resp})
        n += 1
        for v in res.get('violations', []):
            if not want or v['code'] in want:
                codes[v['code']] += 1
                if len(examples[v['code']]) < 6: examples[v['code']].append((res['id'], {k: v[k] for k in v if k not in ('code','source_ids')}))
print('replayed steps', n); print(dict(codes))
for c, ex in examples.items():
    print('==', c)
    for e in ex: print('  ', e[0][:70], str(e[1])[:300])
