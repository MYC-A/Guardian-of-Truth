import json, sys
from pathlib import Path
from guardian_truth.repair.v5 import packet_for
from experiments.guardian_local_a100.run_local import rows
from experiments.guardian_binding.idcheck import check
from experiments.guardian_complementarity.combine import runs, QW, score
from experiments.guardian_local_a100.score_local import gold_for
POOLS = dict(dev=['valid46', 'ext_tau2', 'hold_tau2h', 'hold_holdout2'], test=['lb2_long', 'lb3_long', 'lb_long'])
verbose = '-v' in sys.argv
for pool, sets in POOLS.items():
    G, Q, A = {}, {}, {}
    for s in sets:
        gold = {i: x['label'] for i, x in gold_for(s).items() if x.get('label') in (0, 1)}
        q = runs(QW / s / 'B2_rep1.jsonl', 'B2') or {}
        for r in rows(s):
            i = r['id']
            if i not in gold or i not in q or q[i]['b'] is None:
                continue
            f = check(packet_for(r, 400000) or {})
            k = f'{s}/{i}'; G[k] = gold[i]; Q[k] = q[i]['b']; A[k] = f
            if f and (verbose or not Q[k]):
                print(' ', pool, k, 'gold', gold[i], 'QB2', Q[k], [(x['rule'], x['tool'], x['value'], x.get('attr'), x.get('obj_value'), x.get('user_value')) for x in f][:3])
    for rule in ('A', 'B', 'C', 'ABC'):
        c = {k: int(Q[k] or any(x['rule'] in rule for x in A[k])) for k in G}
        print(pool, 'n', len(G), 'QB2', score(G, Q), f'QB2|{rule}', score(G, c))
