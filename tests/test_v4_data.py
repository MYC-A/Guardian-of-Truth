import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from v4_data import judge_input
from v4_shape_gate import scan
from guardian_truth.transcript import parse_document


def row():
    return dict(id='case',policy='If you make a tool call, you should not respond to the user at the same time.',
        tools=[],history=[dict(role='user',content='Please check the record.')],
        target_turn=dict(role='assistant',content='I will check.',
            tool_calls=[dict(function=dict(name='lookup',arguments={'id':'a'}))]),
        label=1,proof={'hidden':'LABEL_PROOF_MUST_STAY_OUT'},governing_rule='not model metadata')


def test_v4_target_is_one_current_assistant_message_and_shape_is_visible():
    r=judge_input(row());p=parse_document(r['response'],'response')
    assert not p.diagnostics and len(p.messages)==1 and p.messages[0].role=='assistant'
    assert len(p.calls(owner='assistant'))==1
    assert [x['kind'] for x in scan(r['prompt'],r['response'])['violations']]==['NO_TEXT_WITH_CALL']
    assert 'LABEL_PROOF_MUST_STAY_OUT' not in str(r)


def test_tool_only_and_user_owned_history_do_not_become_current_mixed_turn():
    x=row();x['history']=[dict(role='user',content='',tool_calls=[dict(function=dict(name='device',arguments={}))])]
    x['target_turn']['content']=''
    r=judge_input(x);p=parse_document(r['prompt'])
    assert len(p.calls(owner='user'))==1
    assert not scan(r['prompt'],r['response'])['violations']
