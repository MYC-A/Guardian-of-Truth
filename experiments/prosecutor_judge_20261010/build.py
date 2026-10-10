"""Rows for the prosecutor/judge run (no gold written): decision-pool rows with stored B2 Q8 rep1 == 0 (1 pass)
and all valid46 rows (3 passes), deduplicated.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.prosecutor_judge_20261010.build --out rows.json
"""
import argparse
import hashlib
import json

from experiments.contract_lint_20261010.evaluate import DECISION
from experiments.guardian_complementarity.combine import QW, runs
from experiments.guardian_local_a100.run_local import rows


def selected():
    seen, out = set(), []
    for pool in ['valid46'] + DECISION:
        b2 = runs(QW / pool / 'B2_rep1.jsonl', 'B2') or {} if pool != 'valid46' else {}
        for r in rows(pool):
            key = hashlib.sha256((r['prompt'] + '\0' + (r['response'] or '')).encode()).hexdigest()
            if key in seen:
                continue
            if pool != 'valid46' and (b2.get(r['id']) or {}).get('b') != 0:
                continue
            seen.add(key)
            out.append(dict(key=key, pool=pool, id=r['id'], prompt=r['prompt'], turn=r['response'] or '',
                            passes=3 if pool == 'valid46' else 1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    s = selected()
    json.dump([{k: x[k] for k in ('key', 'prompt', 'turn', 'passes')} for x in s], open(a.out, 'w'), ensure_ascii=False)
    print(len(s), 'rows;', sum(x['passes'] for x in s), 'row-passes')


if __name__ == '__main__':
    main()
