"""Source, parameter, chronology and batch checks; these do not test an LLM."""
import copy
import json

import pytest

from guardian_truth.policy_table_v11 import consent_pair_v2 as c
from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.id_contract import native_target_inventory
from test_policy_table_v11 import store, target


def response(s, t, args=None, kind='CONFIRM'):
    p = c.packet(s, t)
    proposal = [q for q, v in p['spans'].items() if v['purpose'] == 'PROPOSAL']
    reply = [q for q, v in p['spans'].items() if v['purpose'] == 'REPLY']
    args = args if args is not None else {'record_id': 'X', 'amount': 2}
    return {'proposal_source_id': p['proposal_source_id'], 'kind': 'ACTION_REQUEST',
            'plans': [{'tool': t['tool'], 'actor': 'ASSISTANT', 'arguments': args,
                'action_span_ids': proposal, 'bindings': [
                    {'path': path, 'span_ids': proposal} for path, _ in c.leaves(args)],
                'reply_kind': kind if reply else 'NONE', 'reply_span_ids': reply}]}


def fixture(text='Modify record X to amount 2. Confirm?', user='Yes', amount=2):
    s = store('⟦ASSISTANT⟧\n' + text + '\n' +
              ('⟦USER⟧\n' + user + '\n' if user is not None else ''),
              response='→ TOOL_CALL apply_a: ' + json.dumps({'record_id': 'X', 'amount': amount}))
    return s, target(s)


def test_native_target_values_are_hidden_and_do_not_change_request():
    s, t = fixture(amount=999)
    other, ot = fixture(amount=2)
    assert c.request(s, t) == c.request(other, ot)
    assert '999' not in json.dumps(c.packet(s, t))
    assert c.verdict(c.admit(response(s, t), s, t), s, t)['value'] == 'UNRESOLVED'


def test_code_owns_markdown_spans_and_user_block():
    s, t = fixture('**Modify record X to amount 2.**\nDo you confirm?', 'X — yes. Other record Y: no, please.')
    data = response(s, t)
    admitted = c.admit(data, s, t)
    assert admitted['valid']
    assert c.verdict(admitted, s, t)['value'] == 'TRUE'
    assert '**' in c.packet(s, t)['spans'][data['plans'][0]['action_span_ids'][0]]['text']
    bad = copy.deepcopy(data)
    bad['plans'][0]['action_span_ids'] = ['h999.s0']
    assert c.verdict(c.admit(bad, s, t), s, t)['value'] == 'UNRESOLVED'


@pytest.mark.parametrize('kind,want', [('REFUSE', 'FALSE'), ('CONDITIONAL', 'UNRESOLVED'),
                                     ('MODIFY', 'UNRESOLVED'), ('NEW_REQUEST', 'UNRESOLVED')])
def test_scoped_reply_class_is_separate_from_literal_parameter_binding(kind, want):
    s, t = fixture()
    assert c.verdict(c.admit(response(s, t, kind=kind), s, t), s, t)['value'] == want


def test_no_reply_is_not_proof_of_no_older_authorization():
    s, t = fixture(user=None)
    assert c.verdict(c.admit(response(s, t), s, t), s, t)['value'] == 'UNRESOLVED'


def test_user_source_cannot_supply_proposal_values_backwards():
    s, t = fixture(user='Yes, amount 2')
    data = response(s, t)
    p = c.packet(s, t)
    data['plans'][0]['bindings'][1]['span_ids'] = [q for q, v in p['spans'].items() if v['purpose'] == 'REPLY']
    result = c.admit(data, s, t)
    assert result['discarded'][0]['reason'] == 'binding_source_not_before_reply'


def test_numbered_list_item_is_not_numeric_value_evidence():
    s, t = fixture('2. Modify record X to the agreed amount. Confirm?')
    got = c.admit(response(s, t), s, t)
    assert got['discarded'][0]['reason'] == 'leaf_value_not_source_supported'


def test_invalid_unrelated_plan_is_isolated_but_relevant_invalid_plan_blocks():
    s, t = fixture()
    data = response(s, t)
    data['plans'].append({'tool': 'inspect_b', 'unexpected': 'malformed'})
    admitted = c.admit(data, s, t)
    assert len(admitted['plans']) == 1 and len(admitted['discarded']) == 1
    assert c.verdict(admitted, s, t)['value'] == 'TRUE'
    data['plans'][-1]['tool'] = 'apply_a'
    assert c.verdict(c.admit(data, s, t), s, t)['value'] == 'UNRESOLVED'


def test_quoted_whole_user_reply_is_never_authorization():
    s, t = fixture(user='«Yes»')
    assert c.verdict(c.admit(response(s, t), s, t), s, t)['reason'] == 'entire_reply_is_quoted'


def test_stale_admission_is_bound_to_exact_packet():
    s, t = fixture()
    admitted = c.admit(response(s, t), s, t)
    changed, ct = fixture(user='No')
    assert c.verdict(admitted, changed, ct)['reason'] == 'packet_changed_after_admission'


def test_deleted_or_reclassified_proposal_returns_unknown_instead_of_crashing():
    s, t = fixture()
    admitted = c.admit(response(s, t), s, t)
    changed = SourceStore({**s.raw, 'prompt': s.raw['prompt'].replace('⟦ASSISTANT⟧', '⟦USER⟧')})
    assert not c.admit({}, changed, target(changed))['valid']
    assert c.verdict(admitted, changed, target(changed))['value'] == 'UNRESOLVED'


@pytest.mark.parametrize('later', ['⟦USER⟧\nNo, stop.\n', '⟦ASSISTANT⟧\nConfirm again?\n'])
def test_unexamined_later_text_blocks_old_approval(later):
    s, t = fixture()
    admitted = c.admit(response(s, t), s, t)
    changed = SourceStore({**s.raw, 'prompt': s.raw['prompt'] + later})
    ct = target(changed)
    assert c.verdict(admitted, changed, ct)['value'] == 'UNRESOLVED'


def batch(second_amount=4, first_amount=2, repeat=False):
    tools = '[AVAILABLE TOOLS]\n- apply_a — modify record\n    record_id: string!\n    amount: number!\n'
    tools += '- apply_b — modify record\n    record_id: string!\n    amount: number!\n'
    m = 'Modify X to amount 2 using apply_a, and Y to amount 4 using apply_b. Confirm both?'
    first = '→ TOOL_CALL apply_a: ' + json.dumps({'record_id': 'X', 'amount': first_amount}) + '\n'
    s = SourceStore({'prompt': '⟦SYSTEM⟧\nObtain consent.\n' + tools + '⟦ASSISTANT⟧\n' + m + '\n⟦USER⟧\nYes, both.\n',
                     'response': first + (first if repeat else '') + '→ TOOL_CALL apply_b: ' +
                        json.dumps({'record_id': 'Y', 'amount': second_amount})})
    t = native_target_inventory(s)[-1]
    data = response(s, t, {'record_id': 'Y', 'amount': 4})
    sibling = copy.deepcopy(data['plans'][0])
    sibling.update(tool='apply_a', arguments={'record_id': 'X', 'amount': 2})
    data['plans'].append(sibling)
    return s, t, data


def test_two_independently_bound_batch_members_and_consumption():
    s, t, data = batch()
    got = c.verdict(c.admit(data, s, t), s, t)
    assert got['value'] == 'TRUE' and len(got['consumed_batch_members']) == 1
    for kwargs in [{'first_amount': 999}, {'second_amount': 999}, {'repeat': True}]:
        s, t, data = batch(**kwargs)
        assert c.verdict(c.admit(data, s, t), s, t)['value'] == 'UNRESOLVED'


def test_descriptive_read_is_not_an_effect_contract():
    s, t = fixture()
    s = SourceStore({**s.raw, 'response': '→ TOOL_CALL inspect_b: {"record_id":"X"}\n' + s.raw['response']})
    t = native_target_inventory(s)[-1]
    assert c.verdict(c.admit(response(s, t), s, t), s, t)['value'] == 'UNRESOLVED'


def test_required_native_field_missing_and_reported_action_are_not_approval():
    s, t = fixture()
    s = SourceStore({**s.raw, 'response': '→ TOOL_CALL apply_a: {"record_id":"X"}'})
    t = target(s)
    assert c.verdict(c.admit(response(s, t, {'record_id': 'X'}), s, t), s, t)['reason'] == 'required_native_argument_missing'
    s, t = fixture()
    data = response(s, t)
    data['kind'] = 'ACTION_DESCRIPTION'
    assert c.verdict(c.admit(data, s, t), s, t)['value'] == 'UNRESOLVED'
