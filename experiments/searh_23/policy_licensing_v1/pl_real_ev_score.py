"""Score the real-track evidence gate: does extractive evidence fix the
false edges created by noisy frontend events?

For each case: BASE-accepted pairs (from REAL_ev ce+det fields) vs
EVIDENCE-gated subset (ev_rows with decision RELATED). Both are matched to
gold via span overlap (same rule as pl_run_real).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/policy_licensing_v1')
from pl_common import load_suite, out_dir
from pl_run_real import match_events

by_split = {}
for split in ('calib', 'val', 'test', 'ALL'):
    rows = {'base': [0]*4, 'ev': [0]*4}  # correct, extra, direrr, missing
    n_pred = n_matched = n_gold = 0
    for case in load_suite('original'):
        if split != 'ALL' and case['split'] != split:
            continue
        p = out_dir('REAL_ev') / (case['case_id'] + '.json')
        if not p.is_file():
            continue
        d = json.loads(p.read_text(encoding='utf-8'))
        front = json.loads((out_dir('FRONTEND') / (case['case_id'] + '.json')).read_text(encoding='utf-8'))['events']
        gold_events = case['events']
        matches = match_events(front, gold_events)
        gold_edges = {(e['from_eid'], e['to_eid']) for e in case['edges']}
        gold_idx = {g['eid']: j for j, g in enumerate(gold_events)}
        n_pred += len(front)
        n_matched += len(set(matches.values()))
        n_gold += len(gold_events)

        ce = {tuple(int(x) for x in k.split('_')): v for k, v in d['ce'].items()}
        det = {tuple(int(x) for x in k.split('_')): v for k, v in d['det'].items()}
        accepted = [k for k, v in det.items() if v == 'RELATED' and ce.get(k, 0.0) >= 0.35]
        ev_ok = {(r['i'], r['j']) for r in d['ev_rows'] if r.get('decision') == 'RELATED'}

        # direction: reuse DIR answers from pl_run_real? Not persisted; use
        # role/position fallback identical to pl_run_real.
        def orient(i, j):
            a, b = front[i], front[j]
            ra, rb = a['role'], b['role']
            if rb in ('PRECONDITION_CHECK', 'STATE_OBSERVATION') and ra not in ('PRECONDITION_CHECK', 'STATE_OBSERVATION'):
                return j, i
            if ra in ('PRECONDITION_CHECK', 'STATE_OBSERVATION') and rb not in ('PRECONDITION_CHECK', 'STATE_OBSERVATION'):
                return i, j
            if a['span_start'] > b['span_start']:
                return j, i
            return i, j

        for tag, pairset in (('base', set(accepted)), ('ev', ev_ok)):
            edges = [orient(i, j) for (i, j) in pairset]
            for (u, v) in edges:
                gu, gv = matches.get(u), matches.get(v)
                if gu is None or gv is None:
                    rows[tag][1] += 1
                    continue
                eu, ev2 = gold_events[gu]['eid'], gold_events[gv]['eid']
                if (eu, ev2) in gold_edges:
                    rows[tag][0] += 1
                elif (ev2, eu) in gold_edges:
                    rows[tag][2] += 1
                else:
                    rows[tag][1] += 1
            covered = set()
            for (u, v) in edges:
                if u in matches:
                    covered.add(matches[u])
                if v in matches:
                    covered.add(matches[v])
            for (gf, gt) in gold_edges:
                gi, gj = gold_idx[gf], gold_idx[gt]
                got = any((u, v) for (u, v) in edges if matches.get(u) == gi and matches.get(v) == gj)
                got_r = any((u, v) for (u, v) in edges if matches.get(u) == gj and matches.get(v) == gi)
                if not got and not got_r:
                    rows[tag][3] += 1

    res = {}
    for tag in ('base', 'ev'):
        c, e, de, m = rows[tag]
        res[tag] = {'correct': c, 'extra': e, 'direrr': de, 'missing': m,
                    'accepted_precision': round(c / max(1, c + e + de), 4),
                    'recall': round(c / max(1, c + m), 4)}
    res['event_match_rate'] = round(n_matched / max(1, n_gold), 4)
    by_split[split] = res

print(json.dumps(by_split, indent=1))
out_dir('REAL_ev').joinpath('ev_gate_score.json').write_text(
    json.dumps(by_split, indent=1), encoding='utf-8')
