"""Evaluator boundaries and genuinely response-independent prepass requests."""
import copy
import json

import pytest

from experiments.guardian_addons import evaluator, variants2
from experiments.guardian_semantic import variants
from experiments.guardian_semantic.neutral import neutral_view
from guardian_truth.integrated.reviewer import body
from guardian_truth.verification.pipeline import packet_for


def b(name, value, kind='STRING'):
    return dict(name=name, value=value, type=kind, source_id='h1')


@pytest.mark.parametrize('literal', ['AND', 'NOT TRUE', 'x=y', 'IF a THEN b', ' TRUE ', 'a!=b'])
def test_expression_literal_contents_unchanged(literal):
    assert evaluator.compute('x == ' + repr(literal), [b('x', literal)]) == ('OK', True)


def test_exact_number_tokens_before_ast_float_rounding():
    assert evaluator.compute('0.10000000000000000001 > 0.1', []) == ('OK', True)
    assert evaluator.compute('1000000000000000000000000000001 > 1000000000000000000000000000000', []) == ('OK', True)
    assert evaluator.compute('x == 9007199254740993.0', [b('x', '9007199254740993.0', 'NUMBER')]) == ('OK', True)
    assert evaluator.compute('1e30 + 1 > 1e30', []) == ('OK', True)
    assert evaluator.compute('1e60 + 1 > 1e60', []) == ('OK', True)
    assert evaluator.compute('(1 / 3) * 3 == 1', [])[0] == 'TYPE_ERROR'


def test_string_binding_whitespace_is_semantic():
    assert evaluator.compute("x == 'X'", [b('x', ' X ')]) == ('OK', False)
    assert evaluator.source_status(b('x', ' X '), {'h1': 'X'}) == 'NOT_FOUND'


@pytest.mark.parametrize('value', ['NaN', 'sNaN', 'Infinity', '-Infinity', 0.1, True])
def test_invalid_number_stays_local_unevaluable(value):
    result = evaluator.check(dict(expression='x > 0', bindings=[b('x', value, 'NUMBER')], claimed_result='TRUE'), {'h1': str(value)})
    assert result['consistency'] == 'UNEVALUABLE'
    assert result['computation'] == 'TYPE_ERROR'


def test_conditional_cannot_be_reinterpreted_as_antecedent():
    assert evaluator.compute('IF TRUE THEN FALSE', []) == ('UNSUPPORTED_CONDITIONAL', None)
    assert evaluator.compute('TRUE AND NOT FALSE', []) == ('OK', True)


@pytest.mark.parametrize('expression', ['1 / 0 > 0', '1e99999999999999999999 > 0', '-TRUE == -1', 'hours_between(a,b, x=1) > 0'])
def test_runtime_errors_do_not_escape(expression):
    assert evaluator.compute(expression, [])[0] != 'OK'


def test_duplicate_bindings_and_unknown_types_rejected():
    assert evaluator.compute('x == 1', [b('x', '1', 'NUMBER'), b('x', '2', 'NUMBER')])[0] == 'TYPE_ERROR'
    assert evaluator.compute("x == '1'", [b('x', '1', 'ENTITY_MAGIC')])[0] == 'TYPE_ERROR'


def test_prepass_valid_json_from_failed_transport_cannot_be_injected():
    rec = dict(content=json.dumps({'requirements': []}), transport={'status': 429})
    assert variants._parse(rec) is None
    assert rec['schema_validation']['status'] == 'TRANSPORT_FAILURE'


def test_expression_contradiction_does_not_change_other_rules_in_same_document():
    analysis = dict(requirements=[dict(source_id='p1', requirement='Rule one', applies='YES'),
                                  dict(source_id='p1', requirement='Rule two', applies='YES')])
    checked = evaluator.check(dict(requirement_source_id='p1', expression='1 > 2', bindings=[], claimed_result='TRUE'), {})
    result, changed = variants2.apply_eval(analysis, [checked])
    assert changed and [r['applies'] for r in result['requirements']] == ['YES', 'YES']
    assert result['code_checks'][0]['requirement_binding'] == 'UNRESOLVED'


def test_byte_cap_matches_actual_transport_encoding():
    from guardian_truth.integrated.transport import wire_body
    request = {'model': variants.SMALL, 'messages': [{'role': 'user', 'content': 'Пример' * 30}], 'max_tokens': 1}
    compact = len(json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    assert len(wire_body(request)) > compact
    client = Fake()
    hook = variants.Hook(client, None, variants.SMALL, max_request_bytes=compact)
    result = hook.call(request)
    assert not client.calls and result['input_budget']['request_bytes'] == len(wire_body(request))


def row(long=False):
    history = ''.join('⟦USER⟧\nOld context %s %s\n' % (i, 'x' * 120) for i in range(50)) if long else ''
    return dict(prompt='⟦SYSTEM⟧\n<policy>Do not invent identifiers.</policy>\n'
                      '[AVAILABLE TOOLS]\n- lookup — Look up a record.\n    key: string! — Identifier.\n'
                      + history + '⟦USER⟧\nPlease look up record A1.\n',
                response='⟦ASSISTANT⟧\n→ TOOL_CALL lookup: {"key":"A1"}')


class Fake:
    def __init__(self, invalid=False):
        self.calls, self.invalid = [], invalid

    def call(self, request, attempt=0, tag=''):
        self.calls.append(copy.deepcopy(request))
        value = dict(requirements=[], entities=[], computed_values=[], expected_actions=[], uncertainties=[])
        if 'condition_checks' in request['response_format']['json_schema']['schema']['properties']:
            value['condition_checks'] = []
        if self.invalid:
            value.pop('requirements')
        return dict(content=json.dumps(value), transport={'status': 200}, finish_reason='stop')


@pytest.mark.parametrize('pre', ['blind', 'blind2', 'blind2_typed', 'blind2_typed_eval'])
@pytest.mark.parametrize('long', [False, True])
def test_fixed_prompt_changed_action_identical_prepass_request(pre, long):
    requests = []
    for response in ['⟦ASSISTANT⟧\n→ TOOL_CALL lookup: {"key":"A1"}',
                     '⟦ASSISTANT⟧\n→ TOOL_CALL completely_different_tool: {"owner":"Other", "text":"' + 'Q' * 2300 + '"}']:
        original = row(long)
        original['response'] = response
        packet = packet_for(original, 6000 if long else 20000)
        assert packet is not None
        request = body(packet, 'mistral', variants.SMALL)
        client = Fake()
        cls = variants.Hook if pre == 'blind' else variants2.Hook2
        hook = cls(client, pre, variants.SMALL, original_row=original, blind_budget_bytes=3000 if long else 20000)
        out = hook.inject(request, 0)
        assert hook.log[0]['injected'] and len(client.calls) == 1
        requests.append(client.calls[0])
        view = json.loads(client.calls[0]['messages'][1]['content'])
        assert 'current_targets' not in view
        assert 'declaration_status' not in view['coverage']
        assert view['coverage']['source_scope'] == 'ORIGINAL_PROMPT_ONLY'
        assert view['declarations'] and view['declarations'][0]['kind'] == 'catalog'
        assert view['coverage']['complete_input'] is (not long)
        if long:
            assert view['coverage']['unread']
        assert 'blind_analysis_sources' in json.loads(out['messages'][1]['content'])
        assert client.calls[0]['response_format']['json_schema']['name'] == 'pre_analysis_neutral_v2'
    assert requests[0] == requests[1]


def test_untrusted_prepacked_view_abstains_without_call_or_mutation():
    request = body(packet_for(row(), 20000), 'mistral', variants.SMALL)
    client = Fake()
    hook = variants2.Hook2(client, 'blind2', variants.SMALL)
    assert hook.inject(request, 0) == request
    assert not client.calls
    assert hook.log[0]['view']['reason'] == 'ORIGINAL_PROMPT_REQUIRED'
    with pytest.raises(ValueError, match='ORIGINAL_PROMPT_REQUIRED'):
        variants2.blind_packet2(json.loads(request['messages'][1]['content']))


def test_neutral_required_anchor_budget_fail_is_explicit():
    packet, receipt = neutral_view(row(), budget_bytes=1)
    assert packet is None and receipt['status'] == 'NOT_EXECUTED'


def test_schema_incomplete_analysis_is_not_injected():
    request = body(packet_for(row(), 20000), 'mistral', variants.SMALL)
    client = Fake(invalid=True)
    hook = variants2.Hook2(client, 'blind2', variants.SMALL, original_row=row())
    assert hook.inject(request, 0) == request
    assert hook.log[0]['schema_validation']['status'] == 'INVALID_SCHEMA'
    assert not hook.log[0]['injected']


def test_duplicate_reply_keys_and_nonfinite_json_rejected():
    for content in ['{"requirements":[],"requirements":[]}', '{"n":NaN}']:
        rec = dict(content=content)
        assert variants._parse(rec, {}) is None
        assert rec['schema_validation']['status'] == 'INVALID_JSON'


@pytest.mark.parametrize('pre', ['blind', 'blind2', 'blind2_typed_eval', 'probe', 'probe_noexec'])
def test_whole_prepass_request_byte_cap_refuses_without_transport(pre):
    request = body(packet_for(row(), 20000), 'mistral', variants.SMALL)
    client = Fake()
    cls = variants.Hook if pre in ('blind', 'probe', 'probe_noexec') else variants2.Hook2
    hook = cls(client, pre, variants.SMALL, original_row=row(), max_request_bytes=1)
    result = hook.call(request, tag='review')
    assert not client.calls
    assert result['transport']['status'] == 'NOT_EXECUTED_INPUT_BUDGET'
    assert result['input_budget']['request_bytes'] > 1
    assert result['input_budget']['validation'] == 'SERIALIZED_UTF8_BYTE_CAP_ONLY_NOT_PROVIDER_TOKENIZER'


@pytest.mark.parametrize('cls,pre', [(variants.Hook, 'blind'), (variants2.Hook2, 'blind2_typed_eval')])
def test_augmented_review_over_cap_falls_back_to_unchanged_base(cls, pre):
    request = body(packet_for(row(), 20000), 'mistral', variants.SMALL)
    first = Fake()
    uncapped = cls(first, pre, variants.SMALL, original_row=row())
    augmented = uncapped.inject(request, 0)
    wire_bytes = lambda r: len(json.dumps(r).encode('utf-8'))
    cap = max(wire_bytes(request), wire_bytes(first.calls[0]))
    assert wire_bytes(augmented) > cap
    client = Fake()
    hook = cls(client, pre, variants.SMALL, original_row=row(), max_request_bytes=cap)
    hook.call(request, tag='review')
    assert client.calls[-1] == request
    assert hook.log[-1]['transport']['status'] == 'NOT_EXECUTED_INPUT_BUDGET'
    assert all(not step.get('injected') for step in hook.log)


def test_multibyte_wire_size_uses_utf8_and_does_not_clip():
    client = Fake()
    hook = variants.Hook(client, None, variants.SMALL, max_request_bytes=30)
    request = dict(messages=[dict(content='Ж' * 30)])
    original = copy.deepcopy(request)
    result = hook.call(request, tag='other')
    assert result['transport']['status'] == 'NOT_EXECUTED_INPUT_BUDGET'
    assert result['input_budget']['request_bytes'] > 60
    assert request == original and not client.calls
