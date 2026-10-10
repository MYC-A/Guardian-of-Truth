"""Build probe requests for all triggered rows (decision pools + valid46, dedup). No gold is written.

    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.escalation_probe_20261010.build --out requests.json
"""
import argparse
import hashlib
import json

from experiments.contract_lint_20261010.evaluate import DECISION
from experiments.escalation_probe_20261010.probe import request_messages, trigger
from experiments.guardian_local_a100.run_local import rows


def triggered():
    seen, out = set(), []
    for pool in DECISION + ['valid46']:
        for r in rows(pool):
            key = hashlib.sha256((r['prompt'] + '\0' + (r['response'] or '')).encode()).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            t = trigger(r['prompt'], r['response'] or '')
            if t:
                out.append(dict(key=key, pool=pool, id=r['id'], trigger=t, prompt=r['prompt'], response=r['response'] or ''))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    reqs = [dict(key=x['key'], messages=request_messages(x['prompt'], x['response'])) for x in triggered()]
    json.dump(reqs, open(a.out, 'w'), ensure_ascii=False)
    print(len(reqs), 'requests; max chars', max(len(r['messages'][1]['content']) for r in reqs))


if __name__ == '__main__':
    main()
