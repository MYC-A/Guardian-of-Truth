"""Typed entity binding tests (assignment §4.1 / audit R-001).

Covers: E-7/E-70 substring, same value across ID fields, several entities,
ID in JSON and plain text, absent ID, mixed text+call response, future
observations and repeated updates, GraphAPI typed queries, span fidelity.
Offline only; synthetic rows in the real corpus event format; no gold, no API.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'service'),
                str(ROOT / 'experiments/searh_23/hybrid_service_v1'),
                str(ROOT / 'experiments/searh_23/three_architectures')]

from evidence_views import _occurrence_spans, graph_for, GraphAPI, render


def span_text(row, doc, s, e):
    return (row['response'] if doc == 'response' else row['prompt'])[s:e]


def test_numeric_and_token_boundaries():
    text = 'E-70 has 70 seats, 7 free, id 42.5 kg and nr 42.'
    assert [text[s:e] for s, e in _occurrence_spans(text, 'E-70')] == ['E-70']
    assert _occurrence_spans(text, 'E-7') == []                       # inside E-70
    assert [text[s:e] for s, e in _occurrence_spans(text, 70)] == ['70']
    assert [text[s:e] for s, e in _occurrence_spans(text, 7)] == ['7']
    assert [text[s:e] for s, e in _occurrence_spans(text, 42)] == ['42']      # not 42.5
    assert [text[s:e] for s, e in _occurrence_spans(text, '42')] == ['42']    # str digits too
    assert _occurrence_spans(text, 5) == []                            # inside 42.5
    assert _occurrence_spans(text, 2) == []                            # inside 42.5/42


def test_substring_e70_excludes_e7():
    row = {'id': 't1', 'prompt': POLICY + USER_E70_AND_E7, 'response':
           '→ TOOL_CALL update_notes: {"item_id":"E-70"}'}
    g = graph_for(row)
    bound = {str(b['value']) for b in g['coverage']['typed_bindings']}
    assert 'E-70' in bound, bound
    assert 'E-7' not in bound, bound
    assert any(r['value'] == 'E-7' for r in g['coverage']['rejected_substring_only_matches']), \
        g['coverage']['rejected_substring_only_matches']
    sel_fields = {e['field'] for f in g['facts'] for e in f['entities']}
    assert sel_fields == {'item_id'}, sel_fields


def test_same_value_different_fields_flagged():
    row = {'id': 't2', 'prompt': POLICY + USER_COLLIDE, 'response':
           'I will proceed with record 42.'}
    g = graph_for(row)
    amb = g['coverage']['ambiguous_value_fields']
    assert amb and any(str(a['value']) == '42' and set(a['fields']) == {'item_id', 'payment_id'}
                       for a in amb), amb
    fields = {e['field'] for f in g['facts'] for e in f['entities']}
    assert {'item_id', 'payment_id'} <= fields, fields


def test_id_in_json_and_plain_text():
    row = {'id': 't4', 'prompt': POLICY + USER_E70, 'response':
           'Checking the item first.\n→ TOOL_CALL get_notes: {"item_id":"E-70"}'}
    g = graph_for(row)
    spans = [s for b in g['coverage']['typed_bindings'] if str(b['value']) == 'E-70' for s in b['spans']]
    assert spans, g['coverage']['typed_bindings']
    assert all(span_text(row, s['document'], s['start'], s['end']) == 'E-70' for s in spans)
    assert any(s['document'] == 'response' for s in spans)


def test_no_id_falls_back_to_full_graph_flagged():
    row = {'id': 't5', 'prompt': POLICY + USER_NOID, 'response':
           'I will check the notes.'}
    g = graph_for(row)
    cov = g['coverage']
    assert cov['selection_fallback_full_graph'] and cov['selection_scope_ambiguous']
    assert cov['facts_selected'] == cov['facts_total']


def test_mixed_text_plus_call_response():
    row = {'id': 't6', 'prompt': POLICY + USER_E70, 'response':
           'Checking the item first.\n→ TOOL_CALL get_notes: {"item_id":"E-70"}'}
    g = graph_for(row)
    bound = {str(b['value']) for b in g['coverage']['typed_bindings']}
    assert 'E-70' in bound, bound


def test_updates_and_edges_preserved():
    row = {'id': 't7', 'prompt': POLICY + USER_E70_UPDATES, 'response':
           '→ TOOL_CALL update_notes: {"item_id":"E-70"}'}
    g = graph_for(row)
    edges = g['edges']
    assert edges, 'chronology edges must survive selection'
    assert all(e['kind'] == 'PRIOR_OBSERVATION_NOT_SEMANTIC_OVERRIDE' for e in edges)
    ids = {f['id'] for f in g['facts']}
    assert all(e['from'] in ids and e['to'] in ids for e in edges)
    assert all(f['epistemic_status'] == 'OBSERVED_PAYLOAD_ONLY_NOT_CURRENT_STATE_OR_EXECUTION'
               for f in g['facts'])


def test_graphapi_typed_query_and_ambiguity():
    row = {'id': 't8', 'prompt': POLICY + USER_COLLIDE, 'response':
           'I will proceed with record 42.'}
    g = graph_for(row)
    api = GraphAPI(g)
    r = api.query({'op': 'observations', 'entity_id': 42})
    assert r['status'] == 'OK'
    assert set(r['matched_entity_fields']) == {'item_id', 'payment_id'}, r['matched_entity_fields']
    assert r['ambiguous_entity_value'] is True
    r2 = api.query({'op': 'observations', 'entity_id': '42'})  # typed string: no int match
    assert r2['matched_entity_fields'] == [] and not r2['ambiguous_entity_value']
    r3 = api.query({'op': 'available_actions'})
    assert r3['status'] == 'OK' and r3['remaining'] == 1


def test_render_modes_share_information():
    row = {'id': 't9', 'prompt': POLICY + USER_E70, 'response':
           '→ TOOL_CALL update_notes: {"item_id":"E-70"}'}
    g = graph_for(row)
    a, b = render(g, 'G2'), render(g, 'G2-linear')
    assert 'E-70' in a and 'E-70' in b
    assert g['coverage']['typed_bindings']


POLICY = """⟦SYSTEM⟧
apply_change may be called only if a is true. If a is true, apply_change is
permitted. No other condition is required. read_state and inspect are
permitted regardless of these conditions.
[AVAILABLE TOOLS]
- read_state — Reports current state of one item; it does not modify it.
    item_id: string!
- get_notes — Reads notes. It never commits an item.
    item_id: string!
- update_notes — Updates notes of one item.
    item_id: string!
⟦USER⟧
"""

USER_E70 = ('Process item E-70 when permitted.\n'
            '⟦ASSISTANT⟧\n'
            '→ TOOL_CALL read_state: {"item_id":"E-70"}\n'
            '← TOOL_RESPONSE read_state: {"item_id":"E-70","status":"active"}\n')

USER_E70_AND_E7 = ('Process item E-70 when permitted.\n'
                   '⟦ASSISTANT⟧\n'
                   '→ TOOL_CALL read_state: {"item_id":"E-7"}\n'
                   '← TOOL_RESPONSE read_state: {"item_id":"E-7","status":"archived"}\n'
                   '→ TOOL_CALL read_state: {"item_id":"E-70"}\n'
                   '← TOOL_RESPONSE read_state: {"item_id":"E-70","status":"active"}\n')

USER_COLLIDE = ('Handle record 42.\n'
                '⟦ASSISTANT⟧\n'
                '→ TOOL_CALL get_item: {"item_id":42}\n'
                '← TOOL_RESPONSE get_item: {"item_id":42,"status":"active"}\n'
                '→ TOOL_CALL get_payment: {"payment_id":42}\n'
                '← TOOL_RESPONSE get_payment: {"payment_id":42,"amount":10}\n')

USER_NOID = ('Please look at the notes.\n'
             '⟦ASSISTANT⟧\n'
             '→ TOOL_CALL get_notes: {}\n'
             '← TOOL_RESPONSE get_notes: {"status":"active","title":"misc"}\n')

USER_E70_UPDATES = ('Update item E-70 twice.\n'
                    '⟦ASSISTANT⟧\n'
                    '→ TOOL_CALL get_notes: {"item_id":"E-70"}\n'
                    '← TOOL_RESPONSE get_notes: {"item_id":"E-70","status":"active"}\n'
                    '→ TOOL_CALL get_notes: {"item_id":"E-70"}\n'
                    '← TOOL_RESPONSE get_notes: {"item_id":"E-70","status":"active","v":2}\n')

if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except AssertionError as exc:
                failures += 1
                print(f'FAIL {name}: {exc!r}')
    sys.exit(1 if failures else 0)
