"""Verify the concrete long-source retrieval failure and source boundaries."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/searh_23/evidence_graph_search_probe'))
from ranked_search import bm25
from ranked_search import RankedGraph
from span_ids import IdGraph
from guardian_truth.source_search.store import SourceStore


def test_bm25_selects_relevant_late_window_without_a_domain_dictionary():
    documents = ['unrelated noise ' * 200, 'unrelated noise ' * 200,
                 'approval M-208 is recorded with limit 73']
    scores = bm25('approval M-208 limit', documents)
    assert scores[2] > scores[0] == scores[1]


def test_ranking_is_finite_for_empty_sources_and_missing_terms():
    assert bm25('missing', ['', '']) == [0., 0.]
    assert bm25('missing', []) == []


def fixture(cls, *, history=''):
    return cls(SourceStore({'prompt': '\u27e6SYSTEM\u27e7\nA change requires approval.\n'
        '[AVAILABLE TOOLS]\n- alter_item \u2014 Change one item\n    item_id: string!\n'
        '\u27e6USER\u27e7\nProceed\n' + history,
        'response': '\u2192 TOOL_CALL alter_item: {"item_id":"R"}'}))


def test_id_contract_cannot_accept_model_offsets_or_unknown_ids():
    g = fixture(IdGraph)
    job = next(j for j in g.initial_jobs() if j['task'] == 'EFFECT')
    reply = {'tool': 'alter_item', 'effect': 'MODIFY', 'action': 'change item',
        'spans': [{'source_id': 'd0', 'start': 0, 'end': 10}],
        'object_type': 'item', 'object_spans': [{'span_id': 'not-issued'}], 'reason': 'explicit'}
    assert not g.admit(job['id'], reply)['valid']
    assert g.failures[job['id']]['cause'] == 'NON_ID_EVIDENCE_ADDRESS'


def test_id_contract_success_is_stable_and_original_text_preserved():
    g = fixture(IdGraph)
    jobs = g.initial_jobs()
    assert jobs == g.initial_jobs()
    job = next(j for j in jobs if j['task'] == 'EFFECT')
    catalog = job['packet']['span_catalog']
    chosen = next(s for s in catalog if 'Change one item' in s['text'])
    reply = {'tool': 'alter_item', 'effect': 'MODIFY', 'action': 'change item',
        'spans': [{'span_id': chosen['span_id']}], 'object_type': 'item',
        'object_spans': [{'span_id': chosen['span_id']}], 'reason': 'explicit'}
    assert g.admit(job['id'], reply)['valid']
    assert g.resolve(g.effects['alter_item']['spans'][0])['text'] == chosen['text']


def test_ranked_source_windows_reach_far_evidence():
    history = '\u27e6ASSISTANT\u27e7\n\u2192 TOOL_CALL inspect_item: {"item_id":"R"}\n'
    history += '\u2190 TOOL_RESPONSE inspect_item: {"notes":"' + ('noise ' * 8000) + 'approval limit 73"}\n'
    g = fixture(RankedGraph, history=history)
    tid = next(iter(g.targets))
    packet = {'target_id': tid, 'requirement_id': 'p0:r0', 'leaf_id': 'condition',
        'target': g.targets[tid], 'leaf': {'label': 'approval limit 73', 'spans': []},
        'requirement': {'action': 'change item'}, 'fragments': [], 'round': 0}
    job = g._job('WITNESS', tid + ':p0:r0:condition', packet)
    far = [f for f in job['packet']['fragments'] if 'approval limit 73' in f['text']]
    assert far and far[0]['start'] > 30000
    assert all(f['end'] - f['start'] <= g.chunk_chars for f in job['packet']['fragments'])
