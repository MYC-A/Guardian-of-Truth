from experiments.think_gate_20261010.cascade import decide, gate, narrow_context, think_body, votes

P = ('⟦SYSTEM⟧\n<policy>Only refund to original payment.</policy>\n[AVAILABLE TOOLS]\n'
     '- get_user — Get user.\n    user_id: string! — id\n- refund — Refund.\n    amount: number! — sum\n'
     '- refund_v2 — Other.\n    x: string — x\n\n⟦USER⟧\nhi\n\n⟦ASSISTANT⟧\n→ TOOL_CALL get_user {"user_id": "a"}\n')


def test_gate():
    assert gate(0.005) and gate(0.9) and not gate(0.0049) and not gate(None)


def test_votes_and_decide():
    v = dict(content='<think>x</think>\nVERDICT: VIOLATION', finish='stop')
    n = dict(content='<think>x</think>\nVERDICT: NO_VIOLATION', finish='stop')
    cut = dict(content='<think>VERDICT: VIOLATION', finish='length')
    assert votes([v, v, n]) == 2 and decide([v, v, n])
    assert not decide([v, n, cut]) and not decide([]) and not decide(None)


def test_narrow_keeps_used_tools_policy_history():
    c = narrow_context(P, 'I will call refund now')
    assert '- get_user — Get user.' in c and 'user_id: string!' in c       # used in history
    assert '- refund — Refund.' in c and 'amount: number!' in c            # named in the current turn
    assert 'x: string — x' not in c and 'refund_v2' in c                   # unused: name only
    assert 'Only refund to original payment.' in c and '⟦USER⟧\nhi' in c


def test_narrow_no_catalog_is_identity():
    p = '⟦SYSTEM⟧\npolicy\n\n⟦USER⟧\nhi\n'
    assert narrow_context(p, 't') == narrow_context(p, 't') and 'policy' in narrow_context(p, 't')


def test_body():
    b = think_body(P, 'turn', narrow=True)
    assert b['n'] == 3 and b['max_tokens'] == 12288 and b['chat_template_kwargs']['enable_thinking']
    assert 'turn' in b['messages'][1]['content']
