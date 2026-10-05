"""Contract tests for the public integrated API (mocked model adapter, label-free fixtures)."""
import json
import socket
import subprocess
import sys

import pytest

from guardian_truth.integrated import ReviewConfig, StaticClient, Transport, NetworkTripwire, review
from guardian_truth.integrated import relations, reviewer
from guardian_truth.integrated.transport import sha
from guardian_truth.source_search.store import SourceStore


def call(tool, args):
    return '\t→ TOOL_CALL ' + tool + ': ' + json.dumps(args, separators=(',', ':')) + '\n'


def result(tool, values, status=None):
    tag = f' [{status}]' if status else ''
    return f'\t← TOOL_RESPONSE {tool}{tag}: ' + (values if isinstance(values, str) else json.dumps(values, separators=(',', ':'))) + '\n'


POLICY = ('Order desk: cancel_order requires that the user confirmed the order id in this conversation. '
          'Never cancel an order that is already delivered.')
TOOLS = ('- get_order — Read one order.\n    order_id: string! — Order id.\n'
         '- cancel_order — Cancel one order.\n    order_id: string! — Order id.\n    reason: string! [enum: no_longer_needed | ordered_by_mistake] — Reason.\n')


def row(response, history=None, user='Please cancel my order W1234567, I no longer need it.'):
    history = history if history is not None else (
        '⟦ASSISTANT · ход 1⟧\n' + call('get_order', {'order_id': 'W1234567'}) +
        result('get_order', {'order_id': 'W1234567', 'status': 'pending'}))
    prompt = ('⟦SYSTEM⟧\n<policy>\n' + POLICY + '\n</policy>\n\n[AVAILABLE TOOLS]\n' + TOOLS + '\n'
              '⟦USER⟧\n' + user + '\n' + history)
    return dict(prompt=prompt, response='⟦ASSISTANT · ход 2⟧\n' + response)


def reply(decision, target='t0', norm=None, evidence=(), questions=()):
    def fn(req):
        pk = json.loads(req['messages'][1]['content'])
        n = norm or pk['normative_sources'][0]['source_id']
        ev = [dict(source_id=s, actor=reviewer.sources(pk)[s]['role'], role='x', fact='f') for s in evidence] or (
            [dict(source_id=pk['current_targets'][0]['source_id'], actor='assistant', role='move', fact='f')] if decision == 'ERROR' else [])
        return json.dumps(dict(regulated_action=dict(target_id=target, description='d'),
                               applicable_norms=[dict(policy_source_id=n, interpretation='i', modality='FORBID')] if decision == 'ERROR' else [],
                               supporting_evidence=ev, exception_analysis='', reason='r', open_questions=list(questions),
                               decision=decision))
    return fn


GOOD = call('cancel_order', {'order_id': 'W1234567', 'reason': 'no_longer_needed'})


def test_error_reply_projects_to_one_as_model_hypothesis():
    r = row(GOOD)
    res = review(r['prompt'], r['response'], ReviewConfig.profile('baseline'), client=StaticClient(reply('ERROR')))
    assert (res['binary'], res['final_decision'], res['proof_status'], res['projection']) == (1, 'ERROR', 'MODEL_HYPOTHESIS', 'ERROR')
    assert res['checked_targets'][0]['tool'] == 'cancel_order'


def test_unknown_and_technical_null_are_distinct_zero_projections():
    r = row(GOOD)
    unk = review(r['prompt'], r['response'], ReviewConfig.profile('baseline'), client=StaticClient(reply('UNKNOWN')))
    bad = review(r['prompt'], r['response'], ReviewConfig.profile('baseline'), client=StaticClient(lambda q: 'not json'))
    none = review(r['prompt'], r['response'], ReviewConfig.profile('baseline'), client=StaticClient(lambda q: None))
    assert (unk['binary'], unk['projection']) == (0, 'UNKNOWN_PROJECTED_0')
    assert (bad['binary'], bad['projection'], bad['steps'][0]['admission']) == (0, 'TECHNICAL_NULL_PROJECTED_0', 'INVALID_JSON')
    assert none['steps'][0]['admission'] == 'TRANSPORT_FAILURE' and none['projection'] == 'TECHNICAL_NULL_PROJECTED_0'


def test_single_fenced_reply_is_admitted_and_recorded():
    r = row(GOOD)
    fenced = lambda q: '```json\n' + reply('NO_ERROR')(q) + '\n```'
    res = review(r['prompt'], r['response'], ReviewConfig.profile('baseline'), client=StaticClient(fenced))
    assert res['final_decision'] == 'NO_ERROR' and res['steps'][0]['normalization'] == 'FENCE_STRIPPED'
    two = lambda q: '```json\n{}\n```\n```json\n{}\n```'
    assert review(r['prompt'], r['response'], ReviewConfig.profile('baseline'), client=StaticClient(two))['final_decision'] is None


def test_foreign_source_id_and_empty_accusation_are_rejected():
    r = row(GOOD)
    res = review(r['prompt'], r['response'], ReviewConfig.profile('baseline'), client=StaticClient(reply('ERROR', target='t9')))
    assert res['steps'][0]['admission'].startswith('REJECTED') and res['binary'] == 0

    def empty(q):
        v = json.loads(reply('ERROR')(q)); v['applicable_norms'] = []
        return json.dumps(v)
    assert 'EMPTY_ACCUSATION' in review(r['prompt'], r['response'], ReviewConfig.profile('baseline'),
                                        client=StaticClient(empty))['steps'][0]['admission']


def test_guard_proof_overrides_model_only_when_enabled():
    bad = call('cancel_order', {'order_id': 'W1234567', 'reason': 'changed_mind'})
    r = row(bad)
    on = review(r['prompt'], r['response'], ReviewConfig.profile('guard'), client=StaticClient(reply('NO_ERROR')))
    off = review(r['prompt'], r['response'], ReviewConfig.profile('baseline'), client=StaticClient(reply('NO_ERROR')))
    assert (on['binary'], on['proof_status'], on['decision_owner']) == (1, 'MECHANICAL_PROOF', 'guard')
    assert on['model_decision'] == 'NO_ERROR'                       # the model hypothesis is preserved, not overwritten
    assert off['binary'] == 0 and off['guard']['established_error'] and not off['guard']['applied']


def test_relation_facts_scope_and_status():
    observed = relations.compute(SourceStore(row(GOOD)))
    a = [f for f in observed['facts'] if f['kind'] == 'ARG_VALUE_PROVENANCE']
    assert a and a[0]['relation'] == 'OBSERVED_BEFORE_MOVE' and not a[0]['decisive']
    unseen = relations.compute(SourceStore(row(call('cancel_order', {'order_id': 'W7654321', 'reason': 'no_longer_needed'}))))
    f = [x for x in unseen['facts'] if x['kind'] == 'ARG_VALUE_PROVENANCE'][0]
    assert f['relation'] == 'NOT_OBSERVED_IN_EARLIER_RECORD' and f['decisive'] and f['status'] == 'SOURCE_OBSERVATION'
    # policy-only mention is not user/tool provenance
    sys_only = relations.compute(SourceStore(row(call('get_order', {'order_id': 'W1234567'}), history='',
                                                 user='Hi, check my order please.')))
    assert all(x['relation'] != 'OBSERVED_BEFORE_MOVE' for x in sys_only['facts'] if x['kind'] == 'ARG_VALUE_PROVENANCE')


def test_error_receipt_and_repeated_call_relations():
    hist = '⟦ASSISTANT · ход 1⟧\n' + call('get_order', {'order_id': 'W1234567'}) + result('get_order', '{"error":"timeout"}', 'ERROR')
    rel = relations.compute(SourceStore(row(call('get_order', {'order_id': 'W1234567'}), history=hist)))
    kinds = {f['kind']: f for f in rel['facts']}
    assert kinds['PRIOR_ERROR_RECEIPT']['decisive'] and kinds['REPEATED_CALL']['earlier_receipt_status'] == 'ERROR'


def test_prose_value_shadow_is_never_decisive():
    rel = relations.compute(SourceStore(row('Your refund of 987.65 is on its way.\n')))
    p = [f for f in rel['facts'] if f['kind'] == 'PROSE_VALUE_NOT_OBSERVED']
    assert p and not any(f['decisive'] for f in p)


def test_metamorphic_consistent_rename_preserves_relation_types():
    a = row(call('cancel_order', {'order_id': 'W7654321', 'reason': 'no_longer_needed'}))
    b = {k: v.replace('W1234567', 'Q9988776').replace('W7654321', 'Q1122334') for k, v in a.items()}
    sig = lambda r: [(f['kind'], f.get('relation'), f['decisive']) for f in relations.compute(SourceStore(r))['facts']]
    assert sig(a) == sig(b)


def test_relations_profile_adds_cited_spans_and_facts_to_request():
    r = row(call('cancel_order', {'order_id': 'W7654321', 'reason': 'no_longer_needed'}))
    cl = StaticClient(reply('NO_ERROR'))
    review(r['prompt'], r['response'], ReviewConfig.profile('relations'), client=cl)
    data = json.loads(cl.calls[0]['request']['messages'][1]['content'])
    assert data['relation_facts'] and reviewer.RELATIONS_ADDENDUM in cl.calls[0]['request']['messages'][0]['content']


def test_controller_is_conditional_and_bounded():
    unseen = row(call('cancel_order', {'order_id': 'W7654321', 'reason': 'no_longer_needed'}))
    cl = StaticClient(reply('NO_ERROR'))
    res = review(unseen['prompt'], unseen['response'], ReviewConfig.profile('integrated'), client=cl)
    assert len(cl.calls) == 2 and res['steps'][1]['trigger'] == 'NO_ERROR_WITH_DECISIVE_RELATION_FACTS'
    assert 'verification_checklist' in json.loads(cl.calls[1]['request']['messages'][1]['content'])
    clean = row(GOOD)
    cl2 = StaticClient(reply('NO_ERROR'))
    review(clean['prompt'], clean['response'], ReviewConfig.profile('integrated'), client=cl2)
    assert len(cl2.calls) == 1                                      # no decisive facts, decided -> no pass
    cl3 = StaticClient(lambda q: 'garbage')
    review(clean['prompt'], clean['response'], ReviewConfig.profile('integrated'), client=cl3)
    assert len(cl3.calls) == 1                                      # technical failure is never retried


def test_controller_rejected_second_stage_falls_back_to_first():
    r = row(GOOD)
    answers = iter([reply('UNKNOWN', questions=['q']), lambda q: 'garbage'])
    res = review(r['prompt'], r['response'], ReviewConfig.profile('integrated'), client=StaticClient(lambda q: next(answers)(q)))
    assert res['final_decision'] == 'UNKNOWN' and res['decision_owner'] == 'review'
    assert res['steps'][0]['fallback_after'] == 'controller_INVALID_JSON'


def test_no_label_or_row_id_is_an_input():
    import inspect
    assert list(inspect.signature(review).parameters) == ['prompt', 'response', 'config', 'client']


def test_crlf_input_runs_end_to_end():
    r = {k: v.replace('\n', '\r\n') for k, v in row(GOOD).items()}
    res = review(r['prompt'], r['response'], ReviewConfig.profile('integrated'), client=StaticClient(reply('NO_ERROR')))
    assert res['final_decision'] in ('NO_ERROR', 'UNKNOWN', None)


# ------------------------------------------------------------------ transport

def fake_sender(content='{"ok":1}', fail=False):
    sent = []

    def send(url, key, payload, timeout=None):
        sent.append(payload)
        if fail:
            return None, dict(status=503, seconds=0.0)
        return dict(model=payload['model'], choices=[dict(message=dict(content=content), finish_reason='stop')],
                    usage=dict(prompt_tokens=10, completion_tokens=2, total_tokens=12)), dict(status=200, seconds=0.01)
    return send, sent


def test_transport_exact_cache_offline_tripwire_and_budget_resume(tmp_path):
    send, sent = fake_sender()
    t = Transport('mistral', 'm1', tmp_path, sender=send, max_calls=2)
    req = dict(model='m1', messages=[], temperature=0)
    a = t.call(req); b = t.call(req)
    assert not a['cached'] and b['cached'] and len(sent) == 1
    assert not t.call(req, attempt=1)['cached'] and len(sent) == 2          # attempt is part of the key
    assert t.call(dict(req, temperature=1))['transport']['status'] == 'BUDGET_EXHAUSTED'
    t2 = Transport('mistral', 'm1', tmp_path, sender=send, max_calls=2)      # restart keeps the counter
    assert t2.sent == 2 and t2.call(dict(req, temperature=2))['transport']['status'] == 'BUDGET_EXHAUSTED'
    off = Transport('mistral', 'm1', tmp_path, offline=True)
    assert off.call(req)['cached']
    with pytest.raises(NetworkTripwire):
        off.call(dict(req, temperature=3))
    with pytest.raises(ValueError):
        t.call(dict(req, model='other'))
    other_model = Transport('mistral', 'm2', tmp_path, offline=True)
    with pytest.raises(NetworkTripwire):
        other_model.call(dict(req, model='m2'))


def test_transport_failure_not_cached_and_not_retried_by_default(tmp_path):
    send, sent = fake_sender(fail=True)
    t = Transport('mistral', 'm1', tmp_path, sender=send)
    req = dict(model='m1', messages=[])
    assert t.call(req)['content'] is None
    assert t.call(req)['transport']['status'] == 'PRIOR_FAILURE_NOT_RETRIED' and len(sent) == 1
    t2 = Transport('mistral', 'm1', tmp_path, sender=send, retry_failed=1)
    t2.call(req)
    assert len(sent) == 2
    lines = [json.loads(x) for x in (tmp_path / 'attempts.jsonl').read_text().splitlines()]
    assert [x['ok'] for x in lines if x['event'] == 'SENT'] == [False, False]


def test_offline_replay_opens_no_socket(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError('network')
    monkeypatch.setattr(socket, 'create_connection', boom)
    monkeypatch.setattr(socket.socket, 'connect', boom)
    r = row(GOOD)
    t = Transport('mistral', 'ministral-14b-2512', tmp_path, offline=True)
    with pytest.raises(NetworkTripwire):
        review(r['prompt'], r['response'], ReviewConfig.profile('baseline'), client=t)


def test_baseline_request_is_byte_identical_to_historical_i4():
    pytest.importorskip('experiments.hybrid_mechanisms.interfaces')
    from experiments.hybrid_mechanisms.interfaces import body as body0
    from experiments.evidence_packer_v2.llm_eval import review_packet as rp0
    from guardian_truth.evidence_packer import PackerConfig, pack, resolve
    r = row(GOOD)
    p = pack(r, PackerConfig(budget_bytes=20000)); resolve(p, r)
    full = p['mode'] == 'FULL_INPUT'
    assert reviewer.body(reviewer.review_packet(p, full), 'mistral', 'm') == body0(rp0(p, full), 'mistral', 'm', interface='I4')
    assert reviewer.body(reviewer.review_packet(p, full), 'ollama', 'g') == body0(rp0(p, full), 'ollama', 'g', interface='I4')


def test_ported_guard_matches_experiment_guard():
    pytest.importorskip('experiments.whole_move_v1.mechanical')
    from experiments.whole_move_v1.mechanical import check as old
    from guardian_truth.integrated.declarations import check as new
    for resp in (GOOD, call('cancel_order', {'order_id': 'W1234567', 'reason': 'changed_mind'}), call('cancel_order', {'order_id': 1})):
        a, b = old(row(resp)), new(row(resp))
        a.pop('version'); b.pop('version')
        assert a == b


def test_cli_no_model_runs_on_unseen_input(tmp_path):
    f = tmp_path / 'in.jsonl'
    f.write_text(json.dumps(dict(row(GOOD), label=1, id='leak')) + '\n')
    out = subprocess.run([sys.executable, '-m', 'guardian_truth.integrated.cli', str(f), '--no-model'],
                         capture_output=True, text=True, check=True).stdout
    res = json.loads(out)
    assert res['projection'] == 'NOT_EXECUTED_PROJECTED_0' and res['cost']['http_calls'] == 0
