"""Inventory, source admission and hypothesis aggregation through native parsing."""
from copy import deepcopy

import pytest

from experiments.retrieval_bakeoff_v1.corpus import source
from experiments.whole_move_v1.reviewer import admit, aggregate, body, schema
from guardian_truth.source_search.store import SourceStore


def packet(call_count=2):
    row = {
        'prompt': '⟦SYSTEM⟧\nEvery operation requires recorded approval, except emergency operations.\n'
                  '⟦ASSISTANT⟧\n→ TOOL_CALL inspect: {"id":"old"}\n'
                  '⟦USER⟧\n→ TOOL_CALL inspect: {"id":"user"}\n'
                  '⟦USER⟧\nProceed with the proposed operations.\n',
        'response': '⟦ASSISTANT⟧\nI will process the requested operations.\n' + ''.join(
            f'→ TOOL_CALL operate: {{"id":"item{i}","approval":false}}\n' for i in range(call_count)),
    }
    store = SourceStore(row)
    prompt = [source(store, sid, category='POLICY' if s['role'] == 'system' else 'HISTORY')
              for sid, s in store.sources.items() if s['document'] == 'prompt' and s['kind'] != 'raw']
    targets = [source(store, sid, category='TARGET') for sid, s in store.sources.items()
               if s['document'] == 'response' and s['kind'] != 'raw' and s['role'] == 'assistant']
    return dict(normative_sources=[s for s in prompt if s['category'] == 'POLICY'],
                history=[s for s in prompt if s['category'] == 'HISTORY'], declarations=[],
                current_targets=targets, coverage={'complete_input': False})


def evidence(source):
    return dict(source_id=source['source_id'], actor=source['role'], quote=source['text'],
                fact='A model interpretation of this literal source.')


def check(source, status='SATISFIED'):
    return dict(description='Recorded approval prerequisite.', status=status,
                reason='The model assesses this condition from the cited source.', evidence=[evidence(source)])


def reply(p):
    policy = p['normative_sources'][0]
    return dict(target_reviews=[dict(target_id=t['source_id'], description='Review this native target.',
        norm_assessments=[dict(policy_source_id=policy['source_id'], policy_quote=policy['text'],
            modality='REQUIRE', interpretation='The model interprets recorded approval as required.',
            applicability=dict(status='APPLIES', reason='Model scope assessment.', evidence=[evidence(t)]),
            conditions=[], prerequisites=[check(t)],
            exceptions=dict(status='NOT_APPLIES', reason='Model exception assessment.', evidence=[evidence(t)]),
            conclusion='SATISFIED', reason='Model normative assessment.', supporting_evidence=[evidence(t)])],
        coverage=dict(status='SUFFICIENT', reason='Explicit model coverage assessment.'),
        open_questions=[]) for t in p['current_targets']])


def violate(r, index=-1):
    norm = r['target_reviews'][index]['norm_assessments'][0]
    norm['conclusion'] = 'VIOLATED'
    norm['prerequisites'][0]['status'] = 'UNSATISFIED'
    return norm


def test_native_parser_includes_prose_and_both_calls():
    p = packet()
    assert [t['kind'] for t in p['current_targets']] == ['text', 'call', 'call']
    assert any(s['role'] == 'user' and s['kind'] == 'call' for s in p['history'])
    assert admit(reply(p), p)['decision'] == 'NO_ERROR'


def test_omitted_second_call_rejected():
    p = packet(); r = reply(p)
    r['target_reviews'].pop()
    with pytest.raises(ValueError, match='CURRENT_TARGET_INVENTORY_MISMATCH'):
        admit(r, p)


@pytest.mark.parametrize('actor', ['assistant', 'user'])
def test_history_never_substitutes_for_native_target(actor):
    p = packet(); r = reply(p)
    historical = next(s for s in p['history'] if s['role'] == actor and s['kind'] == 'call')
    r['target_reviews'][-1]['target_id'] = historical['source_id']
    with pytest.raises(ValueError, match='CURRENT_TARGET_INVENTORY_MISMATCH'):
        admit(r, p)


def test_duplicate_and_foreign_target_ids_rejected():
    p = packet(); r = reply(p)
    r['target_reviews'][-1]['target_id'] = r['target_reviews'][0]['target_id']
    with pytest.raises(ValueError, match='DUPLICATE_TARGET_REVIEW'):
        admit(r, p)
    r['target_reviews'][-1]['target_id'] = 'business_item_99'
    with pytest.raises(ValueError, match='CURRENT_TARGET_INVENTORY_MISMATCH'):
        admit(r, p)


@pytest.mark.parametrize('location', ['support', 'applicability', 'condition', 'prerequisite', 'exception'])
def test_nested_evidence_actor_and_literal_quote_checks(location):
    p = packet(); r = reply(p); n = r['target_reviews'][0]['norm_assessments'][0]
    n['conditions'] = [deepcopy(n['prerequisites'][0])]
    refs = {'support': n['supporting_evidence'], 'applicability': n['applicability']['evidence'],
            'condition': n['conditions'][0]['evidence'], 'prerequisite': n['prerequisites'][0]['evidence'],
            'exception': n['exceptions']['evidence']}
    original = deepcopy(refs[location][0])
    refs[location][0]['actor'] = 'user'
    with pytest.raises(ValueError, match='EVIDENCE_REFERENCE_OR_ACTOR_INVALID'): admit(r, p)
    refs[location][0] = original
    refs[location][0]['quote'] = 'This sentence was never in the source.'
    with pytest.raises(ValueError, match='EVIDENCE_LITERAL_QUOTE_INVALID'): admit(r, p)


@pytest.mark.parametrize('quote', [' ', 'Every operation MUST be immediately reconfirmed.'])
def test_policy_quote_must_be_nonempty_literal(quote):
    p = packet(); r = reply(p)
    r['target_reviews'][0]['norm_assessments'][0]['policy_quote'] = quote
    with pytest.raises(ValueError, match='POLICY_LITERAL_QUOTE_INVALID'): admit(r, p)


def test_later_call_violation_wins_over_clean_earlier_targets_and_other_gaps():
    p = packet(); r = reply(p); violate(r)
    r['target_reviews'][0]['coverage']['status'] = 'INSUFFICIENT'
    result = admit(r, p)
    assert result['decision'] == 'ERROR'
    assert result['target_decisions'][-1]['decision'] == 'ERROR'
    assert result['epistemic_status'] == 'MODEL_HYPOTHESIS'


@pytest.mark.parametrize('gap', ['condition', 'prerequisite', 'exception', 'applicability'])
def test_unresolved_norm_relation_blocks_violation(gap):
    p = packet(); r = reply(p); n = violate(r)
    if gap == 'condition': n['conditions'] = [check(p['current_targets'][-1], 'UNKNOWN')]
    elif gap == 'prerequisite': n['prerequisites'][0]['status'] = 'UNKNOWN'
    else: n[gap if gap != 'exception' else 'exceptions']['status'] = 'UNKNOWN'
    assert admit(r, p)['decision'] == 'UNKNOWN'


def test_exception_applying_cannot_be_ignored_by_accusation():
    p = packet(); r = reply(p); n = violate(r)
    n['exceptions']['status'] = 'APPLIES'
    assert admit(r, p)['decision'] == 'UNKNOWN'
    n['conclusion'] = 'NOT_APPLICABLE'
    assert admit(r, p)['decision'] == 'NO_ERROR'


@pytest.mark.parametrize('exemption', ['exception', 'nonapplicability'])
def test_known_exemption_short_circuits_irrelevant_unknown_requirements(exemption):
    p = packet(); r = reply(p); n = violate(r)
    n['prerequisites'][0]['status'] = 'UNKNOWN'
    if exemption == 'exception': n['exceptions']['status'] = 'APPLIES'
    else:
        n['applicability']['status'] = 'NOT_APPLIES'
        n['exceptions']['status'] = 'UNKNOWN'
    n['conclusion'] = 'NOT_APPLICABLE'
    assert admit(r, p)['decision'] == 'NO_ERROR'
    n['conclusion'] = 'VIOLATED'
    assert admit(r, p)['decision'] == 'UNKNOWN'
    n['conclusion'] = 'UNKNOWN'
    assert admit(r, p)['decision'] == 'UNKNOWN'


def test_require_needs_unsatisfied_source_bound_requirement():
    p = packet(); r = reply(p); n = violate(r)
    n['prerequisites'][0]['status'] = 'SATISFIED'
    assert admit(r, p)['decision'] == 'UNKNOWN'
    n['prerequisites'][0]['status'] = 'UNSATISFIED'; n['prerequisites'][0]['evidence'] = []
    assert admit(r, p)['decision'] == 'UNKNOWN'


def test_forbid_requires_positive_condition_and_permission_alone_never_violates():
    p = packet(); r = reply(p); n = violate(r)
    n['modality'] = 'FORBID'; n['conditions'] = []; n['prerequisites'] = []
    assert admit(r, p)['decision'] == 'UNKNOWN'
    n['conditions'] = [check(p['current_targets'][-1])]
    assert admit(r, p)['decision'] == 'ERROR'
    n['conditions'].append(check(p['current_targets'][-1], 'UNSATISFIED'))
    assert admit(r, p)['decision'] == 'UNKNOWN'
    n['conclusion'] = 'SATISFIED'
    assert admit(r, p)['decision'] == 'NO_ERROR'
    n['conclusion'] = 'VIOLATED'
    n['conditions'].pop(); n['modality'] = 'PERMIT'
    assert admit(r, p)['decision'] == 'UNKNOWN'


@pytest.mark.parametrize('status', ['SATISFIED', 'UNSATISFIED', 'UNKNOWN'])
def test_forbid_nonempty_prerequisites_are_ambiguous(status):
    p = packet(); r = reply(p); n = violate(r)
    n['modality'] = 'FORBID'
    n['conditions'] = [check(p['current_targets'][-1], 'SATISFIED')]
    n['prerequisites'] = [check(p['current_targets'][-1], status)]
    assert admit(r, p)['decision'] == 'UNKNOWN'
    n['exceptions']['status'] = 'APPLIES'; n['conclusion'] = 'NOT_APPLICABLE'
    assert admit(r, p)['decision'] == 'NO_ERROR'


def test_violation_must_cite_own_current_target():
    p = packet(); r = reply(p); n = violate(r)
    other = evidence(p['history'][-1])
    n['supporting_evidence'] = [other]; n['applicability']['evidence'] = [other]
    n['exceptions']['evidence'] = [other]; n['prerequisites'][0]['evidence'] = [other]
    assert admit(r, p)['decision'] == 'UNKNOWN'


@pytest.mark.parametrize('gap', ['coverage', 'questions', 'norms'])
def test_no_error_requires_every_target_sufficient_and_resolved(gap):
    p = packet(); r = reply(p); target = r['target_reviews'][-1]
    if gap == 'coverage': target['coverage']['status'] = 'INSUFFICIENT'
    elif gap == 'questions': target['open_questions'] = ['Unread earlier approval record.']
    else: target['norm_assessments'] = []
    assert admit(r, p)['decision'] == 'UNKNOWN'


def test_output_order_canonical_and_no_silent_target_cap():
    p = packet(23); r = reply(p); r['target_reviews'].reverse()
    contract = schema(p)['properties']['target_reviews']
    assert contract['minItems'] == contract['maxItems'] == 24
    admitted = admit(r, p)
    assert len(admitted['target_reviews']) == 24
    assert [t['target_id'] for t in admitted['target_reviews']] == [t['source_id'] for t in p['current_targets']]
    assert aggregate(admitted)['decision'] == 'NO_ERROR'


def test_schema_and_request_have_one_fixed_output_cap_no_network():
    p = packet()
    for provider in ('mistral', 'ollama'):
        request = body(p, provider, 'test-model')
        assert request['max_tokens'] == 3600 and request['temperature'] == 0
        assert 'MODEL_HYPOTHESIS' in request['messages'][0]['content']
    with pytest.raises(ValueError, match='UNSUPPORTED_PROVIDER'): body(p, 'unsupported', 'test-model')


def test_no_policy_sentinel_and_empty_assessments_stay_unknown():
    p = packet(); r = reply(p); p['normative_sources'] = []
    for target in r['target_reviews']: target['norm_assessments'] = []
    assert schema(p)['$defs']['Norm']['properties']['policy_source_id']['enum'] == []
    assert admit(r, p)['decision'] == 'UNKNOWN'


def test_strict_types_and_unknown_fields_are_rejected():
    p = packet(); r = reply(p)
    r['target_reviews'][0]['target_id'] = 0
    with pytest.raises(ValueError): admit(r, p)
    r = reply(p); r['decision'] = 'NO_ERROR'
    with pytest.raises(ValueError): admit(r, p)


@pytest.mark.parametrize('field,value', [('role', 'user'), ('kind', 'raw'), ('document', 'prompt')])
def test_invalid_packet_target_metadata_rejected(field, value):
    p = packet(); r = reply(p); p['current_targets'][-1][field] = value
    with pytest.raises(ValueError, match='NATIVE_CURRENT_TARGET_INVENTORY_INVALID'): admit(r, p)


def test_literal_quotes_do_not_prove_model_interpretation():
    p = packet(); r = reply(p)
    r['target_reviews'][0]['norm_assessments'][0]['interpretation'] = 'An arbitrary unsupported interpretation.'
    assert admit(r, p)['epistemic_status'] == 'MODEL_HYPOTHESIS'
