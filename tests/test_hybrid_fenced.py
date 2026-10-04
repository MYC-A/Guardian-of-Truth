import pytest
from experiments.hybrid_diagnostics.fenced_replay import unwrap, normalize_record


def test_one_full_fence_preserves_inner_field_order():
    reply = unwrap(' \n```json\r\n{"reason":"first","decision":"ERROR"}\r\n```\n')
    assert list(reply) == ['reason', 'decision']


@pytest.mark.parametrize('text', [
    '{"decision":"ERROR"}', '```json\n{}', '```json\n{}\n``` trailing',
    'leading ```json\n{}\n```', '```json\n{}\n```\n```json\n{}\n```',
    '```python\n{}\n```', '```json\n{"x":1,"x":2}\n```',
    '```json\n{"x":NaN}\n```', '```json\n{"x":1e999}\n```',
    '```json\n[]\n```', None,
])
def test_unsafe_wrappers_or_inner_json_rejected(text):
    with pytest.raises(ValueError): unwrap(text)


def packet():
    return dict(current_targets=[dict(source_id='t0', role='assistant')],
                normative_sources=[dict(source_id='q0', role='system')],
                history=[dict(source_id='h1', role='user')], declarations=[])


def record(actor='user', finish='stop'):
    import json
    value = dict(decision='ERROR', regulated_action=dict(target_id='t0', description='Current'),
                 applicable_norms=[dict(policy_source_id='q0', interpretation='Hypothesis', modality='FORBID')],
                 supporting_evidence=[dict(source_id='h1', actor=actor, role='statement', fact='Observed')],
                 exception_analysis='None applicable', reason='Hypothesis', open_questions=[])
    return dict(status='OK', provider_response=dict(choices=[dict(finish_reason=finish,
                message=dict(content='```json\n'+json.dumps(value)+'\n```'))]))


def test_actor_admission_is_not_relaxed():
    result = normalize_record(record('assistant'), packet())
    assert result['format_valid'] and result['schema_valid']
    assert not result['fully_admitted'] and result['decision'] is None
    assert 'EVIDENCE_REFERENCE_OR_ACTOR_INVALID' in result['failure']


def test_original_source_admission_passes_without_code_proof():
    result = normalize_record(record(), packet())
    assert result['fully_admitted'] and result['decision'] == 'ERROR'
    assert result['code_proof'] is False


def test_unfinished_provider_not_rescued_by_fence():
    result = normalize_record(record(finish='length'), packet())
    assert result['failure'] == 'UNFINISHED_REPLY' and result['decision'] is None
