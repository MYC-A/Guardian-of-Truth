"""Production-parser contrasts for bounded P/S/F contracts; no live model calls."""
import copy
import json

import pytest

from guardian_truth.verification.pipeline import packet_for
from guardian_truth.v6fix import provenance as P, structural as S, turnrules as F


CATALOG = '''[AVAILABLE TOOLS]
- inspect_record — Inspect an existing record.
    record_id: string! — The identifier of any existing record.
- locate_record — Locate an existing record by contact.
    contact: string! — Contact address.
- publish_record — Publish a record.
    record_id: string! — The existing record identifier.
    recipient: string! — Recipient identifier.
'''


def packet(policy, current, history='⟦USER⟧\nPlease inspect my record.', *, closed=True, catalog=CATALOG):
    row = dict(prompt='⟦SYSTEM⟧\n' + policy + '\n' + catalog + '\n' + history,
               response='⟦ASSISTANT · ход 1⟧\n' + current)
    p = packet_for(row, 400000)
    assert p['coverage']['complete_input']
    p['coverage']['provenance_universe_closed'] = closed
    p['coverage']['tool_universe_closed'] = closed
    return p


def current(value='R-unknown', tool='inspect_record', field='record_id'):
    return f'→ TOOL_CALL {tool}: ' + json.dumps({field: value})


def mechanical(findings):
    return [f for f in findings if f['status'] == 'MECHANICAL']


@pytest.mark.parametrize('policy', [
    'For publication, record_id must come directly from the user. For inspection, derive the ID from a prefix.',
    'It is not true that record_id must come from the user.',
    'The record total must come directly from the user.',
    'The record_id must come from the user, or from a verified tool result.',
    'If publication is requested:\nGeneral provenance rules:\nThe record_id must come from the user.',
    'Publication:\nThe record_id must come from the user.',
    'The record_id must come from the user.\nThis requirement does not apply to inspection.',
    'The record_id must come from the user.\nAdministrators are exempt from this requirement.',
    'The record_id must come from the user.\nThe preceding obligation is waived for this session.',
])
def test_P_unsupported_action_polarity_alternatives_and_context_never_decide(policy):
    p = packet(policy, current())
    assert mechanical(P.check(p)[0]) == []


@pytest.mark.parametrize('policy', ['Only use identifiers provided verbatim by the user or the tools.',
                                    'The record_id must come directly from the user.'])
def test_P_bounded_standalone_contract_checks_missing_and_present_exact_value(policy):
    missing = packet(policy, current())
    assert len(mechanical(P.check(missing)[0])) == 1
    present = packet(policy, current(), '⟦USER⟧\nInspect R-unknown.')
    assert not P.check(present)[0]
    not_closed = packet(policy, current(), closed=False)
    assert P.check(not_closed)[0] and not mechanical(P.check(not_closed)[0])
    reduced = copy.deepcopy(missing)
    reduced['coverage']['complete_input'] = False
    assert not mechanical(P.check(reduced)[0])


def test_P_exact_tool_scope_does_not_transfer_between_tools():
    policy = 'The record_id of publish_record must come directly from the user.'
    assert mechanical(P.check(packet(policy, current()))[0]) == []
    assert len(mechanical(P.check(packet(policy, current(tool='publish_record')))[0])) == 1


def test_P_explicit_observed_input_scope_does_not_need_full_history_claim():
    p = packet('The record_id must come directly from the user in this input.', current(), closed=False)
    findings = mechanical(P.check(p)[0])
    assert len(findings) == 1 and findings[0]['norm']['closure_status'] == 'BOUNDED_BY_NORM'


@pytest.mark.parametrize('separator', ['\n', '\n\n'])
def test_P_unparsed_modifier_in_another_paragraph_cannot_acquire_code_authority(separator):
    policy = 'The record_id must come from the user in this input.' + separator + 'Administrators may derive identifiers.'
    assert not mechanical(P.check(packet(policy, current()))[0])


def test_P_sibling_normative_document_may_qualify_requirement():
    p = packet('The record_id must come from the user in this input.', current())
    p['normative_sources'].append(dict(source_id='q-extra', text='Administrators are exempt from this requirement.'))
    assert not mechanical(P.check(p)[0])


def test_P_any_existing_description_does_not_grant_generation():
    variants = [CATALOG, CATALOG.replace('identifier of any existing record', 'existing record identifier')]
    for cat in variants:
        p = packet('The record_id must come directly from the user.', current(), catalog=cat)
        assert len(mechanical(P.check(p)[0])) == 1
        assert P.check(p)[1][0]['field_kind'] == 'REFERENCE'


def test_P_no_invent_does_not_prove_derived_identifier_is_illegal():
    p = packet('You must not invent identifiers.', current('R-A'),
               '⟦USER⟧\nInspect my record whose ID is the prefix R followed by -A.')
    findings, records = P.check(p)
    assert records[0]['status'] == 'NOT_FOUND'
    assert findings and not mechanical(findings)
    assert findings[0]['norm']['provenance_implication'] == 'UNRESOLVED_DERIVATION_VS_INVENTION'


def test_P_source_only_verbatim_contract_differs_from_no_invention():
    policy = 'Only use values provided verbatim by the user or the tools in this input.'
    p = packet(policy, current('R-unknown'), closed=False)
    assert len(mechanical(P.check(p)[0])) == 1
    p = packet(policy, current('R-unknown'), '⟦USER⟧\nInspect R-unknown.', closed=False)
    assert not P.check(p)[0]
    p = packet('Only use values provided by the user or the tools in this input.', current('R-A'),
               '⟦USER⟧\nInspect prefix R followed by -A.', closed=False)
    assert P.check(p)[0] and not mechanical(P.check(p)[0])


def test_P_verified_tool_alternative_preserves_provenance_without_user_only_accusation():
    history = ('⟦USER⟧\nContact address: a@example.org.\n⟦ASSISTANT · ход 0⟧\n'
               '→ TOOL_CALL locate_record: {"contact":"a@example.org"}\n'
               '← TOOL_RESPONSE locate_record: {"ok":true,"verified":true,"record_id":"R-42"}')
    p = packet('The record_id must come from the user, or from a verified tool result.', current('R-42'), history)
    findings, records = P.check(p)
    assert not mechanical(findings)
    assert records[0]['status'] == 'FOUND' and records[0]['found'][0]['kind'] == 'tool_result'


def test_S_grammar_complete_catalog_requires_explicit_caller_closure():
    p = packet('Dynamic tools may be used.', '→ TOOL_CALL dynamically_registered: {}', closed=False)
    assert S.check(p) and not mechanical(S.check(p))
    p['coverage']['tool_universe_closed'] = True
    proven = mechanical(S.check(p))
    assert len(proven) == 1 and S.recheck(p, proven[0])
    p['coverage']['tool_universe_closed'] = False
    assert not S.recheck(p, proven[0])


def rule(quote, n=1, kind='MAX_TOOL_CALLS_PER_TURN'):
    return dict(type=kind, n=n, quote=quote, condition='', exception='', scope='', subject='agent')


def f_result(policy, proposal):
    p = packet(policy, current('R-1') + '\n' + current('R-2'))
    bound = F.bind(dict(runs=[[proposal], [proposal]]), p['normative_sources'])
    return p, bound, F.check(bound, p['current_targets'])


@pytest.mark.parametrize('policy,quote', [
    ('You may make at most one tool call per turn.\nThis limit does not apply to authenticated users.',
     'You may make at most one tool call per turn.'),
    ('If user unauthenticated:\nGeneral interaction rules:\nYou may make at most one tool call per turn.\n'
     'For authenticated users, no call limit.', 'You may make at most one tool call per turn.'),
    ('You should not report more than one failed tool call per turn.',
     'You should not report more than one failed tool call per turn.'),
    ('It is not true that you may make at most one tool call per turn.',
     'It is not true that you may make at most one tool call per turn.'),
    ('Publication:\nYou may make at most one tool call per turn.',
     'You may make at most one tool call per turn.'),
    ('You may make at most one tool call per turn.\nAdministrators are exempt from this limit.',
     'You may make at most one tool call per turn.'),
    ('You may make at most one tool call per turn.\nThe preceding obligation is waived for this session.',
     'You may make at most one tool call per turn.'),
])
def test_F_agreement_cannot_remove_scope_or_change_regulated_operation(policy, quote):
    assert not mechanical(f_result(policy, rule(quote))[2])


def test_F_substring_quote_cannot_remove_outer_negation():
    quote = 'You may make at most one tool call per turn.'
    assert not mechanical(f_result('It is not true that ' + quote, rule(quote))[2])


@pytest.mark.parametrize('separator', ['\n', '\n\n'])
def test_F_unparsed_modifier_in_another_paragraph_cannot_acquire_code_authority(separator):
    quote = 'You may make at most one tool call per turn.'
    assert not mechanical(f_result(quote + separator + 'Administrators may make unlimited calls.', rule(quote))[2])


def test_F_sibling_normative_document_may_qualify_requirement():
    quote = 'You may make at most one tool call per turn.'
    p, _, findings = f_result(quote, rule(quote))
    assert mechanical(findings)
    p['normative_sources'].append(dict(source_id='q-extra', text='Administrators are exempt from this limit.'))
    bound = F.bind(dict(runs=[[rule(quote)], [rule(quote)]]), p['normative_sources'])
    assert not mechanical(F.check(bound, p['current_targets']))


def test_P_F_admin_exception_with_successful_receipt_is_not_mechanical_violation():
    history = ('⟦USER⟧\nInspect both records. Session S-1.\n⟦ASSISTANT · ход 0⟧\n'
               '→ TOOL_CALL check_session: {"session":"S-1"}\n'
               '← TOOL_RESPONSE check_session: {"ok":true,"administrator":true}')
    cat = CATALOG + '- check_session — Read session privileges.\n    session: string! — Session identifier.\n'
    origin = 'The record_id must come from the user in this input.\nAdministrators are exempt from this requirement.'
    p = packet(origin, current(), history, catalog=cat)
    assert any('administrator' in x['text'] and x['kind'] == 'result' for x in p['history'])
    assert not mechanical(P.check(p)[0])
    quote = 'You may make at most one tool call per turn.'
    p = packet(quote + '\nAdministrators are exempt from this limit.',
               current('R-1') + '\n' + current('R-2'), history, catalog=cat)
    bound = F.bind(dict(runs=[[rule(quote)], [rule(quote)]]), p['normative_sources'])
    assert not mechanical(F.check(bound, p['current_targets']))


@pytest.mark.parametrize('n', [0, 1, 2])
def test_F_nonnegative_bound_is_executed_exactly(n):
    quote = f'You may make at most {n} tool calls per turn.'
    p, _, findings = f_result(quote, rule(quote, n))
    assert len(mechanical(findings)) == (1 if n < 2 else 0)
    for f in mechanical(findings):
        assert F.recheck(p, f)
        source = next(s for s in p['normative_sources'] if s['source_id'] == f['norm']['source_id'])
        source['text'] += '\nThis limit does not apply to this request.'
        assert not F.recheck(p, f)


def test_F_canonical_compound_rule_remains_supported():
    quote = ('You should at most make one tool call at a time, and if you take a tool call, you should not respond '
             'to the user at the same time. If you respond to the user, you should not make a tool call at the same time.')
    assert len(mechanical(f_result(quote, rule(quote))[2])) == 1


@pytest.mark.parametrize('bad', [None, {}, {'type': 'MAX_TOOL_CALLS_PER_TURN', 'n': 1},
                                 rule('You may make at most one tool call per turn.', True),
                                 dict(rule('You may make at most one tool call per turn.'), quote=['bad'])])
def test_F_malformed_proposals_are_diagnostics_not_exceptions(bad):
    bound = F.bind(dict(runs=[[bad], [bad]]), [dict(source_id='q', text='You may make at most one tool call per turn.')])
    assert all(r['status'] == 'DROPPED' and not r['checks']['schema_valid'] for r in bound)
    assert not F.check(bound, [])


def test_F_extract_sends_full_policy_and_new_protocol(monkeypatch):
    quote = 'You may make at most one tool call per turn.'
    text = quote + '\nThis limit does not apply to authenticated users.'
    requests = []
    def fake_call(client, req, attempt, tag):
        requests.append(req)
        return {'content': '{}'}, {'rules': []}, None
    monkeypatch.setattr(F, 'call', fake_call)
    monkeypatch.setattr(F, 'step_record', lambda *args: {})
    ext = F.extract(None, 'model', [dict(source_id='q', text=text)])
    assert ext['protocol_version'] == F.PROTOCOL_VERSION
    assert all('This limit does not apply to authenticated users.' in json.dumps(req, ensure_ascii=False)
               and 'policy_documents' in json.dumps(req) for req in requests)


@pytest.mark.parametrize('role', ['USER', 'TOOL', 'SYSTEM'])
def test_P_S_F_do_not_accuse_nonassistant_current_calls_through_parser(role):
    p = packet('The record_id must come from the user in this input.',
               f'⟦{role}⟧\n' + current())
    # The parser's source actor is authoritative, not the TOOL_CALL token.
    assert not any(t.get('role') == 'assistant' and t['kind'] == 'call' for t in p['current_targets'])
    assert not mechanical(P.check(p)[0])
    assert not mechanical(S.check(p))
    quote = 'You may make at most 0 tool calls per turn.'
    rules = F.bind(dict(runs=[[rule(quote, 0)], [rule(quote, 0)]]), [dict(source_id='q-rule', text=quote)])
    assert not F.check(rules, p['current_targets'])


@pytest.mark.parametrize('role', ['user', 'tool', 'system', None])
def test_P_S_F_packet_adapter_requires_explicit_assistant_actor(role):
    p = packet('The record_id must come from the user in this input.', current())
    assert mechanical(P.check(p)[0])
    p['current_targets'][0]['role'] = role
    assert not P.check(p)[0]
    assert not S.check(p)
    quote = 'You may make at most 0 tool calls per turn.'
    rules = F.bind(dict(runs=[[rule(quote, 0)], [rule(quote, 0)]]), [dict(source_id='q-rule', text=quote)])
    assert not F.check(rules, p['current_targets'])


def test_F_user_prose_is_not_assistant_message_and_recheck_actor_changes_fail():
    quote = 'If you make a tool call, you should not respond to the user at the same time.'
    p = packet(quote, '⟦USER⟧\nPlease inspect it.\n⟦ASSISTANT⟧\n' + current('R-1'))
    bound = F.bind(dict(runs=[[rule(quote, None, 'NO_TEXT_WITH_TOOL_CALL')]] * 2), p['normative_sources'])
    assert not F.check(bound, p['current_targets'])
    p, _, findings = f_result('You may make at most one tool call per turn.',
                             rule('You may make at most one tool call per turn.'))
    assert F.recheck(p, mechanical(findings)[0])
    p['current_targets'][1]['role'] = 'user'
    assert not F.recheck(p, mechanical(findings)[0])


def test_P_and_F_direct_recheck_rejects_unread_policy():
    p = packet('The record_id must come from the user in this input.', current())
    proven = mechanical(P.check(p)[0])[0]
    p['coverage']['unread'] = [dict(category='POLICY', unread_units=1)]
    assert not mechanical(P.check(p)[0])
    assert not P.recheck(p, proven)
    quote = 'You may make at most one tool call per turn.'
    p, _, findings = f_result(quote, rule(quote))
    assert F.recheck(p, mechanical(findings)[0])
    p['coverage']['unread'] = [dict(category='POLICY', unread_units=1)]
    assert not F.recheck(p, mechanical(findings)[0])
