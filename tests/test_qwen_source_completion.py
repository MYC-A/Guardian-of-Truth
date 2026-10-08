"""Original native parser spans and generic retrieval contrasts, no model calls."""
import copy
import hashlib
import json

import pytest

from experiments.guardian_binding.source_completion import complete
from guardian_truth.parsing import parse_events
from guardian_truth.verification.pipeline import packet_for


def row(results=None, args=None):
    results = results or [('scan', '{"records":[{"reference":"R42","amount":7}]}', None)]
    prompt = '⟦SYSTEM⟧\nFollow the user request.\n⟦USER⟧\nInspect Мира.\n⟦ASSISTANT⟧\n'
    for name, body, status in results:
        prompt += f'→ TOOL_CALL {name}: {{}}\n← TOOL_RESPONSE {name}' + (f' [{status}]' if status else '') + f': {body}\n'
    return dict(prompt=prompt, response='⟦ASSISTANT⟧\n→ TOOL_CALL inspect: ' +
                json.dumps(args or {'nested': {'reference': 'R42'}}, ensure_ascii=False))


def view(source_row, remove=True):
    packet = packet_for(source_row, 400000)
    assert packet is not None and packet['coverage']['complete_input']
    if remove:
        packet['history'] = [s for s in packet['history'] if s['kind'] not in ('call', 'result')]
        packet['coverage']['complete_input'] = False
        packet['coverage']['unread'] = [{'category': 'HISTORY', 'reason': 'TEST_VIEW_GAP'}]
    return packet


def test_full_native_stale_latest_timeline_and_failed_receipts_are_retrieval_only():
    source_row = row([('scan', '{"reference":"R42","revision":1}', None),
                      ('refresh', '{"reference":"R42","revision":2}', 'ERROR')])
    original = view(source_row)
    packet, rec = complete(source_row, original)
    results = [s for s in packet['history'] if s['kind'] == 'result']
    assert len(results) == 2 and results[1]['receipt_status'] == 'ERROR'
    assert len([s for s in packet['history'] if s['kind'] == 'call']) == 2
    assert [s['event'] for s in packet['history']] == sorted(s['event'] for s in packet['history'])
    assert all(m['match_kind'] == 'FIELD_AND_VALUE' for m in rec['matches'])
    assert rec['authority'] == 'RETRIEVAL_ONLY' and rec['retrieval_complete']
    assert not rec['latest_state_established'] and not rec['semantic_relevance_complete']
    assert not rec['closure_established'] and not packet['coverage']['complete_input']
    assert packet['coverage'] == original['coverage']
    assert not any(lineage['pairing_authenticated'] for lineage in rec['lineage'])


def test_parallel_same_tool_lineage_is_ambiguous_not_paired():
    source_row = row()
    source_row['prompt'] = source_row['prompt'].replace('← TOOL_RESPONSE', '→ TOOL_CALL scan: {"different":true}\n← TOOL_RESPONSE')
    packet, rec = complete(source_row, view(source_row))
    assert rec['lineage'][0]['status'] == 'AMBIGUOUS'
    assert len(rec['lineage'][0]['candidate_call_ids']) == 2
    assert len(rec['lineage'][0]['call_sources_selected']) == 2
    assert len([s for s in packet['history'] if s['kind'] == 'call']) == 2


def test_lineage_never_equates_user_call_with_assistant_result():
    source_row = row()
    source_row['prompt'] = source_row['prompt'].replace('→ TOOL_CALL scan: {}',
        '⟦USER_TOOL_CALL name="scan"⟧\n{}').replace('← TOOL_RESPONSE scan: ',
        '⟦TOOL_RESULT name="scan" requestor="assistant"⟧\n')
    packet, rec = complete(source_row, view(source_row))
    assert rec['lineage'][0]['status'] == 'UNRESOLVED'
    assert not rec['lineage'][0]['candidate_call_ids']
    assert not any(s['kind'] == 'call' for s in packet['history'])


def test_success_and_failure_receipts_for_same_call_are_both_kept_without_resolving_pair():
    source_row = row()
    source_row['prompt'] += '← TOOL_RESPONSE scan [ERROR]: {"reference":"R42"}\n'
    packet, rec = complete(source_row, view(source_row))
    assert len(rec['lineage']) == 2
    assert all(not r['pairing_authenticated'] for r in rec['lineage'])
    assert len([s for s in packet['history'] if s['kind'] == 'result']) == 2


def test_value_collision_is_candidate_and_matching_field_has_priority():
    source_row = row([('other', '{"unrelated":"R42"}', None),
                      ('scan', '{"reference":"R42"}', None)])
    packet, rec = complete(source_row, view(source_row))
    assert [m['match_kind'] for m in rec['matches']] == ['VALUE_ONLY', 'FIELD_AND_VALUE']
    assert all(m['entity_binding'] == 'UNRESOLVED' for m in rec['matches'])
    expected = next(s for s in packet['history'] if s.get('tool') == 'scan' and s['kind'] == 'result')
    _, bounded = complete(source_row, view(source_row), len(expected['text'].encode('utf-8')))
    assert next(m for m in bounded['matches'] if m['match_kind'] == 'FIELD_AND_VALUE')['selected']
    assert not next(m for m in bounded['matches'] if m['match_kind'] == 'VALUE_ONLY')['selected']


def test_decimal_bool_string_null_and_escaped_nested_paths():
    source_row = row([('scan', '{"a/b":{"~key":[1.00000000000000000001,true,"1",null]}}', None)],
                     {'a/b': {'~key': [1, True, '1', None]}})
    _, rec = complete(source_row, view(source_row))
    assert {m['argument_path'] for m in rec['matches']} == {'/a~1b/~0key/1', '/a~1b/~0key/2', '/a~1b/~0key/3'}
    assert {m['value_type'] for m in rec['matches']} == {'BOOLEAN', 'STRING', 'NULL'}
    assert all(m['argument_path'] == m['source_pointer'] for m in rec['matches'])


@pytest.mark.parametrize('budget', [0, 1])
def test_whole_oversized_result_never_truncated_and_explicit_unchecked(budget):
    source_row = row([('scan', '{"reference":"R42","padding":"' + 'z' * 1000 + '"}', None)])
    original = view(source_row)
    packet, rec = complete(source_row, original, budget)
    assert packet == original
    assert rec['exact_typed_match_scan_complete'] and not rec['retrieval_complete']
    assert not rec['matched_sources_read_complete'] and rec['unchecked_source_ids']
    assert all(g['gap'] == 'WHOLE_EVENT_OVER_BUDGET' for g in rec['gaps'])
    assert rec['budget']['used_bytes'] == 0


def test_expands_partial_id_once_and_preserves_exact_unicode_spans_and_hash():
    source_row = row([('scan', '{"reference":"R42","owner":"Мира😀"}', None)])
    original = view(source_row, remove=False)
    source = next(s for s in original['history'] if s['kind'] == 'result')
    source['text'] = source['text'][:25]
    packet, rec = complete(source_row, original)
    sid = source['source_id']
    assert rec['sources_expanded'] == [sid]
    full = next(s for s in packet['history'] if s['source_id'] == sid)
    assert source_row['prompt'][full['start']:full['end']] == full['text']
    assert full['sha256'] == hashlib.sha256(full['text'].encode('utf-8')).hexdigest()
    assert full['offset_unit'] == 'PYTHON_CHARACTER' and 'Мира😀' in full['text']
    assert len([s for s in packet['history'] if s['source_id'] == sid]) == 1
    assert len(full['text'].encode('utf-8')) > len(full['text'])


def test_unchanged_full_sources_cost_zero_even_with_zero_budget():
    source_row = row()
    packet, rec = complete(source_row, view(source_row, remove=False), 0)
    assert rec['retrieval_complete'] and not rec['sources_added'] and not rec['sources_expanded']
    assert rec['sources_already_full'] and rec['budget']['used_bytes'] == 0


@pytest.mark.parametrize('bad', ['{"reference":"R42","reference":"R43"}', '{"reference":NaN}', '{"reference":"R42"} extra', '{"reference":1e9999999999999999999999}'])
def test_result_parse_gaps_do_not_certify_scan_closure(bad):
    source_row = row([('scan', bad, None)])
    _, rec = complete(source_row, view(source_row))
    assert not rec['exact_typed_match_scan_complete'] and not rec['retrieval_complete']
    assert any(g['gap'] == 'RESULT_PAYLOAD_UNPARSED' for g in rec['gaps'])
    assert not rec['matches'] and not rec['closure_established']


def test_status_in_body_and_native_special_marker_are_supported_without_rewriting():
    source_row = row()
    source_row['prompt'] = source_row['prompt'].replace('← TOOL_RESPONSE scan: ', '⟦TOOL_RESULT name="scan" requestor="assistant"⟧\n[ERROR] ')
    packet, rec = complete(source_row, view(source_row))
    result = next(s for s in packet['history'] if s['kind'] == 'result')
    assert result['text'].startswith('⟦TOOL_RESULT') and result['receipt_status'] == 'ERROR'
    assert rec['matches'] and rec['authority'] == 'RETRIEVAL_ONLY'


def test_user_current_calls_are_not_query_targets():
    source_row = row()
    source_row['response'] = source_row['response'].replace('⟦ASSISTANT⟧', '⟦USER⟧')
    _, rec = complete(source_row, view(source_row))
    assert not rec['matches']


def test_malformed_current_payload_reports_gap_without_substring_scalar_search():
    source_row = row()
    source_row['response'] = source_row['response'].replace('{"nested": {"reference": "R42"}}',
                                                          '{"reference":"R42","reference":"R43"}')
    _, rec = complete(source_row, view(source_row))
    assert not rec['matches'] and not rec['exact_typed_match_scan_complete']
    assert any(g['gap'] == 'CURRENT_ARGUMENTS_UNPARSED' for g in rec['gaps'])


def test_missing_lineage_budget_is_explicit_even_when_result_fits():
    source_row = row()
    full = view(source_row, remove=False)
    result = next(s for s in full['history'] if s['kind'] == 'result')
    packet, rec = complete(source_row, view(source_row), len(result['text'].encode('utf-8')))
    assert rec['matched_sources_read_complete'] and not rec['retrieval_complete']
    assert rec['lineage'][0]['call_sources_unchecked'] == rec['unchecked_source_ids']
    assert len([s for s in packet['history'] if s['kind'] == 'result']) == 1
    assert not any(s['kind'] == 'call' for s in packet['history'])


def test_renamed_arbitrary_field_works_without_identity_regex():
    source_row = row([('arbitrary_tool', '{"arbitrary_measure":"R42"}', None)],
                     {'deep': {'arbitrary_measure': 'R42'}})
    _, rec = complete(source_row, view(source_row))
    assert rec['matches'][0]['match_kind'] == 'FIELD_AND_VALUE'
    assert rec['matches'][0]['argument_path'] == '/deep/arbitrary_measure'


def test_duplicate_packet_source_namespace_is_rejected_not_last_write_wins():
    source_row = row()
    original = view(source_row)
    original['history'].append(copy.deepcopy(original['history'][0]))
    with pytest.raises(ValueError, match='DUPLICATED_SOURCE_ID'):
        complete(source_row, original)


def test_determinism_and_no_mutation():
    source_row = row()
    original = view(source_row)
    before_row, before_packet = copy.deepcopy(source_row), copy.deepcopy(original)
    a, b = complete(source_row, original), complete(source_row, original)
    assert a == b and source_row == before_row and original == before_packet
    json.dumps(a, ensure_ascii=False)  # receipt has no unencodable Decimal values


@pytest.mark.parametrize('budget', [-1, True, 1.5, '12'])
def test_invalid_budget_is_not_silently_accepted(budget):
    source_row = row()
    with pytest.raises(ValueError):
        complete(source_row, view(source_row), budget)
