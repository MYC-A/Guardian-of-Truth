"""Blind-source and output-recovery boundaries through the public predictor.

Static receipts exercise contracts, not model quality or token-time estimates.
"""
from copy import deepcopy
import json

import pytest

from experiments.guardian_semantic import variants as V
from guardian_truth.integrated.transport import sha
from guardian_truth.submission import blind_compact as B
from guardian_truth.submission.cli import MODEL, predict_one
from guardian_truth.verification.common import schema_errors


class NoLayers:
    def findings(self, row):
        return dict(findings=[])


def row(response='Hello.'):
    return dict(id='ALIGNMENT_ONLY', prompt='⟦SYSTEM⟧\nNever write FORBIDDEN unless the user requests a quotation.\n'
                '⟦USER⟧\nPlease greet me.\n⟦ASSISTANT · ход 1⟧\nI will greet you.\n⟦USER⟧\nProceed.',
                response='⟦ASSISTANT⟧\n' + response)


class Client:
    model = MODEL

    def __init__(self, pre_failure=None, primary='NO_ERROR', review_failure=None, include_requirement=False):
        self.pre_failure, self.primary, self.review_failure = pre_failure, primary, review_failure
        self.include_requirement, self.calls = include_requirement, []

    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(request=deepcopy(request), attempt=attempt, tag=tag))
        receipt = dict(key=sha(dict(request=request, attempt=attempt)), transport=dict(status=200),
                       finish_reason='stop', cached=False, usage={})
        p = json.loads(request['messages'][1]['content'])
        if tag == 'pre_blind':
            if self.pre_failure == 'exception':
                raise RuntimeError('Optional pre-pass failed')
            if self.pre_failure == 'json':
                return dict(receipt, content='{"requirements":[')
            if self.pre_failure == 'transport':
                return dict(receipt, transport=dict(status=429), content=None)
            value = dict(requirements=[], entities=[], computed_values=[], expected_actions=[], uncertainties=[])
            if request['response_format']['json_schema']['name'] == 'blind_compact_v1':
                unit = p['normative_sources'][0]['units'][0]['unit_id']
                evidence = [p['history'][0]['source_id']] if p['history'] else []
                if self.include_requirement or self.pre_failure in ('unknown_norm', 'unknown_evidence'):
                    value['requirements'] = [dict(norm_id='invented-unit' if self.pre_failure == 'unknown_norm' else unit,
                        scope='An assistant writes the forbidden word without a requested quotation.',
                        state='UNCERTAIN', evidence=['invented-source'] if self.pre_failure == 'unknown_evidence' else evidence,
                        note='The future action remains hidden; check the quotation exception.')]
            return dict(receipt, content=json.dumps(value))
        assert tag == 'review', 'Unexpected extra inference request: ' + tag
        if self.review_failure == 'empty':
            return dict(receipt, content=None)
        target = p['current_targets'][0]['source_id']
        value = dict(decision=self.primary, regulated_action=dict(target_id=target, description='Current prose'),
            applicable_norms=[dict(policy_source_id=p['normative_sources'][0]['source_id'],
                                  interpretation='Never write FORBIDDEN unless quoted at user request.', modality='FORBID')]
                              if self.primary == 'ERROR' else [],
            supporting_evidence=[dict(source_id=target, actor='assistant', role='current prose', fact='FORBIDDEN')]
                                  if self.primary == 'ERROR' else [],
            exception_analysis='No quotation was requested.', reason='Current move assessed.', open_questions=[])
        if self.review_failure == 'reference':
            value['regulated_action']['target_id'] = 'invented-target'
        return dict(receipt, content=json.dumps(value))


@pytest.mark.parametrize('profile', B.PROFILES)
def test_current_values_and_prose_cannot_change_blind_request(profile):
    original = row('CURRENT_SECRET_A amount=A123.')
    alternative = row('CURRENT_SECRET_B amount=B999. Different prose.')
    first, second = Client(), Client()
    before = deepcopy(original)
    predict_one(original, first, NoLayers(), pre_profile=profile)
    predict_one(alternative, second, NoLayers(), pre_profile=profile)
    pre1 = next(c for c in first.calls if c['tag'] == 'pre_blind')
    pre2 = next(c for c in second.calls if c['tag'] == 'pre_blind')
    assert pre1 == pre2
    wire = json.dumps(pre1['request'], ensure_ascii=False)
    assert 'CURRENT_SECRET_' not in wire and 'A123' not in wire and 'B999' not in wire
    assert 'current_targets' not in json.loads(pre1['request']['messages'][1]['content'])
    assert original == before


@pytest.mark.parametrize('split_word', ['NOT', 'unless'])
def test_policy_chunks_preserve_cross_boundary_negation_and_exception(split_word):
    policy = 'You must NOT change the record\r\nunless the owner explicitly requests it. Ω'
    blind, _ = V.neutral_view(dict(prompt='⟦SYSTEM⟧\n' + policy), 20000)
    before = deepcopy(blind)
    source = blind['normative_sources'][0]
    width = source['text'].index(split_word) + 1
    view, units = B.compact_view(blind, width=width)
    parts = view['normative_sources'][0]['units']
    rebuilt = ''.join(p['text'] for p in parts)
    assert rebuilt == source['text'] and policy in rebuilt
    assert parts[0]['text'].endswith(split_word[0])
    assert parts[1]['text'].startswith(split_word[1:])
    for uid, addressed in units.items():
        assert addressed['source_id'] == source['source_id']
        assert source['text'][addressed['start']:addressed['end']] == addressed['text']
    assert blind == before
    assert view['history'] == blind['history'] and view['coverage'] == blind['coverage']


def test_compact_norms_reference_only_norm_units_and_evidence_only_inventory():
    blind, _ = V.neutral_view(row(), 20000)
    _, units = B.compact_view(blind)
    schema = B.analysis_schema(blind, units)
    norm_ids = schema['properties']['requirements']['items']['properties']['norm_id']['enum']
    evidence_ids = schema['properties']['requirements']['items']['properties']['evidence']['items']['enum']
    assert set(norm_ids) == set(units)
    assert all(u['source_id'] in {s['source_id'] for s in blind['normative_sources']} for u in units.values())
    assert set(evidence_ids) == {s['source_id'] for cat in B.CATEGORIES for s in blind.get(cat, [])}
    value = dict(requirements=[dict(norm_id=norm_ids[0], scope='A future forbidden assertion.', state='UNCERTAIN',
                 evidence=[evidence_ids[-1]], note='Scope must be checked.')], entities=[], computed_values=[],
                 expected_actions=[], uncertainties=[])
    assert not schema_errors(value, schema)
    for field, invalid in [('norm_id', evidence_ids[-1]), ('evidence', ['invented-source'])]:
        changed = deepcopy(value)
        changed['requirements'][0][field] = invalid
        assert schema_errors(changed, schema)


def test_empty_inventories_cannot_certify_placeholder_addresses():
    empty = {category: [] for category in B.CATEGORIES}
    schema = B.analysis_schema(empty, {})
    valid = dict(requirements=[], entities=[], computed_values=[], expected_actions=[], uncertainties=[])
    assert not schema_errors(valid, schema)
    invented_norm = dict(valid, requirements=[dict(norm_id='NO_NORM', scope='Invented norm', state='YES',
                                                  evidence=[], note='Not an actual source.')])
    invented_source = dict(valid, entities=[dict(refers_to='Invented object', identifier='x',
                                                 owner_or_relation='Invented owner', source_id='NO_SOURCE')])
    assert schema_errors(invented_norm, schema)
    assert schema_errors(invented_source, schema)


def alias_views():
    source = dict(source_id='h3', role='user', kind='text', event=3, tool=None,
                  text='Yes, only for this record.', future_metadata=dict(scope='bounded'))
    ordinary = dict(normative_sources=[], declarations=[], history=[source], coverage=dict(unread=['h7']))
    blind = deepcopy(ordinary)
    blind['history'][0]['source_id'] = 'blind:h3'
    blind['history'].append(dict(source_id='blind:h7', role='tool', kind='result', event=7, tool='lookup',
                                text='Additional prompt-only source.', future_metadata={}))
    return ordinary, blind


def test_alias_is_lossless_inverse_preserves_unmatched_sources_and_coverage():
    ordinary, blind = alias_views()
    before = deepcopy((ordinary, blind))
    packed, aliases = B.deduplicate_sources(ordinary, blind)
    assert aliases == {'blind:h3': 'h3'}
    assert packed['history'][0]['text_ref'] == 'h3' and 'text' not in packed['history'][0]
    assert packed['history'][1] == blind['history'][1]
    assert packed['coverage'] == blind['coverage']
    assert B.expand_sources(ordinary, packed) == blind
    assert (ordinary, blind) == before
    packed['history'][0]['event'] = 99
    with pytest.raises(ValueError, match='METADATA_DISAGREEMENT'):
        B.expand_sources(ordinary, packed)


@pytest.mark.parametrize('field,value', [('role', 'assistant'), ('event', 4), ('kind', 'result'),
                                      ('tool', 'different'), ('future_metadata', dict(scope='global'))])
def test_equal_text_is_not_alias_across_changed_source_metadata(field, value):
    ordinary, blind = alias_views()
    blind['history'][0][field] = value
    packed, aliases = B.deduplicate_sources(ordinary, blind)
    assert aliases == {} and packed == blind


def test_equal_text_in_other_source_category_is_not_an_alias():
    ordinary, blind = alias_views()
    blind['declarations'] = [blind['history'].pop(0)]
    packed, aliases = B.deduplicate_sources(ordinary, blind)
    assert aliases == {} and packed == blind


@pytest.mark.parametrize('event', [None, -1, True, '3'])
def test_alias_requires_real_nonnegative_integer_event(event):
    ordinary, blind = alias_views()
    ordinary['history'][0]['event'] = blind['history'][0]['event'] = event
    packed, aliases = B.deduplicate_sources(ordinary, blind)
    assert aliases == {} and packed == blind


def test_alias_metadata_boolean_and_integer_remain_different():
    ordinary, blind = alias_views()
    ordinary['history'][0]['future_metadata'] = dict(success=True)
    blind['history'][0]['future_metadata'] = dict(success=1)
    packed, aliases = B.deduplicate_sources(ordinary, blind)
    assert aliases == {} and packed == blind


def test_equal_value_events_keep_separate_identities_and_order():
    ordinary, blind = alias_views()
    second = dict(deepcopy(ordinary['history'][0]), source_id='h4', event=4)
    ordinary['history'].append(second)
    blind['history'].insert(1, dict(deepcopy(second), source_id='blind:h4'))
    packed, aliases = B.deduplicate_sources(ordinary, blind)
    assert aliases == {'blind:h3': 'h3', 'blind:h4': 'h4'}
    assert [s['source_id'] for s in packed['history']] == ['blind:h3', 'blind:h4', 'blind:h7']
    assert [s['event'] for s in packed['history']] == [3, 4, 7]
    assert B.expand_sources(ordinary, packed) == blind


def test_inverse_rejects_alias_with_conflicting_literal_text():
    ordinary, blind = alias_views()
    packed, _ = B.deduplicate_sources(ordinary, blind)
    packed['history'][0]['text'] = 'No, I revoked that permission.'
    with pytest.raises(ValueError, match='AMBIGUOUS_SOURCE_ALIAS'):
        B.expand_sources(ordinary, packed)


@pytest.mark.parametrize('failure', ['json', 'transport', 'exception', 'unknown_norm', 'unknown_evidence'])
@pytest.mark.parametrize('primary,review_failure,binary,mode', [
    ('NO_ERROR', None, 0, None), ('ERROR', None, 1, None),
    ('ERROR', 'reference', 1, 'RAW_MODEL_DECISION'), ('NO_ERROR', 'empty', 0, 'DEFAULT_ZERO'),
])
def test_invalid_optional_prepass_preserves_base_reviewer_and_binary_recovery(failure, primary, review_failure, binary, mode):
    input_row = row('FORBIDDEN' if primary == 'ERROR' else 'Hello.')
    client = Client(failure, primary, review_failure)
    trace = predict_one(input_row, client, NoLayers(), pre_profile='compact')
    reference = Client('json', primary, review_failure)
    predict_one(input_row, reference, NoLayers(), pre_profile='legacy')
    reviews = [c for c in client.calls if c['tag'] == 'review']
    assert len(reviews) == 1
    assert reviews == [c for c in reference.calls if c['tag'] == 'review']
    assert trace['binary'] == binary
    assert all(not s.get('injected') for s in trace['pre_steps'])
    if mode is None:
        assert 'output_recovery' not in trace
    else:
        assert trace['output_recovery']['mode'] == mode and trace['accusation'] is None


@pytest.mark.parametrize('profile', ['dedup', 'compact'])
def test_compaction_exception_preserves_unchanged_reviewer_without_retry(monkeypatch, profile):
    def broken(*args, **kwargs):
        raise RuntimeError('packing failed')
    monkeypatch.setattr(B, 'deduplicate_request', broken)
    client = Client(primary='ERROR', include_requirement=True)
    trace = predict_one(row('FORBIDDEN'), client, NoLayers(), pre_profile=profile)
    base = Client('json', primary='ERROR')
    predict_one(row('FORBIDDEN'), base, NoLayers())
    assert [c for c in client.calls if c['tag'] == 'review'] == [c for c in base.calls if c['tag'] == 'review']
    assert trace['binary'] == 1 and 'output_recovery' not in trace
    assert any(s.get('fallback') == 'UNCHANGED_BASE_REVIEW' for s in trace['pre_steps'])


@pytest.mark.parametrize('profile', ['dedup', 'compact'])
def test_valid_preparation_retains_positive_and_hypothesis_authority(profile):
    client = Client(primary='ERROR', include_requirement=True)
    trace = predict_one(row('FORBIDDEN'), client, NoLayers(), pre_profile=profile)
    assert trace['binary'] == 1 and 'output_recovery' not in trace
    assert len([c for c in client.calls if c['tag'] == 'review']) == 1
    review = next(c['request'] for c in client.calls if c['tag'] == 'review')
    p = json.loads(review['messages'][1]['content'])
    assert 'blind_analysis' in p
    step = next(s for s in trace['pre_steps'] if s.get('injected'))
    assert step['source_compaction']['authority'] == 'MODEL_HYPOTHESIS'
    assert step['source_compaction']['final_citation_scope'] == 'ORDINARY_PACKET_ONLY'
    assert p['current_targets'][0]['source_id'] == trace['rec']['A_adm2']['target_id']
    unchanged = Client('json', primary='ERROR')
    predict_one(row('FORBIDDEN'), unchanged, NoLayers())
    baseline = next(c['request'] for c in unchanged.calls if c['tag'] == 'review')
    ordinary = {k: v for k, v in p.items() if k not in ('blind_analysis', 'blind_analysis_sources', 'blind_norm_units')}
    assert ordinary == json.loads(baseline['messages'][1]['content'])
    assert review['response_format'] == baseline['response_format']
    assert review['temperature'] == baseline['temperature']
    assert len(client.calls) == 2
    if profile == 'compact':
        assert set(p['blind_norm_units']) == {r['norm_id'] for r in p['blind_analysis']['requirements']}
        assert next(c for c in client.calls if c['tag'] == 'pre_blind')['request']['max_tokens'] == 1700
    assert review['max_tokens'] == 1700
