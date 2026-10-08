"""Offline score of the frozen pilot; never writes historical data or selects a best attempt."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from experiments.guardian_complementarity.combine import score
from experiments.guardian_local_a100.score_local import classify_row

REF = '51160fcd0b7b9354f8a63615430aeae0c95b591a'
BASE = 'outputs/guardian_local_a100/llamacpp/qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/runs/ext_tau2/B2_rep1.jsonl'
GOLD = 'outputs/verification_v4/external/tau2v2/GOLD_eval_only.json'


def blob(path):
    return subprocess.check_output(['git', 'show', REF + ':' + path], cwd=ROOT)


def analyze(records, expected_ids, external_gold, contrast_gold, baseline):
    seen = {}
    for row in records:
        key = (row['id'], row['mode'])
        if key in seen or row['id'] not in expected_ids or row['mode'] not in ('blind', 'visible'):
            raise ValueError('DUPLICATE_OR_FOREIGN_PILOT_RECORD')
        seen[key] = row
    result = dict(expected_inputs=len(expected_ids), observed_rows=len(seen), models='local Qwen, one diagnostic repetition',
                  cause_truth='PENDING_INDEPENDENT_SOURCE_REVIEW', modes={})
    for mode in ('blind', 'visible'):
        selected = {i: seen.get((i, mode)) for i in expected_ids}
        ext = {i: g['label'] for i, g in external_gold.items() if g.get('label') in (0, 1)}
        contrasts = {i: g['label'] for i, g in contrast_gold.items()}
        legacy = {i: (baseline.get(i) or {}).get('binary') for i in ext}
        usable = {i: legacy[i] if classify_row(baseline.get(i), 'B2', 'binary') != 'no_solution' else None for i in ext}
        added, end, legacy_end = {}, {}, {}
        for i in ext:
            row = selected.get(i)
            add = row.get('automatic_addition') if row else None
            added[i] = int(add) if type(add) is bool else None
            end[i] = 1 if add is True else usable[i]
            # This explicit legacy projection keeps even historically invalid
            # base zero for comparison. It is not a valid-path quality claim.
            legacy_end[i] = 1 if add is True else legacy[i]
        cp = {i: (int(selected[i]['automatic_addition']) if selected.get(i)
                    and type(selected[i].get('automatic_addition')) is bool else None) for i in contrasts}
        changed = [i for i in ext if legacy.get(i) == 0 and legacy_end.get(i) == 1]
        sources = [selected[i] for i in expected_ids if selected.get(i)]
        candidates = [(r['id'], c) for r in sources for c in (r.get('admission') or {}).get('mismatch_candidates', [])]
        verifications = [(r['id'], v) for r in sources for v in r.get('verifications', [])]
        receipt_steps = [r['extraction'] for r in sources if r.get('extraction')]
        receipt_steps += [v['reply'] for _, v in verifications]
        result['modes'][mode] = dict(
            observed=len(sources), missing_ids=sorted(i for i, r in selected.items() if r is None),
            execution_complete=len(sources) == len(expected_ids),
            quality_claim_eligible=(len(sources) == len(expected_ids)
                                    and all(r.get('automatic_addition') is not None for r in sources)),
            status_counts=dict(Counter(r['status'] for r in sources)),
            technical_or_unmeasured_ids=sorted(i for i, r in selected.items() if not r or r.get('automatic_addition') is None),
            labelled_external=len(ext), unlabelled_external_ids=sorted(set(external_gold) - set(ext)),
            archived_binary_projection=dict(QB2=score(ext, legacy), candidate=score(ext, legacy_end),
                                             contract='Historical binary field including invalid zero; diagnostic only'),
            valid_base_with_explicit_fallback=dict(QB2=score(ext, usable), candidate=score(ext, end),
                contract='Optional failed checker falls back to usable cached base; no_solution base stays unknown unless candidate supported'),
            extra_detector_external=score(ext, added), extra_detector_contrasts=score(contrasts, cp),
            fn_recoveries=[i for i in changed if ext[i]], new_false_positive_rows=[i for i in changed if not ext[i]],
            contrast_false_positive_rows=[i for i in contrasts if not contrasts[i] and cp[i] == 1],
            mismatch_candidates=len(candidates), verifier_counts=dict(Counter(v['judgment'].get('verdict') for _, v in verifications)),
            unchecked_candidates=sum(r.get('unchecked_candidates', 0) for r in sources),
            output_tokens=sum((s.get('usage') or {}).get('completion_tokens') or 0 for s in receipt_steps),
            input_tokens=sum((s.get('usage') or {}).get('prompt_tokens') or 0 for s in receipt_steps),
            receipt_calls=len(receipt_steps), noncached_receipts=sum(not s.get('cached', False) for s in receipt_steps),
            usage_missing=sum(not isinstance(s.get('usage'), dict) for s in receipt_steps),
            proposed_changes=[dict(id=i, label=ext[i], verifications=selected[i].get('verifications', [])) for i in changed],
            contrast_predictions=cp)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--records', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--inputs', type=Path, default=ROOT / 'docs/qwen_binding_audit_20261008/pilot_phase1_inputs.jsonl')
    ap.add_argument('--contrast-gold', type=Path, default=ROOT / 'docs/qwen_binding_audit_20261008/contrast_phase1/GOLD_eval_only.json')
    a = ap.parse_args()
    rows = [json.loads(line) for line in a.records.read_text(encoding='utf-8').splitlines() if line.strip()]
    ids = [json.loads(line)['id'] for line in a.inputs.read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(ids) != len(set(ids)):
        raise ValueError('DUPLICATE_EXPECTED_ID')
    baseline = {}
    for row in map(json.loads, blob(BASE).splitlines()):
        if row['id'] in baseline and baseline[row['id']].get('binary') != row.get('binary'):
            raise ValueError('CONFLICTING_ARCHIVED_BASELINE')
        baseline[row['id']] = row
    result = analyze(rows, ids, json.loads(blob(GOLD)), json.loads(a.contrast_gold.read_text(encoding='utf-8')), baseline)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    for mode, r in result['modes'].items():
        print(mode, 'observed', r['observed'], 'complete', r['execution_complete'], 'status', r['status_counts'],
              'external', r['archived_binary_projection']['candidate'],
              'contrasts', r['extra_detector_contrasts'], '+TP', r['fn_recoveries'], '+FP', r['new_false_positive_rows'])


if __name__ == '__main__':
    main()
