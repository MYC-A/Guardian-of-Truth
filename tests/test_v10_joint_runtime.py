import json
import sys
from pathlib import Path
import pytest
from guardian_truth.action_audit.runtime import run_joint, prepare, combine, validate_modes
from guardian_truth.source_search.pipeline import QUESTIONS
from test_action_audit_rules import make, audit, argument

ROOT = Path(__file__).resolve().parents[1]


def reply(action=None, decision='NO_ERROR', findings=()):
    assessment = {'decision': decision, 'explanation': 'The specific move is assessed against raw sources.',
        'findings': list(findings), 'checks': {q: {'status': 'NOT_APPLICABLE', 'reason': 'Not applicable to this move.', 'evidence_ids': []} for q in QUESTIONS},
        'open_questions': [], 'action_audit': action}
    return {'status': 'OK', 'content': json.dumps({'assessment': assessment})}


def test_joint_request_keeps_raw_policy_and_shadow_never_changes_valid_judge(tmp_path):
    store = make(); messages = []
    def ask(value): messages.extend(value); return reply(audit([argument()]))
    result = run_joint(store.raw, ask, store=store, root=ROOT,
        table_config={'mode': 'shadow', 'tables_dir': str(tmp_path)}, audit_config={'mode': 'shadow'},
        mode='auto', max_payload_bytes=800000, checks_mode='diagnostic', final_context='evidence', artifact_guard=True)
    assert result['decision'] == 'NO_ERROR' and len(messages) == 2
    assert result['v10']['variants']['judge_plus_audit'] == 'ERROR'
    assert result['v10']['policy_table']['cache_status'] == 'not_compiled'
    packet = json.loads(messages[1]['content'])
    assert packet['full_context'] == store.raw['prompt']
    assert packet['target_response'] == store.raw['response']
    assert 'action_audit' in messages[0]['content']
    assert result['v10']['comparison_scope'].endswith('NOT_A_CLEAN_A1_A2_COUNTERFACTUAL')


def test_invalid_audit_does_not_downgrade_clean_vote(tmp_path):
    store = make()
    result = run_joint(store.raw, lambda _: reply({'bad': True}), root=ROOT, store=store,
        table_config={'mode': 'shadow', 'tables_dir': str(tmp_path)}, audit_config={'mode': 'shadow'},
        mode='direct', checks_mode='diagnostic')
    assert result['decision'] == 'NO_ERROR'
    assert result['v10']['action_audit']['status'] == 'INVALID_AUDIT'


def test_added_layers_never_cancel_an_existing_error():
    assert set(combine('ERROR', {'findings': []}, {'findings': []}).values()) == {'ERROR'}
    assert combine('UNKNOWN', {'findings': [{'compile_agreement_status': 'SHADOW'}]}, {'findings': []})['full'] == 'UNKNOWN'


def test_decisive_config_is_rejected_without_measured_gates(tmp_path):
    config = {'stages': {'policy_table': {'mode': 'decisive'}}}
    with pytest.raises(ValueError, match='promotion receipt'): validate_modes(config, root=tmp_path)
    score = tmp_path / 'score.json'; score.write_text(json.dumps({'promotion': {'approved_layers': {'policy_table': True}}}))
    import hashlib
    config['promotion_receipt'] = {'score_file': 'score.json', 'score_sha256': hashlib.sha256(score.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match='not satisfied'): validate_modes(config, root=tmp_path)


def test_service_structural_short_circuit_still_logs_policy_shadow(tmp_path):
    sys.path.insert(0, str(ROOT / 'service'))
    import runtime
    instance = runtime.GuardianServiceRuntime('guardian-v10', audit_path=tmp_path / 'audit.jsonl')
    store = make('→ TOOL_CALL tool_missing: {}')
    result = instance.check({'case_id': 'synthetic', **store.raw})
    assert result['decision'] == 'ERROR' and result['usage']['calls'] == 0
    assert result['v10']['policy_table']['cache_status'] == 'not_compiled'
    assert result['v10']['action_audit']['status'] == 'NOT_RUN_STRUCTURAL_HIT'
