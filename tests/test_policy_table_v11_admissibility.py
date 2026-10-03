from test_policy_table_v11 import store
from guardian_truth.policy_table_v11.admissibility import assess, EnforcementPolicy, STRICT, PERMISSIVE
from guardian_truth.policy_table_v11.citations import locate_citation
from guardian_truth.policy_table_v11.router import route_step


def test_router_separates_prose_from_calls():
    assert route_step(store(response='Готово, спасибо!')).kind == 'PROSE'
    assert route_step(store()).kind in ('TOOL_CALL', 'MIXED')


def test_prose_is_not_sent_to_prover_and_mode_decides():
    s = store(response='Готово, спасибо!')
    t = assess(s)
    assert t['route'] == 'PROSE' and t['channels'] == ['prose_verifier'] and not t['inspected_calls']
    # Bounded prose invariants pass -> ADMISSIBLE with the unchecked semantics reported as residual risk.
    assert t['verdict'] == 'ADMISSIBLE' and any(n['code'] == 'PROSE_RESIDUAL_RISK' for n in t['notes'])
    e = store(response='   ')
    assert assess(e)['verdict'] == 'UNKNOWN' and assess(e)['route'] == 'EMPTY'
    assert assess(e, enforcement=EnforcementPolicy(STRICT))['decision'] == 'REJECT'
    assert assess(e, enforcement=EnforcementPolicy(PERMISSIVE))['decision'] == 'ALLOW'


def test_undeclared_argument_is_violation_with_audit_trace():
    s = store(response='→ TOOL_CALL apply_a: {"record_id":"X","amount":2,"bogus":1}')
    t = assess(s)
    assert t['verdict'] == 'VIOLATION' and t['decision'] == 'REJECT'
    assert any(v['code'] == 'UNDECLARED_ARGUMENT' and v['argument'] == 'bogus' for v in t['violations'])
    assert t['trace_id'] and t['policy_sha256'] and t['graph_snapshot']


def test_whitespace_and_typographic_quotes_are_presentation_only():
    text = 'Do  not modify the “number” of passengers.'
    assert locate_citation('Do not modify the "number" of passengers.', text).conversion == 'WHITESPACE_AND_GLYPHS'
    assert locate_citation('do not modify', text) is None  # casing is never repaired
