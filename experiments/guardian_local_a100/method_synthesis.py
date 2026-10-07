"""Offline, Git-blob-only diagnostic of the frozen first model circle.

Reads illegal-on-Windows model paths without checking them out. No inference,
runtime changes, inferred missing predictions, or relabeling. The output path
must be new. Run from a checkout containing the specified commit.
"""
import argparse
from collections import Counter
import hashlib
import io
import itertools
import json
from pathlib import Path
import subprocess

from experiments.guardian_local_a100.score_local import classify_row, prepass_info
from guardian_truth.integrated.reviewer import decode_reply

VERSION = 'method-synthesis-v1'
MODELS = {
    'qwen': 'llamacpp/qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459',
    'gptoss': 'vllm/gpt-oss-20b@6cee5e81ee83:mxfp4:vllm-0.31.0',
    'compass': 'llamacpp/compassjudger-2-32b@7f6877f97adf:Q8_0:llamacpp-b11459',
    'ministral': 'vllm/ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0',
    'distill': 'llamacpp/qwen3.8-27b-opus-distill-v2@64d56b13ea8d:Q8_0:llamacpp-b11459',
}


def blob(commit, path):
    return subprocess.check_output(['git', 'show', f'{commit}:{path}'])


def metrics(predictions, gold):
    counts = Counter()
    for key, label in gold.items():
        value = predictions.get(key)
        if value is None:
            counts['unavailable_positive' if label else 'unavailable_negative'] += 1
        else:
            if type(value) is not int or value not in (0, 1):
                raise ValueError(f'Invalid binary decision: {key}')
            counts[{(1, 1): 'TP', (1, 0): 'FP', (0, 1): 'FN', (0, 0): 'TN'}[value, label]] += 1
    out = {name: counts[name] for name in ('TP', 'FP', 'FN', 'TN', 'unavailable_positive', 'unavailable_negative')}
    out['expected_rows'] = len(gold)
    out['usable_rows'] = sum(out[name] for name in ('TP', 'FP', 'FN', 'TN'))
    den = 2 * out['TP'] + out['FP'] + out['FN']
    out['conditional_f1'] = 2 * out['TP'] / den if den else 0.0
    # Bounds over possible assignments of unavailable decisions, not predictions.
    best_tp, best_fn = out['TP'] + out['unavailable_positive'], out['FN']
    worst_fp = out['FP'] + out['unavailable_negative']
    worst_fn = out['FN'] + out['unavailable_positive']
    best_den = 2 * best_tp + out['FP'] + best_fn
    worst_den = 2 * out['TP'] + worst_fp + worst_fn
    out['full_set_f1_assignment_bounds'] = [
        2 * out['TP'] / worst_den if worst_den else 0.0,
        2 * best_tp / best_den if best_den else 0.0,
    ]
    return out


def load_rows(data, expected):
    rows = {}
    for line in data.splitlines():
        row = json.loads(line)
        key = row['id']
        if key in rows or key not in expected:
            raise ValueError(f'Duplicate or unexpected ID: {key}')
        rows[key] = row
    return rows


def step_brief(step):
    return {name: step.get(name) for name in ('tag', 'admission', 'finish_reason', 'injected', 'input_budget', 'transport', 'parsed_ok')}


def summarize(rows, variant, gold):
    pick = 'binary_rfix' if variant == 'A' else 'binary'
    predictions, cases = {}, {}
    classes, funnel, pre_status, comp_status, raw_fn = Counter(), Counter(), Counter(), Counter(), Counter()
    pre_failures = Counter()
    for key in sorted(gold):
        row = rows.get(key)
        cls = classify_row(row, variant, pick)
        classes[cls] += 1
        prediction = row.get(pick) if row and cls not in ('missing', 'no_solution') else None
        predictions[key] = prediction
        if row is None:
            cases[key] = dict(label=gold[key], prediction=None, row_class=cls)
            continue
        has_pre, delivered = prepass_info(row)
        pre_status['delivered' if delivered else 'not_delivered' if has_pre else 'absent'] += 1
        rec = row.get('rec') or {}
        components = rec.get('components') or {}
        pool = rec.get('pool') or []
        if prediction == 0 and gold[key] == 1:
            # Structural observations only; NO_COMPONENT does not prove a trigger
            # was absent or that an oracle binding would fix the row.
            bucket = ('NO_COMPONENT' if not components else 'COMPONENT_NO_POOL' if not pool else 'POOL_NO_FINAL_ERROR')
            funnel[bucket] += 1
        for name, component in components.items():
            if isinstance(component, dict):
                comp_status[f'{name}:{component.get("admission", "UNSPECIFIED")}'] += 1
        review_steps = (rec.get('A') or {}).get('steps') or []
        primary = next((step for step in review_steps if step.get('tag') == 'review'), {})
        decoded, valid, _ = decode_reply(primary.get('raw_content'))
        raw_decision = decoded.get('decision') if valid and isinstance(decoded, dict) else None
        if gold[key] and prediction == 0:
            raw_fn[str(raw_decision)] += 1
        for step in row.get('pre_steps') or []:
            status = str((step.get('transport') or {}).get('status'))
            if step.get('tag') == 'pre_injection_budget':
                pre_failures['INJECTION_BYTE_CAP'] += 1
            elif step.get('parsed_ok') is False:
                pre_failures['PRE_DECODE_OR_SCHEMA_FAILURE'] += 1
            elif status not in ('200', 'None'):
                pre_failures['PRE_TRANSPORT_OR_BUDGET_FAILURE'] += 1
        cases[key] = dict(
            label=gold[key], prediction=prediction, row_class=cls,
            delivered=delivered, has_pre=has_pre, base_error=rec.get('base_error'),
            review_decision=(rec.get('A') or {}).get('final'),
            raw_review_decision=raw_decision,
            review_admission=(rec.get('A_adm2') or {}).get('admission'),
            components=sorted(components), pool_size=len(pool),
            component_summary={name: dict(
                admission=component.get('admission'),
                claims=len(component.get('claims') or []),
                candidates=len(component.get('candidates') or []),
                bindings=len(component.get('bindings') or []),
            ) for name, component in components.items() if isinstance(component, dict)},
            owner=row.get('owner_rfix' if variant == 'A' else 'owner'),
            accusation=row.get('accusation_rfix' if variant == 'A' else 'accusation'),
            technical_gaps=row.get('technical_gaps'), error=row.get('error'),
            pre_steps=[step_brief(step) for step in row.get('pre_steps') or []],
            review_steps=[step_brief(step) for step in review_steps],
            review_keys=[step.get('key') for step in review_steps],
            source_coverage=(row.get('layer_trace') or {}).get('coverage'),
        )
    return dict(metrics=metrics(predictions, gold), classes=dict(classes),
                prepass=dict(pre_status), fn_structure=dict(funnel),
                fn_raw_decisions=dict(raw_fn), pre_failures=dict(pre_failures),
                component_admissions=dict(comp_status), cases=cases), predictions


def pair_report(left, right, gold):
    common = {key: label for key, label in gold.items() if left.get(key) is not None and right.get(key) is not None}
    return dict(
        common_rows=len(common), excluded_ids=sorted(set(gold) - set(common)),
        left=metrics(left, common), right=metrics(right, common),
        left_only_positive=sorted(key for key in common if left[key] == 1 and right[key] == 0),
        right_only_positive=sorted(key for key in common if right[key] == 1 and left[key] == 0),
        both_fn=sorted(key for key in common if gold[key] and not left[key] and not right[key]),
        offline_or=metrics({key: left[key] | right[key] for key in common}, common),
        offline_and=metrics({key: left[key] & right[key] for key in common}, common),
        interpretation='Post-hoc overlap diagnostic; no source/cause validation or measured deployable routing.',
    )


def run(commit):
    import pandas as pd
    commit = subprocess.check_output(['git', 'rev-parse', f'{commit}^{{commit}}'], text=True).strip()
    data = blob(commit, 'valid.parquet')
    frame = pd.read_parquet(io.BytesIO(data))
    if len(frame) != 46 or frame.id.duplicated().any() or frame.label.value_counts().to_dict() != {0: 23, 1: 23}:
        raise ValueError('Unexpected valid46 inventory')
    gold = {row.id: int(row.label) for row in frame.itertuples()}
    all_paths = set(subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', commit], text=True).splitlines())
    report = dict(version=VERSION, source_commit=commit, gold_sha256=hashlib.sha256(data).hexdigest(),
                  inference_calls=0, labels_changed=0, models={}, artifacts={}, pairs={})
    predictions = {}
    for name, model in MODELS.items():
        result = {}
        for arm, file_arm in (('A', 'AM'), ('M', 'AM'), ('B2', 'B2')):
            path = f'outputs/guardian_local_a100/{model}/runs/valid46/{file_arm}_rep1.jsonl'
            if path not in all_paths:
                raise ValueError(f'Missing run blob: {path}')
            raw = blob(commit, path)
            report['artifacts'][path] = hashlib.sha256(raw).hexdigest()
            rows = load_rows(raw, gold)
            result[arm], predictions[name, arm] = summarize(rows, arm, gold)
        result['AM_B2_overlap'] = pair_report(predictions[name, 'A'], predictions[name, 'B2'], gold)
        a_cases, b_cases = result['A']['cases'], result['B2']['cases']
        result['undelivered_review_same_key'] = sorted(
            key for key in gold if b_cases[key].get('has_pre') and not b_cases[key].get('delivered')
            and a_cases[key].get('review_keys') and a_cases[key]['review_keys'] == b_cases[key].get('review_keys'))
        result['B2_by_delivery'] = {
            status: metrics(predictions[name, 'B2'], {key: label for key, label in gold.items()
                            if b_cases[key].get('delivered') is delivered})
            for status, delivered in (('delivered', True), ('undelivered_or_absent', False))
        }
        report['models'][name] = result
    for left, right in itertools.combinations(('qwen', 'gptoss', 'ministral', 'compass'), 2):
        report['pairs'][f'{left}_B2+{right}_B2'] = pair_report(predictions[left, 'B2'], predictions[right, 'B2'], gold)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = run(args.commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(output=str(args.output), source_commit=report['source_commit'], inference_calls=0)))


if __name__ == '__main__':
    main()
