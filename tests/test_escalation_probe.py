from experiments.escalation_probe_20261010.probe import compress_history, request_messages, trigger, verify

POLICY = 'You may look up orders with get_order_details when the user gives an order id.'
PROMPT = ('⟦SYSTEM⟧\n<policy>\n' + POLICY + '\n</policy>\n[AVAILABLE TOOLS]\n'
          '- get_order_details — Get order.\n    order_id: string! — id\n'
          '- transfer_to_human_agents — Transfer.\n    summary: string! — why\n'
          '⟦USER⟧\nМой заказ #W123, где он?\n'
          '⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL get_order_details: {"order_id": "#W999"}\n'
          '\t← TOOL_RESPONSE get_order_details [ERROR]: not found\n⟦USER⟧\nПроверьте ещё раз пожалуйста\n')
TRANSFER_TURN = '⟦ASSISTANT · ход 2⟧\n\t→ TOOL_CALL transfer_to_human_agents: {"summary": "x"}'
GOOD = dict(tool='get_order_details', arguments={'order_id': '#W123'}, history_quote='Мой заказ #W123, где он?',
            policy_quote='You may look up orders with get_order_details')


def test_trigger():
    assert trigger(PROMPT, TRANSFER_TURN) == 'transfer'
    assert trigger(PROMPT, 'Я не смогу это сделать, переведу вас на специалиста.') == 'refusal'
    assert trigger(PROMPT, 'Ваш заказ в пути.') is None
    assert trigger(PROMPT, '\t→ TOOL_CALL get_order_details: {"order_id": "#W123"}') is None


def test_verify_accepts_grounded_answer():
    assert verify(PROMPT, GOOD) == (True, 'verified')


def test_verify_abstains():
    assert verify(PROMPT, dict(GOOD, tool=None))[1] == 'null'
    assert verify(PROMPT, dict(GOOD, tool='refund_order'))[1] == 'tool_not_in_catalog'
    assert verify(PROMPT, dict(GOOD, tool='transfer_to_human_agents', arguments={'summary': 'Мой'}))[1] == 'transfer_tool'
    assert verify(PROMPT, dict(GOOD, arguments={'order_id': '#W777'}))[1] == 'arg_not_in_history'
    assert verify(PROMPT, dict(GOOD, arguments={'order_id': '#W999'}))[1] == 'already_called'
    assert verify(PROMPT, dict(GOOD, arguments={}))[1] == 'schema'
    assert verify(PROMPT, dict(GOOD, history_quote='совсем другой текст из ниоткуда'))[1] == 'history_quote'
    assert verify(PROMPT, dict(GOOD, policy_quote='Мой заказ #W123, где он?'))[1] == 'policy_quote'
    assert verify(PROMPT, None)[1] == 'unparsed'


def test_argument_only_in_policy_is_not_grounded():
    p = PROMPT.replace(POLICY, POLICY + ' Example id #W555.')
    assert verify(p, dict(GOOD, arguments={'order_id': '#W555'}))[1] == 'arg_not_in_history'


def test_compress_history_truncates_and_keeps_tail():
    big = '⟦USER⟧\nfirst\n⟦ASSISTANT · ход 1⟧\n\t← TOOL_RESPONSE kb: ok\n' + '\t  ' + 'x' * 5000 + '\n'
    big += ''.join(f'⟦USER⟧\nq{i}\n⟦ASSISTANT · ход {i}⟧\n\t← TOOL_RESPONSE kb: r\n\t  ' + 'y' * 1100 + '\n' for i in range(2, 60))
    out = compress_history(big)
    assert len(out) <= 30000 + 2000 and out.startswith('⟦USER⟧\nfirst') and 'q59' in out
    assert 'older turns omitted' in out
    small = compress_history('⟦USER⟧\nq\n⟦ASSISTANT · ход 1⟧\n\t← TOOL_RESPONSE kb: ok\n\t  ' + 'x' * 5000 + '\n⟦USER⟧\nnext\n')
    assert 'truncated' in small and small.endswith('⟦USER⟧\nnext\n') and len(small) < 1400


def test_request_keeps_full_policy_and_turn():
    m = request_messages(PROMPT, TRANSFER_TURN)
    assert POLICY in m[1]['content'] and TRANSFER_TURN in m[1]['content']
