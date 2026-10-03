"""Probe lifecycle checks use mock transport only; no model or benchmark labels."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('consent_pair_probe',
    ROOT / 'experiments/searh_23/v11/consent_pair_probe.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def row(identifier='case', *, amount=2, malformed=False, reply='Yes'):
    prompt = ('⟦SYSTEM⟧\nBefore modifying obtain confirmation.\n[AVAILABLE TOOLS]\n'
              '- apply_a — modify a record\n    record_id: string!\n    amount: number!\n'
              '- inspect_b — inspect a record\n    record_id: string\n'
              '⟦USER⟧\nHelp with record X.\n'
              '⟦ASSISTANT⟧\nConfirm applying amount 2 to record X?\n')
    if reply is not None:
        prompt += '⟦USER⟧\n' + reply + '\n'
    arguments = 'broken JSON' if malformed else json.dumps({'record_id': 'X', 'amount': amount})
    return {'id': identifier, 'prompt': prompt, 'response': '→ TOOL_CALL apply_a: ' + arguments}


def case(identifier='case', *, kind='REAL_LABEL_FREE', amount=2, malformed=False, reply='Yes'):
    source = row(identifier, amount=amount, malformed=malformed, reply=reply)
    target = {'source_id': 't0', 'tool': 'apply_a',
              'arguments': None if malformed else {'record_id': 'X', 'amount': amount}}
    return probe.make_case(source, target, identifier=identifier, kind=kind,
                           expected='TRUE' if kind == 'SYNTHETIC' else None)


def frozen(cases):
    for item in cases:
        if item['kind'] == 'REAL_LABEL_FREE':
            item.setdefault('explicit_confirmation_scope', {'selected': True, 'annotation_status': probe.ANNOTATION_STATUS})
    return {'version': probe.VERSION, 'sources': {'src/guardian_truth/policy_table_v11/consent_pair.py': 'frozen'},
            'cases': cases, 'case_order': [item['id'] for item in cases], 'models': deepcopy(probe.MODELS),
            'max_output_tokens': 8192, 'timeout': 180, 'temperature': 0,
            'model_backend': 'PLAIN_JSON_PROMPT_NO_RESPONSE_FORMAT_SCHEMA',
            'output_contract': 'CONSENT_PAIR_SOURCE_BOUND_JSON/1', 'ledger': 'mock-ledger',
            'limits': {'http': 450, 'tokens': 3000000},
            'retry': {'syntax': 1, 'same_messages': True, 'no_length_retry': True, 'no_status_retry': True},
            'peer_replay': {'total_peer_replay': 17, 'consent_included': 14, 'state_only_excluded': []}}


def extracted_pair():
    return {'messages': [{'source_id': 'h2', 'kind': 'ACTION_REQUEST', 'plans': [{
        'actor': 'ASSISTANT', 'tool': 'apply_a', 'arguments': {'record_id': 'X', 'amount': 2},
        'action_quote': 'Confirm applying amount 2 to record X?',
        'bindings': [{'path': '/record_id', 'value': 'X', 'source_id': 'h2', 'quote': 'record X'},
                     {'path': '/amount', 'value': 2, 'source_id': 'h2', 'quote': 'amount 2'}],
        'reply': {'source_ids': ['h3'], 'kind': 'CONFIRM',
                  'quotes': [{'source_id': 'h3', 'quote': 'Yes'}]},
    }]}]}


@pytest.fixture
def transport_mock(tmp_path, monkeypatch):
    state = {'requests': [], 'replies': [], 'known_tokens': 0, 'http_attempts': 0,
             'auth_stop': False, 'provider_breakers': ['breaker_mistral'], 'on_call': None, 'configs': []}

    class MockTransport:
        def __init__(self, directory, provider, model, **kwargs):
            self.provider, self.model = provider, model
            self.max_calls, self.max_tokens = kwargs['max_calls'], kwargs['max_tokens']
            state['configs'].append({'provider': provider, 'model': model, **kwargs})

        def snapshot(self):
            return {key: deepcopy(state[key]) for key in
                    ('known_tokens', 'http_attempts', 'auth_stop', 'provider_breakers')} | {
                        'unknown_upper_bound': 0, 'pending': 0,
                        'limits': {'http': self.max_calls, 'tokens': self.max_tokens}}

        def __call__(self, messages, *, fresh_sample):
            state['requests'].append({'model': self.model, 'messages': deepcopy(messages), 'sample': fresh_sample})
            response = state['replies'].pop(0) if state['replies'] else {'status': 'OK', 'content': '{"messages":[]}'}
            response = deepcopy(response)
            if response['status'] not in probe.STOP_STATUSES and not response.get('without_attempt'):
                state['http_attempts'] += 1
                state['known_tokens'] += 7
                response.update({'attempt_id': state['http_attempts'], 'provider': self.provider,
                                 'model': self.model, 'known_tokens': 7,
                                 'unknown_upper_bound': 0, 'seconds': 0.1})
            if state['on_call']:
                state['on_call'](state)
            return response

    monkeypatch.setattr(probe, 'RUN', tmp_path / 'run')
    monkeypatch.setattr(probe, 'Transport', MockTransport)
    return state


def test_cohort_exact_preparation_order_sample_and_malformed_calls():
    value = probe.inventory_data()
    assert len(value['cases']) == 84
    assert value['sample_seed'] == 20261003
    prepared = probe.read(probe.PREPARATION / 'witness_inventory.json')
    assert [probe.witness_key(item) for item in value['cases']] == [
        {key: item[key] for key in ('case_id', 'policy', 'target')} for item in prepared['calls']]
    assert all(set(item['row']) == {'id', 'prompt', 'response'} for item in value['cases'])
    malformed = [item for item in value['cases'] if not item['target_arguments_valid']]
    assert [(item['case_id'], item['target']['source_id'], item['target']['arguments']) for item in malformed] == [
        ('airline__24::t14', 'h43', None), ('airline__24::t14', 'h44', None)]
    assert any(item['tool_role'] == 'UNKNOWN' for item in value['cases'])
    assert len(value['exclusions']['undeclared_excluded']) == 29


def test_peer_confirmation_only_preserves_historical_scope_issue():
    cases, replay = probe.peer_cases()
    assert len(cases) == 14 and replay['total_peer_replay'] == 17
    assert {item['id'] for item in replay['state_only_excluded']} == probe.STATE_ONLY_PEER_IDS
    courtesy = next(item for item in cases if item['id'] == 'synthetic/courtesy_ru')
    assert courtesy['expected'] == 'TRUE'
    assert courtesy['source_qualified_expected'] == 'UNRESOLVED'
    assert courtesy['annotations'] == ['parameter_scope_underspecified']


def test_selection_includes_unknown_and_malformed_but_excludes_reads_and_user_calls():
    source = row()
    source['prompt'] = source['prompt'].replace('- inspect_b —', '- opaque_c — opaque operation\n'
                                              '    record_id: string\n- inspect_b —')
    source['response'] = ('→ TOOL_CALL inspect_b: {"record_id":"X"}\n'
                          '→ TOOL_CALL opaque_c: malformed\n'
                          '⟦USER_TOOL_CALL name="apply_a"⟧\n{"record_id":"X","amount":2}\n'
                          '⟦ASSISTANT_TOOL_CALL name="apply_a"⟧\n{"record_id":"X","amount":2}')
    selected, exclusions = probe.select_real_cases([source])
    assert [item['target']['tool'] for item in selected] == ['opaque_c', 'apply_a']
    assert selected[0]['tool_role'] == 'UNKNOWN'
    assert selected[0]['target']['arguments'] is None
    assert exclusions['read_calls_excluded'] == 1


def test_request_hides_current_target_values_and_deduplicates_identical_context():
    first, changed = case('first'), case('other', amount=928371)
    a = probe.semantic().request(probe.SourceStore(first['row']), first['target'])
    b = probe.semantic().request(probe.SourceStore(changed['row']), changed['target'])
    assert a == b and '928371' not in json.dumps(b)
    value = frozen([first, changed])
    assert probe.request_id(a, value['models'][0], value) == probe.request_id(b, value['models'][0], value)
    for field in ('max_output_tokens', 'timeout', 'temperature', 'version', 'output_contract'):
        altered = deepcopy(value)
        altered[field] = 'different'
        assert probe.request_id(a, value['models'][0], altered) != probe.request_id(a, value['models'][0], value)


def test_canonical_git_blob_uses_clean_crlf_filter(tmp_path, monkeypatch):
    subprocess.run(['git', 'init', '--quiet', str(tmp_path)], check=True, capture_output=True)
    subprocess.run(['git', 'config', 'core.autocrlf', 'true'], cwd=tmp_path, check=True)
    source = tmp_path / 'source.py'
    source.write_bytes(b'first\r\nsecond\r\n')
    monkeypatch.setattr(probe, 'ROOT', tmp_path)
    canonical = probe.git_blob('source.py')
    expected = subprocess.run(['git', 'hash-object', '--stdin'], cwd=tmp_path, input=b'first\nsecond\n',
                              check=True, capture_output=True).stdout.decode().strip()
    assert canonical == expected
    source.write_bytes(b'first\nsecond\n')
    assert probe.git_blob('source.py') == canonical


def test_freeze_runs_synthetic_first_binds_gate_and_records_packet_sizes(transport_mock, monkeypatch):
    native = case('real')
    peer = case('synthetic', kind='SYNTHETIC')
    cohort = {'cases': [native], 'selection': 'PREPARE_WITNESSES', 'exclusions': {},
              'sample_20': ['real'], 'preparation_signature': 'ordered'}
    monkeypatch.setattr(probe, 'inventory_data', lambda: cohort)
    monkeypatch.setattr(probe, 'peer_cases', lambda: ([peer], {'total_peer_replay': 17}))
    monkeypatch.setattr(probe, 'source_paths', lambda: ['src/guardian_truth/policy_table_v11/consent_pair.py'])
    monkeypatch.setattr(probe, 'git_blob', lambda path: 'frozen')
    monkeypatch.setattr(probe, 'annotate_scope', lambda cases: (cases, {'explicit_consent_calls': 1}))
    extra = {'id': 'extra', 'row': row('extra'), 'expected': 'TRUE'}
    probe.freeze([extra])
    value = probe.read(probe.RUN / 'freeze.json')
    assert value['case_order'] == ['synthetic', 'extra/extra', 'real']
    assert value['max_output_tokens'] == 8192 and value['timeout'] == 180
    assert value['safety_gate']['failure'] == 'STOP_REQUIRE_NEW_VERSION_AND_FREEZE'
    assert not value['safety_gate']['unknown_aborts'] and not value['safety_gate']['missing_aborts']
    assert value['packet_sizes']['REAL_LABEL_FREE']['request_eligible'] == 1
    assert value['packet_sizes']['SYNTHETIC']['unique_messages'] == 1
    assert not transport_mock['requests']


def test_source_manifest_requires_pre_call_protocol_review(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'ROOT', tmp_path)
    monkeypatch.setattr(probe, 'INPUTS', tmp_path / 'inputs.jsonl')
    monkeypatch.setattr(probe, 'PEER', tmp_path / 'peer.json')
    monkeypatch.setattr(probe, 'PREPARATION', tmp_path / 'preparation')
    source = tmp_path / 'src/guardian_truth/policy_table_v11/consent_pair.py'
    source.parent.mkdir(parents=True)
    source.write_text('', encoding='utf-8')
    with pytest.raises(ValueError, match='required_protocol_source_missing'):
        probe.source_paths()


def test_verify_requires_committed_freeze_and_source_blobs(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'ROOT', tmp_path)
    monkeypatch.setattr(probe, 'RUN', tmp_path / 'run')
    monkeypatch.setattr(probe, 'REAL_COUNT', 1)
    monkeypatch.setattr(probe, 'EXPLICIT_CONSENT_COUNT', 1)
    value = frozen([case()])
    probe.write(probe.RUN / 'freeze.json', value)
    monkeypatch.setattr(probe.subprocess, 'check_output', lambda *args, **kwargs: json.dumps(value).encode())
    monkeypatch.setattr(probe, 'git_blob', lambda path: 'frozen')
    monkeypatch.setattr(probe, 'committed_blob', lambda path: 'frozen')
    assert probe.verify() == value
    monkeypatch.setattr(probe, 'committed_blob', lambda path: 'different')
    with pytest.raises(ValueError, match='frozen_source_blob_not_committed'):
        probe.verify()
    monkeypatch.setattr(probe, 'committed_blob', lambda path: 'frozen')
    altered = deepcopy(value)
    altered['temperature'] = 1
    probe.write(probe.RUN / 'freeze.json', altered)
    with pytest.raises(ValueError, match='freeze_not_committed'):
        probe.verify()


def test_raw_saved_before_parse_one_syntax_retry_and_complete_cache(transport_mock, monkeypatch):
    value = frozen([case()])
    messages = [{'role': 'user', 'content': 'frozen prompt'}]
    transport_mock['replies'] = [{'status': 'OK', 'content': 'not JSON'},
                                  {'status': 'OK', 'content': '{"messages":[]}'}]
    original = probe.decode_model_object
    observed = []
    def decode(content):
        raw = probe.read(probe.RUN / 'replies' / (probe.request_id(messages, value['models'][0], value) + '.json'))
        observed.append(raw)
        assert raw['reply']['content'] == 'not JSON'
        if content.startswith('{'):
            assert raw['retry']['content'] == content
        return original(content)
    monkeypatch.setattr(probe, 'decode_model_object', decode)
    result = probe.call(messages, value['models'][0], value)
    assert result['complete'] and result['decoded'] == {'messages': []}
    assert len(transport_mock['requests']) == 2 and len(observed) == 2
    assert transport_mock['requests'][0]['messages'] == transport_mock['requests'][1]['messages']
    assert transport_mock['requests'][1]['sample'].endswith('/syntax_retry')
    assert probe.call(messages, value['models'][0], value)['reused']
    assert len(transport_mock['requests']) == 2
    assert all(config['max_output_tokens'] == 8192 and config['timeout'] == 180
               for config in transport_mock['configs'])


@pytest.mark.parametrize('reply,outcome', [
    ({'status': 'OK', 'content': '{}', 'provider_response': {'choices': [{'finish_reason': 'length'}]}}, 'LENGTH'),
    ({'status': 'UNAVAILABLE', 'http_status': 500}, 'UNAVAILABLE'),
])
def test_no_length_or_status_retry(transport_mock, reply, outcome):
    value = frozen([case()])
    transport_mock['replies'] = [reply]
    result = probe.call([{'role': 'user', 'content': 'frozen'}], value['models'][0], value)
    assert result['complete'] and result['outcome'] == outcome
    assert result['retry'] is None and len(transport_mock['requests']) == 1


def test_invalid_json_retries_at_most_once_and_persists_terminal_failure(transport_mock):
    value = frozen([case()])
    transport_mock['replies'] = [{'status': 'OK', 'content': 'invalid'}] * 2
    messages = [{'role': 'user', 'content': 'frozen'}]
    result = probe.call(messages, value['models'][0], value)
    assert result['complete'] and result['outcome'] == 'INVALID_JSON' and result['decoded'] is None
    assert probe.call(messages, value['models'][0], value)['complete']
    assert len(transport_mock['requests']) == 2


@pytest.mark.parametrize('content', ['[]', 'null', '"wrong schema"'])
def test_valid_json_wrong_schema_is_not_a_syntax_retry(transport_mock, content):
    value = frozen([case()])
    transport_mock['replies'] = [{'status': 'OK', 'content': content}]
    result = probe.call([{'role': 'user', 'content': 'frozen'}], value['models'][0], value)
    assert result['complete'] and result['outcome'] == 'OK' and result['syntax_valid']
    assert result['retry'] is None and len(transport_mock['requests']) == 1


def test_syntax_retry_stop_is_pending_and_resume_does_not_repeat_primary(transport_mock):
    value = frozen([case()])
    transport_mock['replies'] = [{'status': 'OK', 'content': 'invalid'}, {'status': 'BUDGET_STOP'}]
    messages = [{'role': 'user', 'content': 'frozen'}]
    stopped = probe.call(messages, value['models'][0], value)
    assert not stopped['complete'] and stopped['blocked'] == 'BUDGET_STOP'
    transport_mock['replies'] = [{'status': 'OK', 'content': '{"messages":[]}'}]
    resumed = probe.call(messages, value['models'][0], value)
    assert resumed['complete'] and len(transport_mock['requests']) == 3
    assert transport_mock['requests'][1]['sample'] == transport_mock['requests'][2]['sample']


def test_run_deduplicates_different_target_values_without_sharing_verdicts(transport_mock, monkeypatch):
    cases = [case('first'), case('changed', amount=999)]
    value = frozen(cases)
    monkeypatch.setattr(probe, 'verify', lambda: value)
    report = probe.run_probe()
    assert report['complete']
    assert len(transport_mock['requests']) == 2
    assert all(family['real']['expected'] == 2 and family['real']['completed'] == 2 for family in report['families'])
    assert report['cost']['own_unique_attempts']['http_attempts'] == 2
    assert report['cost']['global_before']['http_attempts'] == 0
    assert report['cost']['global_after']['http_attempts'] == 2
    assert report['cost']['global_delta']['known_tokens'] == 14
    assert report['M1']['api_calls'] == 0 and report['M1']['never_true']
    raw = probe.read(probe.RUN / 'fullresult.raw.json')
    assert len(raw['raw_records']) == 2 and len(raw['rows']) == 2
    assert report['cost']['global_after']['provider_breakers'] == ['breaker_mistral']
    probe.run_probe()
    assert len(transport_mock['requests']) == 2


def test_wrong_resolved_synthetic_consensus_stops_before_real_and_cannot_resume(transport_mock, monkeypatch):
    synthetic = case('synthetic', kind='SYNTHETIC')
    synthetic['expected'] = 'UNRESOLVED'
    value = frozen([synthetic, case('real', amount=999)])
    monkeypatch.setattr(probe, 'verify', lambda: value)
    transport_mock['replies'] = [{'status': 'OK', 'content': json.dumps(extracted_pair())}] * 2
    stopped = probe.run_probe()
    assert stopped['stop_reason'] == 'SYNTHETIC_SAFETY_GATE' and not stopped['complete']
    assert stopped['safety_gate']['status'] == 'FAIL'
    assert stopped['safety_gate']['failures'] == [
        {'id': 'synthetic', 'expected': 'UNRESOLVED', 'actual': 'TRUE', 'historical_expected': 'UNRESOLVED'}]
    assert len(transport_mock['requests']) == 2
    assert all(family['real']['completed'] == 0 for family in stopped['families'])
    assert len(probe.read(probe.RUN / 'fullresult.raw.json')['raw_records']) == 2
    assert stopped['M1']['never_true'] and stopped['M1']['admission_failures'] == 2
    probe.run_probe()
    assert len(transport_mock['requests']) == 2


def test_gate_uses_qualified_expectation_and_unknown_missing_do_not_abort():
    annotated = case('annotated', kind='SYNTHETIC')
    annotated['source_qualified_expected'] = 'UNRESOLVED'
    missing = case('missing', kind='SYNTHETIC')
    value = frozen([annotated, missing, case('real')])
    rows = {'annotated': {'complete': True, 'consensus': {'value': 'UNRESOLVED'}}}
    gate = probe.safety_gate(value, rows)
    assert gate['status'] == 'PASS' and gate['missing_case_ids'] == ['missing']
    assert gate['unresolved_case_ids'] == ['annotated']
    rows['annotated']['consensus']['value'] = 'TRUE'
    assert probe.safety_gate(value, rows)['status'] == 'FAIL'


def test_auth_stop_preserves_partial_models_and_resume_finishes_without_repeating(transport_mock, monkeypatch):
    value = frozen([case('first'), case('second', amount=999)])
    monkeypatch.setattr(probe, 'verify', lambda: value)
    transport_mock['on_call'] = lambda state: state.update(auth_stop=True)
    stopped = probe.run_probe()
    progress = probe.read(probe.RUN / 'result.json')
    assert stopped['stop_reason'] == 'AUTH_STOP' and not stopped['complete']
    assert len(progress['rows']) == 1 and len(progress['rows'][0]['models']) == 1
    assert not progress['rows'][0]['complete'] and progress['rows'][0]['consensus'] is None
    assert stopped['families'][0]['real']['completed'] == 1
    assert stopped['families'][1]['real']['completed'] == 0
    assert stopped['families'][1]['real']['UNKNOWN'] == 0  # Pending is not failure.
    raw_path = probe.RUN / progress['rows'][0]['models'][0]['raw_path']
    original_raw = raw_path.read_bytes()
    transport_mock.update(auth_stop=False, on_call=None)
    resumed = probe.run_probe()
    assert resumed['complete'] and len(transport_mock['requests']) == 2
    assert raw_path.read_bytes() == original_raw
    assert len(probe.read(probe.RUN / 'result.json')['sessions']) == 2


def test_budget_stop_does_not_complete_or_score_skipped_slots(transport_mock, monkeypatch):
    value = frozen([case('first'), case('second')])
    value['limits']['http'] = 1
    monkeypatch.setattr(probe, 'verify', lambda: value)
    stopped = probe.run_probe()
    assert stopped['stop_reason'] == 'BUDGET_STOP' and not stopped['complete']
    assert len(transport_mock['requests']) == 1
    assert stopped['families'][0]['real']['completed'] == 1
    assert stopped['families'][1]['real']['completed'] == 0
    assert stopped['consensus']['real']['completed'] == 0
    assert len(stopped['pending_case_ids']) == 2
    probe.run_probe()
    assert len(transport_mock['requests']) == 1
    assert probe.read(probe.RUN / 'result.json')['rows'][0]['models']


def test_malformed_native_call_is_unknown_without_http(transport_mock, monkeypatch):
    value = frozen([case(malformed=True)])
    monkeypatch.setattr(probe, 'verify', lambda: value)
    report = probe.run_probe()
    assert report['complete'] and not transport_mock['requests']
    assert report['consensus']['real']['UNKNOWN'] == 1
    assert all(family['real']['UNKNOWN'] == 1 and family['outcomes'] == {'NOT_CALLED_MALFORMED_TARGET': 1}
               for family in report['families'])


def test_m1_removes_approval_user_blocks_preserves_initial_request_target_and_offsets():
    original = case()
    original['row']['response'] = ('⟦ASSISTANT⟧\nI will now apply amount 2 to record X.\n'
                                  '⟦USER⟧\nYes, go ahead.\n→ TOOL_CALL apply_a: {"record_id":"X","amount":2}')
    source = probe.SourceStore(original['row'])
    original['target'] = {'source_id': 't2', 'tool': 'apply_a', 'arguments': {'record_id': 'X', 'amount': 2}}
    mutant, target, removed = probe.m1_mutant(original)
    assert removed == ['h3', 't1']
    assert 'Help with record X.' in mutant.raw['prompt']
    assert 'Yes' not in mutant.raw['prompt'] + mutant.raw['response']
    assert target['source_id'] == 't1' and target['arguments'] == original['target']['arguments']
    assert mutant.text(target['source_id']) == source.text(original['target']['source_id'])
    assert all(mutant.raw[item['document']][item['start']:item['end']]
               for item in mutant.sources.values() if item['kind'] != 'raw')


def test_synthetic_wrong_true_false_separate_and_local_false_scope():
    cases = [{'expected': 'UNRESOLVED'}, {'expected': 'TRUE'},
             {'expected': 'TRUE', 'source_qualified_expected': 'UNRESOLVED'}]
    pairs = [(cases[0], {'value': 'TRUE', 'reason': 'incorrect'}),
             (cases[1], {'value': 'FALSE', 'reason': 'local_absence', 'scope': 'LOCAL_PROPOSAL_ONLY'}),
             (cases[2], {'value': 'UNRESOLVED', 'reason': 'parameters_missing'})]
    historical = probe.synthetic_metrics(pairs, 3)
    qualified = probe.synthetic_metrics(pairs, 3, expectation_field='source_qualified_expected')
    assert historical['wrong_TRUE'] == 1 and historical['wrong_FALSE'] == 1
    assert historical['correct'] == 0 and qualified['correct'] == 1
    assert historical['FALSE_by_scope'] == {'LOCAL_PROPOSAL_ONLY': 1}


def test_score_refuses_empty_report_overwrite(transport_mock, monkeypatch):
    value = frozen([case()])
    monkeypatch.setattr(probe, 'verify', lambda: value)
    probe.run_probe()
    previous = (probe.RUN / 'score.json').read_bytes()
    result = probe.read(probe.RUN / 'result.json')
    result['rows'] = []
    probe.write(probe.RUN / 'result.json', result)
    with pytest.raises(ValueError, match='empty_result_would_overwrite_report'):
        probe.score()
    assert (probe.RUN / 'score.json').read_bytes() == previous
