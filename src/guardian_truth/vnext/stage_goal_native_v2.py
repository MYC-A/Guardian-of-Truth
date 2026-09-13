"""Input-only native adapter and post-seal controlled Goal-layer scoring."""

from collections import Counter
from dataclasses import asdict

from .goal_invocation_v2 import GoalInvocationInput, analyze_goal_invocation
from .integrity import digest
from .latency import percentile
from .stage_goal import normalized_text, stage_input
from .stage_results import confusion, fraction


METRIC_RULES = {
    'scope': 'controlled Goal subsystem, NOT whole-Core end-to-end evidence',
    'fields': 'exact source goal/scope IDs; gold step and drift; action text uses fixed stage_goal normalization',
    'eligibility': 'field-specific transport/schema failures excluded from semantic denominators, retained in operational counts',
    'aggregation': 'all-candidate precision, any/all-candidate case recall; unknown placeholders are never dropped',
    'activation': 'none: original v1 source contains no fresh-plan activation contract',
    'interfaces': 'literal plan heads/target are interface candidates only, not trusted effect contracts or closed tool universe',
    'binary': 'diagnostic Goal-layer ERROR or INCONSISTENT=1, otherwise=0; unresolved fallback is not safety proof',
}


def predict_native_goal(value, backend):
    old = stage_input(value)
    data = GoalInvocationInput(old.prompt, old.response, old.declared_goal, old.ordered_plan,
        old.allowed_scope, tool_schemas=old.tool_schemas, history_complete=old.history_complete,
        completeness_basis=old.completeness_basis)
    analysis = analyze_goal_invocation(data, backend)
    return {'parsed': asdict(analysis.parsed), 'decision': asdict(analysis.decision),
        'diagnostics': asdict(analysis.diagnostics), 'binding_candidates': asdict(analysis.binding_candidates),
        'context': asdict(analysis.context), 'ledger': asdict(analysis.ledger), 'plan_activation': None}


def score_native_case(case, prediction):
    parsed, decision = prediction['parsed'], prediction['decision']
    readings = parsed['readings']
    failures = {task: reason for task, reason in parsed['failures']}
    inventory_failed = 'goal_v2_reading_inventory' in failures
    sources = {source['source_id']: source for source in parsed['sources']}
    scope = {sid for sid, source in sources.items() if source['kind'] == 'SCOPE'}
    gold = case['gold']
    conditions = {
        'declared_goal_source': lambda r: r['declared_goal_source'] == 'goal:0',
        'expected_step': lambda r: r['expected_step'] == gold['expected_step'],
        'expected_action_source': lambda r: normalized_text(sources.get(r['expected_action_source'], {}).get('text', '')) == normalized_text(gold['expected_action']),
        'allowed_scope_sources': lambda r: set(r['allowed_scope_sources']) == scope,
        'drift_type': lambda r: r['drift_type'] == gold['drift'],
    }
    fields = {}
    for field, condition in conditions.items():
        correct = sum(bool(condition(reading)) for reading in readings)
        fields[field] = {'eligible': not inventory_failed and 'goal_v2_' + field not in failures,
            'correct': correct, 'candidates': len(readings), 'any_correct': correct > 0,
            'all_correct': bool(readings) and correct == len(readings)}
    binary = int(decision['status'] in {'PROVED_ERROR', 'INCONSISTENT'})
    expected_binary = {'PROVED_ERROR': 1, 'PROVED_NO_ERROR': 0}.get(gold['verdict'])
    components = set()
    for reason in prediction['diagnostics']['contributing_reasons']:
        components.add('TRANSPORT' if reason == 'TRANSPORT_ERROR' else 'SCHEMA' if reason == 'SCHEMA_ERROR' else 'GOAL_PLAN_SEMANTICS')
    if any(row['eligible'] and not row['all_correct'] for row in fields.values()):
        components.add('GOAL_PLAN_SEMANTICS')
    missing = prediction['diagnostics']['missing_evidence']
    if any('active_step' in item or 'prior_completion' in item for item in missing):
        components.add('EVIDENCE_COMPLETENESS')
    return {'case_id': case['case_id'], 'family': case['family'], 'fields': fields,
        'goal_layer_status': decision['status'], 'expected_status': gold['verdict'],
        'diagnostic_binary': binary, 'expected_binary': expected_binary, 'components': sorted(components),
        'primary_reason': prediction['diagnostics']['primary_reason'], 'missing_evidence': missing}


def summarize_native_goal(cases, rows):
    by_id = {row['case_id']: row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != {case['case_id'] for case in cases}:
        raise ValueError('exact complete unique case coverage required')
    scores = [score_native_case(case, by_id[case['case_id']]['prediction']) for case in cases]
    fields = {}
    for field in scores[0]['fields']:
        eligible = [score['fields'][field] for score in scores if score['fields'][field]['eligible']]
        correct = sum(row['correct'] for row in eligible)
        count = sum(row['candidates'] for row in eligible)
        fields[field] = {'eligible_cases': len(eligible), 'excluded_transport_schema': len(scores) - len(eligible),
            'candidate_correct': correct, 'candidate_count': count, 'candidate_accuracy': fraction(correct, count),
            'any_candidate_case_accuracy': fraction(sum(row['any_correct'] for row in eligible), len(eligible)),
            'all_candidate_case_accuracy': fraction(sum(row['all_correct'] for row in eligible), len(eligible))}
    counts = Counter(score['goal_layer_status'] for score in scores)
    telemetry = [item for row in rows for item in row['request_telemetry']]
    binary_scores = [score for score in scores if score['expected_binary'] is not None]
    certs = {}
    for status in ('PROVED_ERROR', 'PROVED_NO_ERROR'):
        decisions = [row['prediction']['decision'] for row in rows if row['prediction']['decision']['status'] == status]
        valid = sum(row['certificate_valid'] is True for row in decisions)
        certs[status] = {'definitive': len(decisions), 'valid': valid, 'rate': fraction(valid, len(decisions))}
    return {'case_count': len(cases), 'unique_semantic_inputs': len({digest({key: value for key, value in case['input'].items() if key != 'context_variant'}) for case in cases}),
        'field_metrics': fields, 'goal_layer': {'counts': dict(counts),
            'resolution_rate': fraction(counts['PROVED_ERROR'] + counts['PROVED_NO_ERROR'], len(scores)),
            'unresolved_rate': fraction(counts['UNRESOLVED'], len(scores)), 'certificate_validation': certs},
        'diagnostic_goal_binary': confusion([(score['expected_binary'], score['diagnostic_binary']) for score in binary_scores]),
        'baseline_x0_binary': confusion([(score['expected_binary'], by_id[score['case_id']]['baseline_x0']['binary_label']) for score in binary_scores]),
        'semantic_coverage': dict(Counter(row['prediction']['parsed']['coverage']['status'] for row in rows)),
        'primary_unresolved_reasons': dict(Counter(score['primary_reason'] for score in scores if score['goal_layer_status'] == 'UNRESOLVED')),
        'provider': {'attempts': len(telemetry), 'transport_success': sum(row['transport_status'] == 'SUCCESS' for row in telemetry),
            'schema_valid': sum(row['schema_status'] == 'VALID' for row in telemetry),
            'latency_ms_p50': percentile([row['latency_ms'] for row in telemetry], .5),
            'latency_ms_p95': percentile([row['latency_ms'] for row in telemetry], .95),
            'token_usage': {key: sum(row['usage'].get(key, 0) for row in telemetry) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
            'cost': 'NOT_AUDITED'}, 'failure_taxonomy': scores, 'blind_cases_read': 0,
        'whole_core_gain': 'NOT_ESTABLISHED_GOAL_SUBSYSTEM_ONLY'}
