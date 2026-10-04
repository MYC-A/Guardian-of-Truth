"""Adversarial structural checks using supplied interpretations, not model scores."""
from copy import deepcopy
import json

import pytest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

from guardian_truth.evidence_graph import EvidenceGraph
from guardian_truth.evidence_graph.facts import compare
from guardian_truth.evidence_graph.logic import evaluate, evaluate_requirement
from guardian_truth.source_search.store import SourceStore


def graph(policy='A change requires approval.', *, history='', response=None, **options):
    prompt = ('\u27e6SYSTEM\u27e7\n' + policy + '\n[AVAILABLE TOOLS]\n'
        '- inspect_entry \u2014 retrieve entry data without modifying it\n    entry_id: string!\n'
        '- apply_entry \u2014 change entry data\n    entry_id: string!\n    amount: number!\n'
        + '\u27e6USER\u27e7\nHelp me.\n' + history)
    response = response or '\u2192 TOOL_CALL apply_entry: {"entry_id":"E-17","amount":999}'
    return EvidenceGraph(SourceStore({'prompt': prompt, 'response': response}), **options)


def span(g, sid, needle=None):
    text = g.text(sid)
    start = text.index(needle) if needle else 0
    return {'source_id': sid, 'start': start, 'end': start + len(needle) if needle else len(text)}


def atom(label='approval', spans=None, op='ATOM'):
    return {'op': op, 'label': label, 'spans': spans or [], 'children': []}


def requirement(g, uid=None, *, local_id='r0', condition=None, guard=None, exceptions=None, opened=None):
    uid = uid or next(iter(g.units))
    s = span(g, uid)
    return {'local_id': local_id, 'action': 'change stored data', 'action_spans': [s],
        'scope': 'the assistant performing a change', 'source_spans': [s], 'modality': 'REQUIRE',
        'condition': condition or atom(spans=[s]), 'guard': guard,
        'exceptions': exceptions or [], 'open_questions': opened or []}


def seed(g, requirements=None):
    jobs = g.initial_jobs()
    uid = next(iter(g.units))
    for j in jobs:
        p = j['packet']
        if j['task'] == 'INVENTORY':
            response = {'unit_id': p['unit_id'], 'status': 'REVIEWED', 'reason': 'Supplied test interpretation',
                        'requirements': (requirements or [requirement(g)]) if p['unit_id'] == uid else []}
        else:
            response = {'tool': p['tool'], 'effect': 'MODIFY', 'action': 'change stored data',
                        'object_type': 'entry', 'object_spans': [span(g, g.declarations[p['tool']])],
                        'spans': [span(g, g.declarations[p['tool']])], 'reason': 'Supplied interpretation'}
        assert g.admit(j['id'], response)['valid']


def link(g, status='APPLIES'):
    for j in g.link_jobs():
        p = j['packet']
        response = {'target_id': p['target_id'], 'requirement_id': p['requirement_id'],
            'status': status, 'policy_spans': p['requirement']['source_spans'],
            'declaration_spans': [span(g, p['declaration_id'])], 'reason': 'Supplied scope interpretation'}
        assert g.admit(j['id'], response)['valid']


def witness(g, j, *, value='UNKNOWN', evidence=None, reads=None, check=None):
    p = j['packet']
    return {'target_id': p['target_id'], 'requirement_id': p['requirement_id'], 'leaf_id': p['leaf_id'],
            'value': value, 'evidence': evidence or [], 'read_requests': reads or [],
            'check': check, 'reason': 'Supplied test witness'}


def native(sid, pointer):
    return {'kind': 'NATIVE_JSON', 'source_id': sid, 'pointer': pointer, 'literal_span': None}


def literal(g, text='70'):
    return {'kind': 'SOURCE_LITERAL', 'source_id': 'h0', 'pointer': None,
            'literal_span': span(g, 'h0', text)}


def numeric_check(g, sid, path='/record/load', bindings=None):
    return {'lhs': native(sid, path), 'operator': '<', 'rhs': literal(g),
            'bindings': bindings if bindings is not None else [
                {'target_pointer': '/entry_id', 'source_pointer': '/record/entry_id'}]}


def receipts(value, *, call='{"entry_id":"E-17"}'):
    return ('\u27e6ASSISTANT\u27e7\n\u2192 TOOL_CALL inspect_entry: ' + call + '\n'
            '\u2190 TOOL_RESPONSE inspect_entry: ' + json.dumps(value) + '\n')


def result_sid(g, *, last=False):
    ids = [sid for sid, s in g.store.sources.items() if s['kind'] == 'result']
    return ids[-1] if last else ids[0]


def test_entire_system_text_after_catalog_is_preserved_unicode_and_long_lines():
    g = graph('Before\n' + '\u0436' * 300, chunk_chars=64)
    # Append a policy instruction after all declarations in the same system event.
    row = dict(g.store.raw)
    row['prompt'] = row['prompt'].replace('\u27e6USER\u27e7', 'After catalog: never alter archived entries.\n\u27e6USER\u27e7', 1)
    g = EvidenceGraph(SourceStore(row), chunk_chars=64)
    assert ''.join(g.text(uid) for uid in g.units) == g.store.text('h0')
    assert 'After catalog: never alter archived entries.' in ''.join(g.text(uid) for uid in g.units)
    assert g.report()['source_span_coverage'] == 1
    assert g.report()['semantic_completeness_proven'] is False


def test_reverse_sweep_does_not_depend_on_lexical_top_k():
    g = graph('Arbiter pluvial xerus.\n' + 'Unrelated source sentence.\n' * 20, chunk_chars=64)
    seed(g)
    assert len(g.link_jobs(bidirectional=False, forward_limit=0)) == 0
    assert len(g.link_jobs(bidirectional=True)) == len(g.requirements) * len(g.targets)
    assert g.report()['open_requirements']


def test_target_and_original_declaration_are_supplied_and_link_packet_does_not_mutate():
    g = graph()
    seed(g)
    jobs = deepcopy(g.link_jobs())
    assert jobs[0]['packet']['target']['tool'] == 'apply_entry'
    assert 'change entry data' in str(jobs[0]['packet']['fragments'])
    link(g)
    assert g.jobs[jobs[0]['id']] == jobs[0]
    assert [j['id'] for j in g.link_jobs()] == [j['id'] for j in jobs]
    assert not any(j['task'] == 'LINK' for j in g.pending_jobs())


def test_invalid_spans_are_retained_as_failure_and_unreviewed_unit():
    g = graph()
    j = next(j for j in g.initial_jobs() if j['task'] == 'INVENTORY')
    r = requirement(g)
    r['source_spans'][0]['end'] += 50000
    reply = {'unit_id': j['packet']['unit_id'], 'status': 'REVIEWED', 'reason': 'test', 'requirements': [r]}
    assert not g.admit(j['id'], reply)['valid']
    assert g.report()['units_reviewed'] == 0
    assert g.report()['targets'][0]['candidate_decision'] == 'UNKNOWN'
    assert g.report()['failed_jobs']


def test_unresolved_obligation_cannot_disappear_through_not_applicable_link():
    g = graph()
    s = span(g, next(iter(g.units)))
    seed(g, [requirement(g, condition=atom('unresolved antecedent', [s], 'UNKNOWN'),
                          opened=['shared applicability condition unresolved'])])
    link(g, 'DOES_NOT_APPLY')
    report = g.report()
    assert report['open_requirements']
    assert report['targets'][0]['candidate_decision'] == 'UNKNOWN'
    assert any(o['cause'] == 'UNRESOLVED_REQUIREMENT' for o in report['targets'][0]['open'])


@pytest.mark.parametrize('op,values,expected', [('AND', ['TRUE','UNKNOWN'], 'UNKNOWN'),
    ('AND',['FALSE','UNKNOWN'],'FALSE'), ('OR',['TRUE','UNKNOWN'],'TRUE'),
    ('OR',['FALSE','UNKNOWN'],'UNKNOWN'), ('OR',['FALSE','FALSE'],'FALSE')])
def test_boolean_operators_keep_their_original_formula(op, values, expected):
    f = {'op': op, 'label': 'source relation', 'spans': [], 'children': [atom(), atom()]}
    assert evaluate(f, {f'condition.{i}': {'value': v, 'reason': 'test'}
                        for i, v in enumerate(values)})['value'] == expected


def test_exception_for_one_obligation_does_not_suppress_another_and_unknown_is_open():
    g = graph()
    s = span(g, next(iter(g.units)))
    a = requirement(g, exceptions=[atom('exemption A', [s])])
    b = requirement(g, local_id='r1')
    true_exception = {'condition': {'value': 'FALSE'}, 'exception.0': {'value': 'TRUE'}}
    assert evaluate_requirement(a, true_exception)['status'] == 'NOT_TRIGGERED'
    assert evaluate_requirement(b, true_exception)['status'] == 'VIOLATED'
    assert evaluate_requirement(a, {'condition': {'value': 'FALSE'}})['status'] == 'UNKNOWN'
    b['guard'] = atom('unknown guard', [s])
    assert evaluate_requirement(b, {'condition': {'value': 'FALSE'}})['status'] == 'UNKNOWN'


def test_permission_condition_is_not_reinterpreted_as_prohibition():
    g = graph()
    r = requirement(g)
    r['modality'] = 'PERMIT'
    assert evaluate_requirement(r, {'condition': {'value': 'FALSE'}})['status'] == 'UNKNOWN'


def test_full_history_is_addressable_and_rereads_have_explicit_budget_cause():
    history = '\u27e6ASSISTANT\u27e7\nPropose operation on E-17 for amount 2.\n\u27e6USER\u27e7\nYes.\n'
    history += '\u27e6ASSISTANT\u27e7\nLater unrelated text.\n' * 12
    g = graph(history=history, witness_sources=1, max_rereads=0)
    seed(g)
    link(g)
    j = g.witness_jobs()[0]
    old_sid = next(sid for sid,s in g.store.sources.items() if s['kind'] != 'raw' and 'Propose operation' in g.text(sid))
    assert old_sid in {r['source_id'] for r in j['packet']['source_registry']}
    assert g.admit(j['id'], witness(g, j, reads=[span(g, old_sid)]))['valid']
    assert not g.witness_jobs()
    assert any(o['cause'] == 'READ_BUDGET_EXHAUSTED' for o in g.report()['targets'][0]['open'])


def test_reread_returns_exact_original_text_and_does_not_duplicate_the_first_job():
    g = graph(history='\u27e6ASSISTANT\u27e7\nAn old distinct proposal.\n', witness_sources=1)
    seed(g)
    link(g)
    j = g.witness_jobs()[0]
    sid = next(sid for sid,s in g.store.sources.items() if s['kind'] != 'raw' and 'An old distinct' in g.text(sid))
    assert g.admit(j['id'], witness(g, j, reads=[span(g, sid)]))['valid']
    next_job = g.witness_jobs()[0]
    assert next_job['id'] != j['id'] and next_job['packet']['round'] == 1
    assert any(f['text'] == g.text(sid) for f in next_job['packet']['fragments'])


def test_future_result_and_unseen_quote_are_rejected():
    response = ('\u2192 TOOL_CALL apply_entry: {"entry_id":"E-17","amount":999}\n'
                '\u2190 TOOL_RESPONSE apply_entry: {"ok":true}')
    g = graph(response=response)
    seed(g)
    link(g)
    j = g.witness_jobs()[0]
    assert not g.admit(j['id'], witness(g, j, value='TRUE', evidence=[span(g, 't1')]))['valid']


def test_native_numeric_comparison_and_parent_binding():
    g = graph('The threshold is 70.', history=receipts({'record': {'entry_id':'E-17','load':75}}))
    result = compare(g, 't0', numeric_check(g, result_sid(g)))
    assert result['value'] == 'FALSE'
    assert result['assurance'] == 'CODE_CHECKED_NATIVE_FACT_NOT_POLICY_MEANING'
    assert result['left'] == 75 and result['right'] == 70


@pytest.mark.parametrize('value,path,binding,cause', [
    ({'entry_id':'OTHER','record':{'entry_id':'E-17','load':20}}, '/record/load', '/record/entry_id',
     'PARENT_ENTITY_CONTRADICTION'),
    ({'records':[{'entry_id':'E-17','load':20},{'entry_id':'OTHER','load':20}]},
     '/records/1/load','/records/0/entry_id','JOIN_OUTSIDE_SELECTED_RECORD_LINEAGE'),
    ({'record':{'entry_id':'OTHER','load':20}},'/record/load','/record/entry_id','ENTITY_JOIN_MISMATCH'),
])
def test_wrong_parent_and_sibling_facts_never_satisfy_target(value, path, binding, cause):
    g = graph('The threshold is 70.', history=receipts(value))
    check = numeric_check(g, result_sid(g), path,
        [{'target_pointer':'/entry_id','source_pointer':binding}])
    result = compare(g, 't0', check)
    assert result['value'] == 'UNKNOWN' and result['cause'] == cause


def test_latest_invalid_receipt_prevents_reusing_old_success():
    history = receipts({'record': {'entry_id':'E-17','load':20}})
    history += '\u2192 TOOL_CALL inspect_entry: {"entry_id":"E-17"}\n\u2190 TOOL_RESPONSE inspect_entry: not JSON\n'
    g = graph('The threshold is 70.', history=history)
    assert compare(g, 't0', numeric_check(g, result_sid(g)))['cause'] == 'OBSERVATION_SUPERSEDED_BY_LATER_RESULT'


def test_ambiguous_result_and_unspecified_entity_join_remain_unknown():
    h = '\u27e6ASSISTANT\u27e7\n\u2192 TOOL_CALL inspect_entry: {"entry_id":"E-17"}\n'
    h += '\u2192 TOOL_CALL inspect_entry: {"entry_id":"E-18"}\n'
    h += '\u2190 TOOL_RESPONSE inspect_entry: {"record":{"entry_id":"E-17","load":20}}\n'
    g = graph('The threshold is 70.', history=h)
    assert compare(g, 't0', numeric_check(g, result_sid(g)))['cause'] == 'RESULT_WITHOUT_UNIQUE_VALID_PRIOR_CALL'
    g = graph('The threshold is 70.', history=receipts({'record':{'entry_id':'E-17','load':20}}))
    assert compare(g, 't0', numeric_check(g, result_sid(g), bindings=[]))['cause'] == 'OBSERVATION_ENTITY_JOIN_UNSPECIFIED'


def test_consent_on_2_cannot_be_code_bound_to_target_999_or_fact_question():
    g = graph(history='\u27e6ASSISTANT\u27e7\nIs entry E-17 amount 2?\n\u27e6USER\u27e7\nYes.\n')
    sid = next(sid for sid, s in g.store.sources.items() if s['role'] == 'user')
    check = {'lhs':native(sid,''),'operator':'==','rhs':native('t0','/amount'),'bindings':[]}
    assert compare(g, 't0', check)['value'] == 'UNKNOWN'
    # No policy literal 2 exists: prose values are not manufactured native facts.
    with pytest.raises(ValueError):
        literal(g,'2')


@pytest.mark.parametrize('payload', ['[]', 'null', '{"entry_id":"E-17","entry_id":"E-18"}'])
def test_malformed_supporting_call_cannot_ground_temporal_position(payload):
    g = graph(history='\u27e6ASSISTANT\u27e7\n\u2192 TOOL_CALL inspect_entry: ' + payload + '\n',
              witness_sources=40)
    seed(g)
    link(g)
    j = g.witness_jobs()[0]
    sid = next(sid for sid, s in g.store.sources.items() if s['document']=='prompt' and s['kind']=='call')
    assert g.admit(j['id'], witness(g, j, value='TRUE', evidence=[span(g,sid)]))['valid']
    reply = next(iter(g.witnesses.values()))[-1]
    assert reply['position'] is None


def test_temporal_relation_requires_two_actual_positions():
    f = {'op':'BEFORE','label':'A before B','spans':[],'children':[atom(),atom()]}
    assert evaluate(f, {'condition.0':{'value':'TRUE'},'condition.1':{'value':'TRUE'}})['value'] == 'UNKNOWN'
    assert evaluate(f, {'condition.0':{'value':'TRUE','position':2},
                        'condition.1':{'value':'TRUE','position':1}})['value'] == 'FALSE'


def test_bfs_and_dfs_return_same_reachable_nodes_and_keep_limits_visible():
    g = graph(chunk_chars=64)
    root = next(iter(g.units))
    bfs = g.traverse(root, strategy='BFS', max_depth=30, max_nodes=200)
    dfs = g.traverse(root, strategy='DFS', max_depth=30, max_nodes=200)
    assert {n['node_id'] for n in bfs['items']} == {n['node_id'] for n in dfs['items']}
    assert g.traverse(root, max_nodes=1)['was_truncated']
    assert 'NOT_SATISFACTION' in bfs['interpretation']


def test_resolved_model_witness_remains_shadow_and_no_missing_unit_is_hidden():
    g = graph(witness_sources=40)
    seed(g)
    link(g)
    j = g.witness_jobs()[0]
    assert g.admit(j['id'], witness(g, j, value='FALSE', evidence=[span(g,'t0')]))['valid']
    target = g.report()['targets'][0]
    assert target['candidate_decision'] == 'ERROR'
    assert target['mode'] == 'SHADOW_MODEL_SEMANTICS' and target['code_proof'] is False
    assert not g.report()['semantic_completeness_proven']


def test_returned_jobs_are_detached_and_source_mutation_is_detected():
    g = graph()
    j = g.initial_jobs()[0]
    before = deepcopy(g.jobs[j['id']])
    j['packet']['fragments'][0]['text'] = 'invented'
    assert g.jobs[j['id']] == before
    g.store.raw['prompt'] += 'changed input'
    with pytest.raises(ValueError, match='SOURCE_OR_NATIVE_PARSE_CHANGED'):
        g.report()


def test_prior_call_identity_bindings_are_checked_too():
    g = graph('Threshold is 70.', history='\u27e6ASSISTANT\u27e7\n'
        '\u2192 TOOL_CALL inspect_entry: {"entry_id":"OTHER","amount":2}\n')
    sid = next(sid for sid,s in g.store.sources.items() if s['document']=='prompt' and s['kind']=='call')
    check = numeric_check(g, sid, '/amount', [{'target_pointer':'/entry_id','source_pointer':'/entry_id'}])
    assert compare(g, 't0', check)['cause'] == 'ENTITY_JOIN_MISMATCH'


def test_newer_other_entity_does_not_supersede_the_bound_observation():
    history = receipts({'record':{'entry_id':'E-17','load':20}})
    history += receipts({'record':{'entry_id':'OTHER','load':90}}, call='{"entry_id":"OTHER"}')
    g = graph('Threshold is 70.', history=history)
    assert compare(g, 't0', numeric_check(g, result_sid(g)))['value'] == 'TRUE'


def test_automatic_native_json_read_is_explicit_in_fact_trace():
    g = graph('Threshold is 70.', history=receipts({'padding':'x'*5000,
        'record':{'entry_id':'E-17','load':20}}))
    sid = result_sid(g)
    result = compare(g, 't0', numeric_check(g,sid))
    assert result['value'] == 'TRUE'
    read = result['code_source_reads'][0]
    assert read['read_by_code'] == 'FULL_NATIVE_JSON_RECORD'
    assert read['pointer'] == '/record/load' and read['value'] == 20
    assert read['end'] - read['start'] > 5000


def test_numeric_witness_value_is_recomputed_instead_of_believing_model():
    g = graph('The threshold is 70.', witness_sources=40)
    seed(g)
    link(g)
    j = g.witness_jobs()[0]
    check = {'lhs':native('t0','/amount'),'operator':'<','rhs':literal(g),'bindings':[]}
    assert g.admit(j['id'], witness(g,j,value='TRUE',evidence=[span(g,'t0')],check=check))['valid']
    result = next(iter(g.witnesses.values()))[-1]
    assert result['model_value'] == 'TRUE' and result['value'] == 'FALSE'
    assert g.report()['targets'][0]['candidate_decision'] == 'ERROR'
    assert g.report()['targets'][0]['code_proof'] is False


def test_unrelated_policy_threshold_is_not_borrowed_by_this_requirement():
    g = graph('The threshold is 70. Another independent threshold is 99.', witness_sources=40)
    s = span(g,'h0','The threshold is 70.')
    r = requirement(g, condition=atom(spans=[s]))
    # Broad parent context contains both constants; only this leaf owns 70.
    seed(g,[r])
    link(g)
    j = g.witness_jobs()[0]
    check = {'lhs':native('t0','/amount'),'operator':'<','rhs':literal(g,'99'),'bindings':[]}
    result = g.admit(j['id'], witness(g,j,value='FALSE',evidence=[span(g,'t0')],check=check))
    assert not result['valid'] and result['cause'] == 'POLICY_LITERAL_NOT_OWNED_BY_ATOMIC_CONDITION'


def test_native_fact_does_not_accept_boolean_number_type_substitution():
    g = graph('The threshold is 70.', history=receipts({'record':{'entry_id':'E-17','load':True}}))
    result = compare(g,'t0',numeric_check(g,result_sid(g)))
    assert result['value'] == 'UNKNOWN' and result['cause'] == 'ORDER_COMPARISON_NEEDS_NUMBERS'


def test_native_source_metadata_mutation_cannot_change_provenance_silently():
    g = graph('Threshold is 70.', history=receipts({'record':{'entry_id':'E-17','load':20}}))
    sid = result_sid(g)
    g.store.sources[sid]['start'] += 1
    assert compare(g,'t0',numeric_check(g,sid))['cause'] == 'SOURCE_OR_NATIVE_PARSE_CHANGED'


def test_native_observation_can_be_compared_to_actual_target_arguments():
    g = graph('Threshold is 70.',history=receipts({'record':{'entry_id':'E-17','load':20}}))
    check = numeric_check(g,result_sid(g))
    check['rhs'] = native('t0','/amount')
    assert compare(g,'t0',check)['value'] == 'TRUE'


def test_omitted_parent_join_cannot_hide_a_known_contradictory_parent():
    history = receipts({'scope_id':'OTHER_SCOPE','record':{'entry_id':'E-17','load':20}})
    response = '\u2192 TOOL_CALL apply_entry: {"entry_id":"E-17","amount":999,"scope_id":"OWN_SCOPE"}'
    g = graph('Threshold is 70.',history=history,response=response)
    result = compare(g,'t0',numeric_check(g,result_sid(g)))
    assert result['value'] == 'UNKNOWN' and result['cause'] == 'COMMON_PARENT_FIELD_CONTRADICTION'


def offline_module():
    path = Path(__file__).resolve().parents[1] / 'experiments/searh_23/evidence_graph_v1/offline.py'
    spec = spec_from_file_location('evidence_graph_offline_test',path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_prepare_and_replay_deduplicate_without_inventing_model_answers(tmp_path):
    m = offline_module()
    input_path = tmp_path / 'inputs.jsonl'
    raw = graph().store.raw
    input_path.write_text(''.join(json.dumps({'id':str(i),**raw})+'\n' for i in range(2)),encoding='utf-8')
    args = SimpleNamespace(inputs=input_path,out=tmp_path/'out',chunk_chars=2400,strategy='BFS',
                           model='NOT_SELECTED_NO_API_AUTHORIZATION',cache=None,arm='bidirectional')
    prepared = m.prepare(args)
    assert prepared['logical_jobs'] == 4 and prepared['unique_requests'] == 2
    result = m.replay(args)
    assert result['candidate_decisions'] == {'UNKNOWN':2}
    assert result['new_http_attempts'] == 0 and result['cached_requests_admitted_or_rejected'] == 0
    assert not result['model_quality_measured']


def test_old_or_wrong_model_cache_is_rejected(tmp_path):
    m = offline_module()
    input_path = tmp_path / 'inputs.jsonl'
    input_path.write_text(json.dumps({'id':'one',**graph().store.raw})+'\n',encoding='utf-8')
    args = SimpleNamespace(inputs=input_path,out=tmp_path/'out',chunk_chars=2400,strategy='BFS',
                           model='selected-model',cache=tmp_path/'cache',arm='bidirectional')
    m.prepare(args)
    args.cache.mkdir()
    protocol = m.read(args.out/'protocol.json')
    m.write(args.cache/'wrong.json',{'protocol_sha256':protocol['protocol_sha256'],
        'request_sha256':'unused','model_id':'other-model','reply':{}})
    with pytest.raises(ValueError,match='protocol/model mismatch'):
        m.replay(args)


def test_code_hashes_are_portable_but_raw_input_hashes_remain_exact(tmp_path):
    m = offline_module()
    win, linux = tmp_path/'win.py', tmp_path/'linux.py'
    win.write_bytes(b'a\r\nb\r\n')
    linux.write_bytes(b'a\nb\n')
    assert m.canonical_source_sha(win) == m.canonical_source_sha(linux)
    assert m.sha(win) != m.sha(linux)
