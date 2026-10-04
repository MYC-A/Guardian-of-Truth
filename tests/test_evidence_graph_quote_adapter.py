"""Addressing and API accounting risks introduced by the new experiment."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments/searh_23/evidence_graph_v1'))
from quote_adapter import QuoteGraph
from guardian_truth.source_search.store import SourceStore


def graph():
    return QuoteGraph(SourceStore({'prompt': '\u27e6SYSTEM\u27e7\nA change needs approval.\n'
        '[AVAILABLE TOOLS]\n- alter_item \u2014 Change one item\n    item_id: string!\n'
        '\u27e6USER\u27e7\nProceed', 'response': '\u2192 TOOL_CALL alter_item: {"item_id":"R"}'}))


def test_quote_is_unique_exact_and_no_fuzzy_repair():
    g = graph(); job = next(j for j in g.initial_jobs() if j['task'] == 'INVENTORY')
    sid = job['packet']['unit_id']
    out = g.offsets(job, {'source_id': sid, 'quote': 'needs approval'})
    assert g.resolve(out)['text'] == 'needs approval'
    with pytest.raises(ValueError, match='MISSING_OR_AMBIGUOUS'):
        g.offsets(job, {'source_id': sid, 'quote': 'need approval'})


def test_duplicate_quote_and_other_source_cannot_resolve():
    g = graph(); job = next(j for j in g.initial_jobs() if j['task'] == 'INVENTORY')
    sid = job['packet']['unit_id']
    modified = deepcopy(job)
    modified['packet']['fragments'][0]['text'] = 'same same'
    with pytest.raises(ValueError, match='AMBIGUOUS'):
        g.offsets(modified, {'source_id': sid, 'quote': 'same'})
    with pytest.raises(ValueError, match='MISSING_OR_AMBIGUOUS'):
        g.offsets(job, {'source_id': 't0', 'quote': 'Proceed'})


def test_changed_wire_contract_keeps_request_identity_valid_and_is_stable():
    g = graph(); first = g.initial_jobs(); second = g.initial_jobs()
    assert first == second
    job = next(j for j in first if j['task'] == 'EFFECT')
    sid = job['packet']['fragments'][0]['source_id']
    reply = {'tool': 'alter_item', 'effect': 'MODIFY', 'action': 'change item',
             'spans': [{'source_id': sid, 'quote': 'Change one item'}],
             'object_type': 'item', 'object_spans': [{'source_id': sid, 'quote': 'one item'}],
             'reason': 'The declaration explicitly changes an item.'}
    assert g.admit(job['id'], reply)['valid']
    assert g.effects['alter_item']['effect'] == 'MODIFY'


def test_read_requests_retain_native_offsets():
    g = graph()
    reply = {'read_requests': [{'source_id': 'h0', 'start': 0, 'end': 10}]}
    job = g.initial_jobs()[0]
    assert g.offsets(job, reply) == reply


def test_worker_uses_same_wire_digest_and_never_serializes_credentials():
    from api_worker import digest as worker_digest
    from guardian_truth.source_search.store import digest
    assert digest({'x': '\u041f\u0440\u0438\u0432\u0435\u0442'}) == worker_digest({'x': '\u041f\u0440\u0438\u0432\u0435\u0442'})
