"""Post-report Goal v2 telemetry/source-field audit; no old metrics are changed."""

from collections import Counter
import json
from pathlib import Path

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, write_new


ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / 'outputs/vnext'
    prefix = 'goal_plan_v2'
    freeze_path = output / (prefix + '_freeze.json')
    report_path = output / (prefix + '_results.json')
    audit_path = output / (prefix + '_failure_audit.json')
    freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
    report = json.loads(report_path.read_text(encoding='utf-8'))
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    rows = json.loads((output / (prefix + '_predictions.json')).read_text(encoding='utf-8'))
    seal = json.loads((output / (prefix + '_prediction_seal.json')).read_text(encoding='utf-8'))
    if (seal != prediction_seal(rows, freeze['case_ids'], architecture_commit=freeze['architecture_commit'],
            configuration_sha256=digest(freeze)) or audit['source_report_sha256'] != file_digest(report_path)
            or audit['cases'] != report['failure_taxonomy']):
        raise ValueError('full report/prediction seal/failure taxonomy must be valid before analysis')
    schema_codes, schema_tasks, unknown_fields, components = Counter(), Counter(), Counter(), Counter()
    source_nulls, source_changed, source_null_without_goal_anchor, cases = 0, 0, 0, []
    for index, row in enumerate(rows):
        parsed, telemetry = row['prediction']['parsed'], row['request_telemetry']
        readings = {reading['reading_id']: reading for reading in parsed['readings']}
        issues, raw_sources, case_components = [], [], report['failure_taxonomy'][index]['components']
        components.update(case_components)
        for reading in readings.values():
            unknown_fields.update(reading['unknown_fields'])
        for ordinal, record in enumerate(telemetry):
            request_path = output / f'{prefix}_case_{index:03d}_request_{ordinal:03d}.json'
            result_path = output / f'{prefix}_case_{index:03d}_request_{ordinal:03d}_result.json'
            request = json.loads(request_path.read_text(encoding='utf-8'))
            result = json.loads(result_path.read_text(encoding='utf-8'))
            if result['request_sha256'] != digest(request) or result['telemetry'] != record:
                raise ValueError('persisted request/result telemetry mismatch')
            if record['schema_status'] == 'INVALID':
                schema_tasks.update([record['task']])
                codes = [issue['code'] for issue in record.get('schema_issues', [])]
                schema_codes.update(codes)
                issues.append({'task': record['task'], 'codes': codes})
            proposal = result['proposal']
            if record['task'] == 'goal_v2_declared_goal_source' and proposal['schema_status'] == 'VALID':
                raw = json.loads(proposal['payload_json'])
                for candidate in raw['readings']:
                    reading = readings[candidate['reading_id']]
                    value = candidate['declared_goal_source']
                    changed = value != reading['declared_goal_source']
                    source_nulls += value is None
                    source_changed += changed
                    missing_anchor = value is None and 'goal:0' not in reading['source_ids']
                    source_null_without_goal_anchor += missing_anchor
                    raw_sources.append({'reading_id': candidate['reading_id'], 'raw_source': value,
                        'accepted_source': reading['declared_goal_source'], 'parser_changed_value': changed,
                        'basis_includes_declared_goal': 'goal:0' in reading['source_ids']})
        cases.append({'case_id': row['case_id'], 'components': case_components,
            'schema_issues': issues, 'reading_unknown_fields': {key: value['unknown_fields'] for key, value in readings.items()},
            'declared_goal_source_transfer': raw_sources,
            'coverage': parsed['coverage']['status'], 'worlds': len(row['prediction']['decision']['world_proofs']),
            'binding_tasks': sum(record['task'].startswith('goal_binding') for record in telemetry),
            'plan_activation': row['prediction']['plan_activation']})
    detailed = {'experiment': prefix, 'source_report_sha256': file_digest(report_path),
        'source_original_audit_sha256': file_digest(audit_path), 'case_count': len(cases),
        'schema_invalid_by_task': dict(schema_tasks), 'schema_issue_codes': dict(schema_codes),
        'reading_unknown_fields': dict(unknown_fields), 'case_components': dict(components),
        'raw_declared_goal_nulls': source_nulls, 'parser_changed_declared_goal_values': source_changed,
        'raw_null_with_basis_not_citing_goal': source_null_without_goal_anchor,
        'source_null_interpretation': 'observed raw-output/basis association only; not evidence of a parser loss or causal explanation',
        'schema_cause_limit': 'invalid content/finish_reason not retained; JSON_INVALID does not establish truncation or markdown cause',
        'progress_limit': 'no original fresh-plan activation contract; expected-step match is an annotation proxy, not proof of active progress',
        'whole_core_gain': 'NOT_ESTABLISHED', 'blind_gold_read': False, 'cases': cases}
    write_new(output / (prefix + '_detailed_audit.json'), detailed)
    print(json.dumps({key: detailed[key] for key in ('case_count', 'schema_invalid_by_task', 'schema_issue_codes',
        'reading_unknown_fields', 'case_components', 'raw_declared_goal_nulls', 'parser_changed_declared_goal_values')}))


if __name__ == '__main__':
    main()
