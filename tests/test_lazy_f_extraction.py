"""Capability-only F gating, with production parser and unchanged bound rules."""
from copy import deepcopy
import json

import pytest

from guardian_truth.integrated.transport import sha
from guardian_truth.verification.pipeline import packet_for
from guardian_truth.v6fix import pipeline as P


POLICY = 'You must make at most zero tool calls per turn.'
RULE = dict(type='MAX_TOOL_CALLS_PER_TURN', n=0, quote=POLICY, condition='', exception='', scope='', subject='agent')


def row(response='Hello.', policy=POLICY):
    return dict(prompt='⟦SYSTEM⟧\n' + policy, response=response)


class Client:
    def __init__(self):
        self.calls = []
    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(request=deepcopy(request), attempt=attempt, tag=tag))
        return dict(content=json.dumps(dict(rules=[RULE])), transport=dict(status=200), finish_reason='stop',
                    usage={}, cached=False, key=sha(dict(request=request, attempt=attempt)))


@pytest.mark.parametrize('invalid', [None, 0, 1, 'false', [], {}])
def test_lazy_flag_is_strict_boolean(invalid):
    with pytest.raises(ValueError, match='SKIP_INAPPLICABLE_F_MUST_BE_BOOLEAN'):
        P.Layers(Client(), 'test', skip_inapplicable_f=invalid)


@pytest.mark.parametrize('response', ['Hello.',
    '⟦USER_TOOL_CALL name="lookup"⟧\n{}',
    '⟦TOOL_RESULT name="lookup" requestor="assistant"⟧\n{"value": 1}',
    'I describe a lookup without executing it.'])
def test_no_assistant_call_skips_all_f_stages_without_poisoning_cache(monkeypatch, response):
    input_row = row(response)
    packet = packet_for(input_row, 400000)
    assert not any(t['kind'] == 'call' and t['role'] == 'assistant' for t in packet['current_targets'])
    def forbidden(*args, **kwargs):
        pytest.fail('An inapplicable F stage was executed')
    for name in ('extract', 'bind', 'check'):
        monkeypatch.setattr(P.F, name, forbidden)
    client = Client()
    layers = P.Layers(client, 'test', layers=('F',), skip_inapplicable_f=True)
    result = layers.findings(input_row)
    assert result['findings'] == [] and result['rules'] == [] and result['extraction']['raw'] is None
    assert result['f_eligibility']['status'] == 'SKIPPED_NO_CURRENT_ASSISTANT_CALL'
    assert result['f_eligibility']['authority'] == 'CHECKER_CAPABILITY_ONLY'
    assert layers.cache == {} and client.calls == []


@pytest.mark.parametrize('response', ['⟦ASSISTANT_TOOL_CALL name="lookup"⟧\n{}',
                                     '⟦ASSISTANT⟧\n→ TOOL_CALL lookup: {broken'])
def test_single_call_max_zero_and_malformed_args_retain_original_positive(response):
    input_row = row(response)
    old_client, new_client = Client(), Client()
    old = P.Layers(old_client, 'test', layers=('F',)).findings(input_row)
    revised = P.Layers(new_client, 'test', layers=('F',), skip_inapplicable_f=True).findings(input_row)
    eligibility = revised.pop('f_eligibility')
    assert eligibility['status'] == 'ELIGIBLE_CURRENT_ASSISTANT_CALL' and eligibility['skipped'] is False
    assert revised == old and new_client.calls == old_client.calls
    assert len(new_client.calls) == 2
    assert revised['findings'][0]['status'] == 'MECHANICAL'
    assert revised['findings'][0]['fact']['limit'] == 0
    assert revised['findings'][0]['fact']['n_calls'] == 1


def test_text_then_call_same_policy_does_not_reuse_fake_empty_extraction():
    client = Client()
    layers = P.Layers(client, 'test', layers=('F',), skip_inapplicable_f=True)
    layers.findings(row())
    assert not client.calls and not layers.cache
    called = row('⟦ASSISTANT⟧\n→ TOOL_CALL lookup: {}')
    first = layers.findings(called)
    assert len(client.calls) == 2 and first['findings'][0]['status'] == 'MECHANICAL'
    before = deepcopy(layers.cache)
    layers.findings(row())
    assert layers.cache == before and len(client.calls) == 2
    second = layers.findings(called)
    assert second == first and len(client.calls) == 2


def test_disabled_lazy_flag_keeps_identical_extraction_wire_and_receipts():
    default_client, explicit_client = Client(), Client()
    default = P.Layers(default_client, 'test').findings(row())
    explicit = P.Layers(explicit_client, 'test', skip_inapplicable_f=False).findings(row())
    assert default == explicit and default_client.calls == explicit_client.calls
    assert len(default_client.calls) == 2 and 'f_eligibility' not in default
    assert default['rules'][0]['status'] == 'MECHANICAL' and default['findings'] == []


def test_skip_preserves_s_p_findings_records_and_coverage(monkeypatch):
    seen = []
    structural = dict(layer='S', status='HYPOTHESIS', kind='FIXTURE', reason='Structural fixture')
    provenance = dict(layer='P', status='HYPOTHESIS', kind='FIXTURE', reason='Provenance fixture')
    def structural_check(packet):
        seen.append(('S', deepcopy(packet)))
        return [deepcopy(structural)]
    def provenance_check(packet):
        seen.append(('P', deepcopy(packet)))
        return [deepcopy(provenance)], [dict(record='preserved')]
    monkeypatch.setattr(P.S, 'check', structural_check)
    monkeypatch.setattr(P.P, 'check', provenance_check)
    input_row = row()
    original = deepcopy(input_row)
    result = P.Layers(Client(), 'test', skip_inapplicable_f=True).findings(input_row)
    assert result['findings'] == [structural, provenance] and result['records'] == [dict(record='preserved')]
    assert [name for name, _ in seen] == ['S', 'P']
    assert result['coverage'] == P.coverage(seen[0][1]) == P.coverage(seen[1][1])
    assert input_row == original


def test_mandatory_target_overflow_is_unresolved_not_absence_of_call():
    input_row = row('⟦ASSISTANT⟧\n→ TOOL_CALL lookup: {"payload":"' + 'x' * 5000 + '"}')
    assert packet_for(input_row, 100) is None
    client = Client()
    result = P.Layers(client, 'test', budget=100, skip_inapplicable_f=True).findings(input_row)
    assert result['coverage'] is None and result['extraction'] is None
    assert result['f_eligibility']['status'] == 'UNRESOLVED_NO_PACKET'
    assert client.calls == []


def test_incomplete_history_does_not_hide_current_assistant_call():
    input_row = dict(prompt='⟦SYSTEM⟧\n' + POLICY + '\n⟦USER⟧\nEarlier unrelated request.\n'
                           '⟦ASSISTANT⟧\n→ TOOL_CALL old_lookup: {}\n'
                           '← TOOL_RESPONSE old_lookup: {"data":"' + 'history ' * 1500 + '"}\n'
                           '⟦USER⟧\nCurrent request.',
                     response='⟦ASSISTANT⟧\n→ TOOL_CALL lookup: {}')
    packet = packet_for(input_row, 4000)
    assert packet is not None and not packet['coverage']['complete_input']
    assert any(t['kind'] == 'call' and t['role'] == 'assistant' for t in packet['current_targets'])
    client = Client()
    result = P.Layers(client, 'test', budget=4000, layers=('F',), skip_inapplicable_f=True).findings(input_row)
    assert result['f_eligibility']['status'] == 'ELIGIBLE_CURRENT_ASSISTANT_CALL'
    assert len(client.calls) == 2


def test_lazy_option_with_disabled_f_makes_no_eligibility_claim():
    result = P.Layers(Client(), 'test', layers=('S', 'P'), skip_inapplicable_f=True).findings(row())
    assert result['f_eligibility']['status'] == 'DISABLED_LAYER'
