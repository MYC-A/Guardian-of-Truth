"""Score a complete frozen paired source-completion diagnostic without editing gold."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from experiments.guardian_complementarity.combine import score
from scripts.qwen_source_visibility_audit import REF, BASE


def analyze(records, inputs, gold, baseline):
    expected = {r['id']: r for r in inputs}
    if len(expected) != len(inputs) or set(expected) != set(gold) or set(expected) != set(baseline):
        raise ValueError('INPUT_GOLD_BASELINE_COVERAGE_MISMATCH')
    indexed = {}
    for row in records:
        key = (row['id'], row['mode'])
        if key in indexed or key[0] not in expected or key[1] not in ('control', 'completion'):
            raise ValueError('DUPLICATE_OR_FOREIGN_RECORD')
        if row['request_sha256'] != expected[key[0]][key[1] + '_sha256']:
            raise ValueError('RECORD_REQUEST_MISMATCH')
        value = row['result'].get('binary')
        if value is not None and (type(value) is not int or value not in (0, 1)):
            raise ValueError('INVALID_BINARY')
        indexed[key] = row
    complete = set(indexed) == {(i, m) for i in expected for m in ('control', 'completion')}
    predictions, overlays, modes = {}, {}, {}
    for mode in ('control', 'completion'):
        selected = {i: indexed.get((i, mode)) for i in expected}
        predictions[mode] = {i: r['result']['binary'] if r else None for i, r in selected.items()}
        overlays[mode] = {i: 1 if predictions[mode][i] == 1 else baseline[i] for i in expected}
        modes[mode] = dict(primary=score(gold, predictions[mode]), frozen_full_B2_OR_primary=score(gold, overlays[mode]),
            unknown_ids=sorted(i for i, r in selected.items() if r and r['result'].get('decision') == 'UNKNOWN'),
            technical_or_rejected_ids=sorted(i for i, r in selected.items() if not r or
                r['result'].get('status') != 'ADMITTED'), missing_ids=sorted(i for i, r in selected.items() if not r),
            causes={i: r['result'].get('interpretation', {}).get('admitted') for i, r in selected.items() if r})
    noop_conflicts = []
    for i, source in expected.items():
        if source['wire_identical'] and (i, 'control') in indexed and (i, 'completion') in indexed:
            c, t = indexed[(i, 'control')], indexed[(i, 'completion')]
            if c['result'] != t['result'] or (c.get('reply') or {}).get('content') != (t.get('reply') or {}).get('content'):
                noop_conflicts.append(i)
    if noop_conflicts:
        raise ValueError('IDENTICAL_WIRE_CONFLICT:' + ','.join(noop_conflicts))
    changes = [dict(id=i, label=gold[i], control=predictions['control'][i], completion=predictions['completion'][i])
               for i in expected if predictions['control'][i] != predictions['completion'][i]]
    return dict(ref=REF, expected_rows=len(gold), observed_records=len(indexed), execution_complete=complete,
                source_cause_review='PENDING', interpretation='Fresh primary-review comparison, not a full new B2 pipeline',
                frozen_full_B2=score(gold, baseline), modes=modes, paired_changes=changes,
                paired_true_positive_recoveries=[r['id'] for r in changes if r['label'] == 1 and r['completion'] == 1 and r['control'] != 1],
                paired_new_false_positives=[r['id'] for r in changes if r['label'] == 0 and r['completion'] == 1 and r['control'] != 1])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--records', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--inputs', type=Path, default=ROOT / 'docs/qwen_binding_audit_20261008/source_completion_phase3_inputs/runtime_requests.jsonl')
    a = ap.parse_args()
    def blob(path):
        return subprocess.check_output(['git', 'show', REF + ':' + path], cwd=ROOT)
    import pandas as pd
    gold = {r.id: int(r.label) for r in pd.read_parquet(io.BytesIO(blob('valid.parquet'))).itertuples()}
    baseline = {r['id']: r['binary'] for r in map(json.loads, blob(BASE + 'valid46/B2_rep1.jsonl').splitlines())}
    records = [json.loads(l) for l in a.records.read_text(encoding='utf-8').splitlines() if l.strip()]
    inputs = [json.loads(l) for l in a.inputs.read_text(encoding='utf-8').splitlines() if l.strip()]
    result = analyze(records, inputs, gold, baseline)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print('complete', result['execution_complete'], 'paired changes', result['paired_changes'])
    for mode, value in result['modes'].items():
        print(mode, value['primary'])


if __name__ == '__main__':
    main()
