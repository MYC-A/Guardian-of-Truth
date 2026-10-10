"""Write unique (policy, catalog) pairs of the given pools to policies.jsonl (no labels read)."""
import argparse
import json

from experiments.guardian_local_a100.run_local import rows
from experiments.near_miss_20261010.policy import key, split
from experiments.near_miss_20261010.evaluate import DECISION, REPORT_ONLY


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    seen = {}
    for pool in DECISION + REPORT_ONLY:
        for r in rows(pool):
            s = split(r['prompt'])
            if s:
                seen.setdefault(key(*s), dict(key=key(*s), policy=s[0], catalog=s[1]))
    with open(a.out, 'x', encoding='utf-8') as f:
        for v in seen.values():
            f.write(json.dumps(v, ensure_ascii=False) + '\n')
    print(len(seen))


if __name__ == '__main__':
    main()
