"""Offline proposal coverage; historical heuristic OR is explicitly unsafe."""
import argparse
from guardian_truth.repair.v5 import packet_for
from experiments.guardian_local_a100.run_local import rows
from experiments.guardian_binding.idcheck import check
from experiments.guardian_complementarity.combine import runs, QW, score
from experiments.guardian_local_a100.score_local import gold_for
POOLS = dict(dev=['valid46', 'ext_tau2', 'hold_tau2h', 'hold_holdout2'], test=['lb2_long', 'lb3_long', 'lb_long'])


def project(qwen_binary, proposals, *, historical_unsafe_or=False, rules='ABC'):
    if qwen_binary is None:
        return None
    if historical_unsafe_or:
        return int(qwen_binary or any(x['rule'] in rules for x in proposals))
    return qwen_binary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-v', '--verbose', action='store_true')
    ap.add_argument('--historical-unsafe-or', action='store_true',
                    help='reproduce exploratory ABC OR; not a policy proof')
    a = ap.parse_args()
    for pool, sets in POOLS.items():
        gold, qwen, proposals, gaps = {}, {}, {}, {}
        for s in sets:
            labels = {i: x['label'] for i, x in gold_for(s).items() if x.get('label') in (0, 1)}
            saved = runs(QW / s / 'B2_rep1.jsonl', 'B2') or {}
            inputs, seen = list(rows(s)), set()
            for r in inputs:
                i = r['id']
                if i in seen:
                    raise ValueError('DUPLICATE_INPUT_ID: ' + i)
                seen.add(i)
                if i not in labels:
                    continue
                k = f'{s}/{i}'
                gold[k], qwen[k] = labels[i], (saved.get(i) or {}).get('b')
                packet = packet_for(r, 400000)
                proposals[k] = check(packet) if packet is not None else []
                if packet is None:
                    gaps[k] = 'PACKET_UNAVAILABLE'
                if qwen[k] is None:
                    gaps[k] = 'BASE_MISSING_OR_TECHNICAL'
                if a.verbose and proposals[k]:
                    print(pool, k, 'gold', labels[i], 'QB2', qwen[k], proposals[k])
            if set(labels) - seen or set(saved) - seen:
                raise ValueError('SOURCE_OR_RESULT_INVENTORY_MISMATCH: ' + s)
        print(pool, 'n_expected', len(gold), 'QB2', score(gold, qwen),
              'hypothesis_rows', sum(bool(v) for v in proposals.values()), 'gaps', gaps)
        selected = {k: project(qwen[k], proposals[k]) for k in gold}
        assert selected == qwen
        print(pool, 'QB2 + shadow proposals', score(gold, selected))
        if a.historical_unsafe_or:
            for rule in ('A', 'B', 'C', 'ABC'):
                pred = {k: project(qwen[k], proposals[k], historical_unsafe_or=True, rules=rule) for k in gold}
                print(pool, 'HISTORICAL_UNSAFE_OR', rule, score(gold, pred))


if __name__ == '__main__':
    main()
