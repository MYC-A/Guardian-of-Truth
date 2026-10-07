"""Offline first-circle QA; counts each row once, reports full and common coverage.

This is a diagnostic ranking, NOT a retrospective claim of preregistration.
The earlier PLAN did not specify which architecture's valid46 F1 was primary.
A and B2 rankings are therefore both reported, without silently selecting one.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .run_local import OUTROOT

SETS = {'dev': 10, 'contrast': 14, 'valid46': 46}
SCORES = {
    'ministral': ['vllm/ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0/score_short.json',
                  'vllm/ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0/score_valid46.json'],
    'qwen': ['llamacpp/qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/score_first_circle.json'],
    'gptoss': ['vllm/gpt-oss-20b@6cee5e81ee83:mxfp4:vllm-0.31.0/score_first_circle.json'],
    'compass_pointwise': ['llamacpp/compassjudger-2-32b@7f6877f97adf:Q8_0:llamacpp-b11459/score_first_circle.json'],
    'distill': ['llamacpp/qwen3.8-27b-opus-distill-v2@64d56b13ea8d:Q8_0:llamacpp-b11459/score_first_circle_qa.json'],
}


def combined(per_set):
    fields = ('tp', 'fp', 'fn', 'tn', 'n_verdict', 'n_fallback', 'n_no_solution', 'rows', 'missing')
    result = {k: sum((m or {}).get(k, 0) or 0 for m in per_set.values()) for k in fields}
    result['valid_solution_coverage'] = ((result['n_verdict'] + result['n_fallback']) / 70)
    result['all_sets_present'] = all(per_set.get(s) and per_set[s].get('rows') == n for s, n in SETS.items())
    return result


def confusion(records):
    result = {k: 0 for k in ('tp', 'fp', 'fn', 'tn')}
    for r in records:
        if r.get('outcome') in result:
            result[r['outcome']] += 1
    tp, fp, fn = (result[k] for k in ('tp', 'fp', 'fn'))
    return dict(result, rows=len(records), f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)


def build(root=OUTROOT):
    table, per_rows, fingerprints = {}, {}, {}
    for model, paths in SCORES.items():
        summary, selected_rows = {}, {}
        for name in paths:
            path = root / name
            if not path.exists():
                continue
            fingerprints[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            data = json.loads(path.read_text(encoding='utf-8'))
            for s, arms in data.get('summary', {}).items():
                if s in SETS:
                    summary.setdefault(s, {}).update(arms)
            for r in data.get('rows', []):
                if r.get('set') in SETS and r.get('rep') == 1 and r.get('variant') in ('A', 'M', 'B2'):
                    key = (r['set'], r['variant'], r['id'])
                    if key in selected_rows and selected_rows[key] != r:
                        raise ValueError('CONFLICTING_SCORE_ROWS')
                    selected_rows[key] = r
        arms = {}
        for arm in ('A', 'M', 'B2'):
            p = {s: summary.get(s, {}).get(arm + '_rep1') for s in SETS}
            arms[arm] = dict(per_set=p, combined=combined(p))
        a = arms['A']
        eligible = (a['combined']['all_sets_present'] and a['combined']['valid_solution_coverage'] >= .8
                    and all((a['per_set'][s].get('f1') or 0) >= .6 for s in ('dev', 'contrast')))
        table[model] = dict(status='EXECUTED' if all(x['combined']['all_sets_present'] for x in arms.values()) else 'PARTIAL_OR_MISSING',
                            diagnostic_gates_passed=bool(eligible), arms=arms)
        per_rows[model] = selected_rows
    rankings = {}
    for arm in ('A', 'B2'):
        candidates = [m for m, r in table.items() if r['status'] == 'EXECUTED' and r['diagnostic_gates_passed']]
        rankings[arm] = sorted(candidates, key=lambda m: (
            table[m]['arms'][arm]['per_set']['valid46'].get('f1') or 0,
            table[m]['arms'][arm]['per_set']['valid46'].get('precision') or 0), reverse=True)
    common = {}
    models = [m for m, t in table.items() if t['status'] == 'EXECUTED']
    for arm in ('A', 'B2'):
        keys = [{k for k, r in per_rows[m].items() if k[0] == 'valid46' and k[1] == arm and r.get('outcome') in ('tp', 'fp', 'fn', 'tn')}
                for m in models]
        ids = set.intersection(*keys) if keys else set()
        common[arm] = dict(ids=sorted(k[2] for k in ids), models={m: confusion([per_rows[m][k] for k in sorted(ids)]) for m in models})
    return dict(table=table, diagnostic_rankings=rankings, common_valid46=common, score_sha256=fingerprints,
                note='Each combined rows count is summed once. Denominator remains 70 when any set is missing. '
                     'extra_pass is an overlapping diagnostic subset of verdict, not added to coverage. '
                     'A/B2 rankings are diagnostic: the old PLAN did not disambiguate primary architecture. '
                     'Lynx is a separate factual-grounding lane. No new inference or holdout claim.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    a = ap.parse_args()
    value = build()
    with Path(a.output).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    print(json.dumps(value['diagnostic_rankings']), flush=True)


if __name__ == '__main__':
    main()
