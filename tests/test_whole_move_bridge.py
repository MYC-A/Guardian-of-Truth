"""Generic regression: later malformed calls cannot be hidden by a model pass."""
from copy import deepcopy

from experiments.whole_move_compact_v2.bridge import evaluate
from experiments.whole_move_v1.runner import full_packet


def row():
    return dict(prompt='⟦SYSTEM⟧\n<policy>Use the declared field contracts.</policy>\n'
        '[AVAILABLE TOOLS]\n- dax_41 — Read an arbitrary record.\n    token: string!\n'
        '- vel_93 — Read another arbitrary record.\n    anchor: integer!\n'
        '⟦USER⟧\nRead both records if allowed.',
        response='⟦ASSISTANT⟧\n→ TOOL_CALL dax_41: {"token":"k"}\n'
                 '→ TOOL_CALL vel_93: {}\n')


def clean_model_reply(packet):
    return dict(decision='NO_ERROR',regulated_action=dict(target_id=packet['current_targets'][0]['source_id'],
        description='First read'),applicable_norms=[],supporting_evidence=[],exception_analysis='None',
        reason='First call seems fine.',open_questions=[])


def test_later_missing_required_field_overrides_first_action_only_model_pass():
    r=row(); value=clean_model_reply(full_packet(r))
    result=evaluate(r,value,interface='baseline')
    assert result['decision']=='ERROR'
    assert result['basis']=='ORIGINAL_DECLARATION_CONSTRAINT'
    assert result['underlying_model']['decision']=='NO_ERROR'
    assert result['mechanical']['findings'][0]['target_id']=='t1'
    renamed=deepcopy(r)
    for k in ('prompt','response'):
        renamed[k]=renamed[k].replace('dax_41','arbitrary_776').replace('vel_93','other_922').replace('anchor','datum')
    assert evaluate(renamed,clean_model_reply(full_packet(renamed)),interface='baseline')['decision']=='ERROR'


def test_positive_declaration_constraint_survives_rejected_model_stage():
    result=evaluate(row(),{'bad':'reply'})
    assert result['decision']=='ERROR'
    assert result['underlying_model']['status']=='REJECTED'
    assert result['underlying_model']['failure']


def test_no_model_and_schema_pass_does_not_imply_business_no_error():
    r=row();r['response']=r['response'].replace('{}','{"anchor":5}')
    result=evaluate(r)
    assert result['decision']=='UNKNOWN'
    assert result['underlying_model']['status']=='NOT_RUN'
    assert not result['mechanical']['findings']
