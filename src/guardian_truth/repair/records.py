"""Validated run records (stability contract). Scoring never silently takes the last line per id:
duplicates are accepted only as retry chains whose earlier lines failed (error / transport failure); two successful
lines for one id are a DUPLICATE_CONFLICT. The id set must equal the expected set exactly."""
from __future__ import annotations

import json
from pathlib import Path


def failed(rec):
    if 'error' in rec:
        return True
    steps = list((rec.get('A') or {}).get('steps') or [])
    for k in ('DF4', 'Ems', 'AT', 'CTRL', 'CB', 'DF', 'E', 'B', 'C', 'Av'):
        xs = rec.get(k) if isinstance(rec.get(k), list) else [rec.get(k)]
        for x in xs:
            if x:
                steps.append(x)
                if x.get('verify'):
                    steps.append(x['verify'])
    for k, c in (rec.get('components') or {}).items():
        steps.append(c)
    for it in rec.get('pool') or []:
        if it.get('verify'):
            steps.append(it['verify'])
    return any(s.get('admission') == 'TRANSPORT_FAILURE' for s in steps if isinstance(s, dict))


def load(path, expected_ids):
    lines = [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines() if s.strip()]
    by = {}
    for r in lines:
        by.setdefault(r['id'], []).append(r)
    report = dict(path=str(path), lines=len(lines), ids=len(by), retry_chains=0, conflicts=[])
    out = {}
    for i, rs in by.items():
        ok = [r for r in rs if not failed(r)]
        if len(rs) > 1:
            report['retry_chains'] += 1
        if len(ok) > 1:
            same = all(json.dumps(r, sort_keys=True) == json.dumps(ok[0], sort_keys=True) for r in ok[1:])
            if not same:
                report['conflicts'].append(i)
        if any(failed(r) for r in rs[rs.index(ok[0]) + 1:] if ok) if ok else False:
            report['conflicts'].append(i)          # a failure AFTER a success is not a retry chain
        out[i] = ok[-1] if ok else rs[-1]
    missing, extra = sorted(set(expected_ids) - set(out)), sorted(set(out) - set(expected_ids))
    report.update(missing=missing, extra=extra, failed_final=sorted(i for i, r in out.items() if failed(r)))
    if report['conflicts'] or missing or extra:
        raise AssertionError(f"INVALID_RECORDS {report}")
    return out, report
