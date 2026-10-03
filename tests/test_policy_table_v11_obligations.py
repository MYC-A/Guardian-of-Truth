import copy
import pytest
from test_policy_table_v11 import store, policy, target, atomic, comparison
from guardian_truth.policy_table_v11.obligations import admit_ledger, admit_lowerings, extraction_request
from guardian_truth.policy_table_v11.compile import canonical
from guardian_truth.policy_table_v11.evaluate import evaluate_atom
from guardian_truth.policy_table_v11.schema import Expression


def sample():
    p = policy(store(policy='Before apply_a amount must be 2.'))
    text = p['clauses'][0]['text']
    response = {'clauses': [{'clause_id': 'clause_0', 'status': 'APPLICABLE', 'reason': 'The clause governs the selected action.',
        'obligations': [{'id': 'o1', 'spans': [{'clause_id': 'clause_0', 'quote': text}],
            'description': 'Amount must be 2 before this action.', 'applies_when': 'UNCONDITIONAL', 'exceptions': 'NONE'}]}]}
    return p, response


def test_obligations_kept_before_DSL_and_source_spans_exact():
    p, raw = sample(); result = admit_ledger(raw, p)
    assert result['valid'] and len(result['obligations']) == 1
    assert result['obligations'][0]['source_spans'][0]['start'] == 0
    assert not result['semantic_completeness_proven']
    before = copy.deepcopy(p); extraction_request(p, {'kind': 'TOOL_CALL', 'tool': 'apply_a'})
    assert p == before


@pytest.mark.parametrize('edit,reason', [('missing_clause', 'clause_disposition_missing'),
    ('duplicate_clause', 'duplicate_clause_disposition'), ('paraphrase', 'quotation_absent_or_ambiguous'),
    ('lost_obligation', 'invalid_applicability_inventory'), ('duplicate_obligation', 'duplicate_obligation_id')])
def test_ledger_admission_quarantines_bad_items_without_dropping_the_group(edit, reason):
    p, raw = sample()
    if edit == 'missing_clause': raw['clauses'] = []
    elif edit == 'duplicate_clause': raw['clauses'] *= 2
    elif edit == 'paraphrase': raw['clauses'][0]['obligations'][0]['spans'][0]['quote'] = 'My own interpretation'
    elif edit == 'lost_obligation': raw['clauses'][0]['obligations'] = []
    else: raw['clauses'][0]['obligations'] *= 2
    got = admit_ledger(raw, p)
    assert got['valid'] and reason in {q['reason'] for q in got['quarantined']}
    if edit in ('missing_clause', 'lost_obligation', 'paraphrase'): assert got['obligations'] == []
    if edit in ('duplicate_clause', 'duplicate_obligation'): assert len(got['obligations']) == 1


def test_one_bad_quote_does_not_drop_sibling_rules():
    p, raw = sample()
    p['clauses'].append({'id': 'clause_1', 'text': 'Never  apply_a when “blocked”.'})
    good = {'id': 'o2', 'spans': [{'clause_id': 'clause_1', 'quote': 'Never apply_a when "blocked".'}],
            'description': 'Blocked state forbids the action.', 'applies_when': 'UNCONDITIONAL', 'exceptions': 'NONE'}
    bad = {**good, 'id': 'o3', 'spans': [{'clause_id': 'clause_1', 'quote': 'paraphrased rule'}]}
    raw['clauses'].append({'clause_id': 'clause_1', 'status': 'APPLICABLE', 'reason': 'Governs it.', 'obligations': [good, bad]})
    got = admit_ledger(raw, p)
    assert {o['id'] for o in got['obligations']} == {'o1', 'o2'}
    assert [q['obligation_id'] for q in got['quarantined']] == ['o3']
    assert got['obligations'][1]['source_spans'][0]['conversion'] == 'WHITESPACE_AND_GLYPHS'


def test_invalid_envelope_is_the_only_all_or_nothing_failure():
    p, _ = sample()
    assert not admit_ledger({'oops': []}, p)['valid']
    assert not admit_ledger('not json', p)['valid']


@pytest.mark.parametrize('status', ['UNSUPPORTED', 'AMBIGUOUS'])
def test_unrepresentable_is_not_absence_of_requirement(status):
    p, raw = sample(); ledger = admit_ledger(raw, p)
    response = {'lowerings': [{'obligation_id': 'o1', 'status': status, 'reason': 'No trusted predicate exists.', 'atom': None}]}
    admitted = admit_lowerings(response, ledger, p, {'kind': 'TOOL_CALL', 'tool': 'apply_a'})
    assert admitted['valid'] and admitted['obligations'] == 1 and admitted['compiled'] == 0
    assert admitted[status.lower()] == 1 and admitted['dispositions'][0]['status'] == status


def test_unified_requirement_compiles_and_empty_lowering_is_invalid():
    p, raw = sample(); ledger = admit_ledger(raw, p)
    response = {'lowerings': [{'obligation_id': 'o1', 'status': 'COMPILED', 'reason': 'Direct numeric policy constant.',
        'atom': {'polarity': 'REQUIRED', 'requirement': comparison(value=2), 'guard': None, 'exceptions': [], 'clause_ids': ['clause_0']}}]}
    assert admit_lowerings(response, ledger, p, {'kind': 'TOOL_CALL', 'tool': 'apply_a'})['compiled'] == 1
    empty = admit_lowerings({'lowerings': []}, ledger, p, {'kind': 'TOOL_CALL', 'tool': 'apply_a'})
    assert empty['compiled'] == 0 and empty['missing'] == 1 and not empty['inventory_complete']
    assert empty['dispositions'][0]['rejection'] == 'lowering_missing'


@pytest.mark.parametrize('amount,expected', [(2, 'TRUE'), (9, 'FALSE')])
def test_applicability_guard_is_separate_from_requirement(amount, expected):
    s = store(response='→ TOOL_CALL apply_a: {"record_id":"X","amount":' + str(amount) + '}')
    a = atomic(modality='REQUIRES', confirmation=None, condition=comparison(value=7))
    a.guard = Expression.model_validate(comparison(value=2))
    result = evaluate_atom(s, a, target(s))
    assert result['guard_value'] == expected and result['finding'] is (amount == 2)
    a.guard = Expression.model_validate(comparison('args.missing', value=2))
    assert not evaluate_atom(s, a, target(s))['finding']


def test_different_applicability_never_agrees_even_for_same_necessary_state():
    s = store(); p = policy(s); trigger = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}
    a = atomic(modality='REQUIRES', confirmation=None, condition=comparison(value=7))
    b = a.model_copy(deep=True); b.guard = Expression.model_validate(comparison(value=2))
    assert canonical(p['policy_sha256'], trigger, a) != canonical(p['policy_sha256'], trigger, b)


def test_chunk_output_inventory_retains_full_source_context():
    p, raw = sample()
    p['clauses'].append({'id': 'clause_1', 'text': 'Shared condition also applies.'})
    raw['clauses'][0]['obligations'][0]['spans'].append({'clause_id': 'clause_1', 'quote': 'Shared condition also applies.'})
    assert admit_ledger(raw, p, ['clause_0'])['inventory_complete']
    assert not admit_ledger(raw, p)['inventory_complete']  # Full inventory still demands the other disposition.
    messages = extraction_request(p, {'kind': 'TOOL_CALL', 'tool': 'apply_a'}, ['clause_0'])
    assert 'Shared condition also applies.' in messages[1]['content']


def test_scope_prevents_dialogue_obligation_from_argument_proxy_lowering():
    p, raw = sample(); raw['clauses'][0]['obligations'][0]['required_scopes'] = ['DIALOGUE_STATE']
    ledger = admit_ledger(raw, p)
    response = {'lowerings': [{'obligation_id': 'o1', 'status': 'COMPILED', 'reason': 'Wrong proxy',
        'atom': {'polarity': 'REQUIRED', 'requirement': comparison(value=2), 'guard': None, 'exceptions': [], 'clause_ids': ['clause_0']}}]}
    got=admit_lowerings(response,ledger,p,{'kind':'TOOL_CALL','tool':'apply_a'})
    assert got['compiled']==0 and got['rejected']==1
    assert 'evidence_scope_missing' in got['dispositions'][0]['rejection']


def test_NA_missing_empty_list_losslessly_defaults_but_applicable_does_not():
    p,raw=sample()
    raw['clauses'][0].update(status='NOT_APPLICABLE'); raw['clauses'][0].pop('obligations')
    assert admit_ledger(raw,p)['valid']
    raw['clauses'][0]['status']='APPLICABLE'
    got=admit_ledger(raw,p)
    assert not got['inventory_complete'] and got['quarantined'][0]['level']=='clause'


def test_argument_presence_cannot_stand_in_for_dialogue_obligation():
    p, raw = sample()
    raw['clauses'][0]['obligations'][0]['description'] = 'The user must explicitly confirm before this action.'
    ledger = admit_ledger(raw, p)
    response = {'lowerings': [{'obligation_id': 'o1', 'status': 'COMPILED', 'reason': 'proxy',
        'atom': {'polarity': 'REQUIRED', 'requirement': comparison(value=2), 'guard': None, 'exceptions': [], 'clause_ids': ['clause_0']}}]}
    got = admit_lowerings(response, ledger, p, {'kind': 'TOOL_CALL', 'tool': 'apply_a'})
    assert got['compiled'] == 0 and 'DIALOGUE_STATE' in got['dispositions'][0]['rejection']
