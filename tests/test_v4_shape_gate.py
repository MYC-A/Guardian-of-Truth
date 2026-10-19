import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from v4_shape_gate import scan


def test_opt_in_mechanical_gate_and_default_compatibility():
    from guardian_truth.judge.mechanical import analyze
    p=prompt(ONE);r=turn(CALL+CALL)
    baseline=analyze(p,r)
    enabled=analyze(p,r,bounded_turn_shape=True)
    assert not any(x.startswith('bounded_turn_shape') for x in baseline.hard)
    assert any(x.startswith('bounded_turn_shape MAX_ONE_CALL') for x in enabled.hard)
    assert enabled.features['n_hard']==len(enabled.hard)
    permitted=analyze(prompt(ONE+' Except for read-only lookups.'),r,bounded_turn_shape=True)
    assert not any(x.startswith('bounded_turn_shape') for x in permitted.hard)

ONE='You should only make one tool call at a time.'
MIX='If you make a tool call, you should not respond to the user at the same time.'
CALL='\t→ TOOL_CALL lookup: {"id":"a"}\n'


def prompt(rule,user='OK',history=''):
    return ('⟦SYSTEM⟧\n<policy>\n'+rule+'\n</policy>\n[AVAILABLE TOOLS]\n'
            '- lookup — Read-only lookup.\n    id: string!\n'+history+'⟦USER⟧\n'+user)


def turn(body):return '⟦ASSISTANT · ход 2⟧\n'+body


@pytest.mark.parametrize('rule',[
    'You may make more than one tool call at a time.',
    'Before confirmation, you should only make one tool call at a time.',
    'Before confirmation:\n- '+ONE,
    '# Before authentication\n'+ONE,
    ONE+' Except for read-only lookups.',
    ONE+'\nRead-only lookups are exempt.',
    'The obsolete rule was "'+ONE+'".\nMultiple calls are allowed.',
    '```\n'+ONE+'\n```',
])
def test_scope_exceptions_permissions_and_quotes_do_not_force(rule):
    assert not scan(prompt(rule),turn(CALL+CALL))['violations']


def test_two_actual_calls_and_mixed_current_turn_are_detected():
    assert {r['kind'] for r in scan(prompt(ONE),turn(CALL+CALL))['violations']}=={'MAX_ONE_CALL'}
    assert {r['kind'] for r in scan(prompt(MIX),turn('I will check.\n'+CALL))['violations']}=={'NO_TEXT_WITH_CALL'}


def test_compound_retail_and_airline_are_supported():
    for sentence in [
        'You should at most make one tool call at a time, and if you take a tool call, you should not respond to the user at the same time. If you respond to the user, you should not make a tool call at the same time.',
        'You should only make one tool call at a time, and if you make a tool call, you should not respond to the user simultaneously. If you respond to the user, you should not make a tool call at the same time.',
    ]:
        result=scan(prompt(sentence),turn('I will check.\n'+CALL+CALL))
        assert {r['kind'] for r in result['violations']}=={'MAX_ONE_CALL','NO_TEXT_WITH_CALL'}


def test_absent_or_user_only_rule_history_and_single_mode_do_not_force():
    assert not scan(prompt('Be helpful.',user=ONE),turn(CALL+CALL))['violations']
    assert not scan(prompt(MIX),turn(CALL))['violations']
    assert not scan(prompt(MIX),turn('Hello.'))['violations']
    earlier='⟦ASSISTANT · ход 1⟧\nEarlier narration.\n'+CALL
    assert not scan(prompt(ONE+'\n'+MIX,history=earlier),turn(CALL))['violations']


def test_whitespace_thoughts_transfer_and_ambiguous_multiple_messages():
    for body in [' \n'+CALL,'<think>Plan privately.</think>\n'+CALL,'<analysis>Plan.</analysis>\n'+CALL]:
        assert not scan(prompt(MIX),turn(body))['violations']
    assert scan(prompt(MIX),turn('<think>Unclosed\n'+CALL))['status']=='UNKNOWN'
    transfer='I am transferring you.\n\t→ TOOL_CALL transfer_to_human_agents: {"summary":"help"}'
    assert scan(prompt(MIX),turn(transfer))['status']=='UNKNOWN'
    assert scan(prompt(ONE),turn(CALL)+'⟦ASSISTANT · ход 3⟧\n'+CALL)['status']=='UNKNOWN'


def test_either_block_has_source_and_scope_binding():
    either='In each turn you can either:\n- Send a message to the user.\n- Make a tool call.\nYou cannot do both at the same time.'
    assert scan(prompt(either),turn('Hi.\n'+CALL))['violations']
    assert not scan(prompt('Before confirmation:\n'+either),turn('Hi.\n'+CALL))['violations']
    assert not scan(prompt('Example:\n'+either),turn('Hi.\n'+CALL))['violations']


def test_renamed_or_wrapped_transfer_keeps_exception_and_results_are_not_text():
    policy=MIX+"\nTo transfer, first make a tool call to handoff, and then send the message 'Please hold.'"
    renamed='Please hold.\n\t→ TOOL_CALL handoff: {"summary":"help"}'
    assert not scan(prompt(policy),turn(renamed))['violations']
    wrapped='Please hold.\n\t→ TOOL_CALL call_discoverable_agent_tool: {"agent_tool_name":"handoff","arguments":"{}"}'
    assert not scan(prompt(policy),turn(wrapped))['violations']
    result=CALL+'\t← TOOL_RESPONSE lookup: A customer-facing-looking string inside a tool result.\n'
    assert not scan(prompt(MIX),turn(result))['violations']
    assert not scan(prompt(ONE),'⟦USER⟧\n'+CALL+CALL)['violations']
