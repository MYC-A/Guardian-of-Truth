import json
from guardian_truth.source_search.id_contract import run_ids
from guardian_truth.source_search.pipeline import QUESTIONS, TOOLS
from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.final_context import retrieved_texts


def test_final_contains_retrieved_text_but_no_evaluator_conversation():
    row = {'prompt': '⟦SYSTEM⟧\nSynthetic policy.\n[AVAILABLE TOOLS]\n- tool_a — inspect\n⟦USER⟧\nHello.', 'response': 'Hello.'}
    seen = []
    vote = {'decision': 'NO_ERROR', 'explanation': 'Synthetic', 'findings': [],
        'checks': {q: {'status': 'NOT_APPLICABLE', 'reason': 'Synthetic', 'evidence_ids': []} for q in QUESTIONS}, 'open_questions': []}
    def ask(messages):
        seen.append(json.loads(json.dumps(messages)))
        reply = {'action': {'op': 'read_source', 'args': {'source_id': 'h0'}}} if len(seen) == 1 else {'assessment': vote}
        return {'status': 'OK', 'content': json.dumps(reply)}
    result = run_ids(row, ask, max_steps=2, checks_mode='diagnostic', final_context='evidence', artifact_guard=True)
    assert result['decision'] == 'NO_ERROR'
    final = seen[-1]
    assert [m['role'] for m in final] == ['system', 'user']
    packet = json.loads(final[1]['content'])
    assert set(packet) == {'target_response', 'source_linked_context', 'retrieved_evidence'}
    assert packet['retrieved_evidence']
    assert 'investigation_transcript' not in json.dumps(packet)
    assert 'tool_call_id' not in json.dumps(packet)
    # Original input strings may name a tool also used by the verifier.
    assert not any(name in json.dumps(packet) for name in TOOLS)
    assert not any(name in final[0]['content'] for name in TOOLS)


def test_search_excerpt_not_expanded_to_unread_source():
    store = SourceStore({'prompt': '⟦SYSTEM⟧\n' + 'data ' * 600, 'response': 'ok'})
    result = store.search_sources('data')
    returned = retrieved_texts(store, result)
    assert returned
    assert all(len(r['text']) <= 300 for r in returned)
    assert all(store.text(r['source_id']) == r['text'] for r in returned)


def test_original_call_with_shared_name_is_preserved_and_not_rejected():
    row = {'prompt': '⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- calculate — numeric tool\n',
        'response': '→ TOOL_CALL calculate: {"x":1}'}
    vote = {'decision': 'ERROR', 'explanation': 'Synthetic',
        'findings': [{'type': 'OTHER', 'target_source_id': 't0', 'explanation': 'calculate has an invalid value', 'evidence_ids': ['h0']}],
        'checks': {q: {'status': 'NOT_APPLICABLE', 'reason': 'Synthetic', 'evidence_ids': []} for q in QUESTIONS}, 'open_questions': []}
    result = run_ids(row, lambda _: {'status': 'OK', 'content': json.dumps({'assessment': vote})}, mode='auto',
        checks_mode='diagnostic', final_context='evidence', artifact_guard=True)
    assert result['mode'] == 'direct'
    assert result['decision'] == 'ERROR'
    assert not result['assessment']['rejected_findings']
