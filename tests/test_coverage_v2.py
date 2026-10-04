"""Property tests for coverage_v2 (no case-specific expectations)."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from experiments.retrieval_bakeoff_v1.dataset import load_cases
from experiments.retrieval_bakeoff_v1.corpus import build_corpus
from guardian_truth.coverage_v2 import select_evidence, build_units
from guardian_truth.coverage_v2.selector import literals, _pieces

CASES = load_cases()


@pytest.fixture(scope='module')
def corpora():
    return [build_corpus(c) for c in CASES]


def test_pieces_partition_text():
    text = '# A\n\npara one\n- x\n- y\n\n' + 'word ' * 900
    spans = _pieces(text, 500)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(a < b and b - a <= 500 for a, b in spans)
    assert all(spans[k][1] == spans[k + 1][0] for k in range(len(spans) - 1))


def test_literals_normalise_and_skip_free_text():
    lits = literals('Pay $1,286 to certificate_3765853 on 2024-05-26T10:00, total 44$.')
    assert {'1286', 'certificate_3765853', '44'} <= lits
    assert all(' ' not in l for l in lits)


@pytest.mark.parametrize('budget', [20000, 40000, 80000])
def test_budget_and_exact_provenance(corpora, budget):
    for co in corpora:
        pk = select_evidence(co, budget_bytes=budget)
        used = len(json.dumps(pk['read_sources'] + pk['current_targets'] + pk['declarations'],
                              ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        assert used <= budget
        for s in pk['read_sources']:
            assert co.row['prompt'][s['start']:s['end']] == s['text']
        assert pk['completeness_certified'] is False
        assert len(set(pk['selected_ids'])) == len(pk['selected_ids'])


def test_full_input_mode_reads_everything(corpora):
    co = min(corpora, key=lambda c: len(c.row['prompt']))
    pk = select_evidence(co, budget_bytes=10**7)
    assert pk['mode'] == 'FULL_INPUT'
    assert len(pk['read_sources']) == len(build_units(co))


def test_deterministic_and_label_blind(corpora):
    c = dict(CASES[0]); c['label'] = 1; c['explanation'] = 'SECRET'
    a = select_evidence(build_corpus(c), 20000)
    b = select_evidence(corpora[0], 20000)
    assert a['selected_ids'] == b['selected_ids']


def test_monotone_more_budget_never_loses_coverage_mass(corpora):
    from experiments.retrieval_bakeoff_v1.scoring import covered
    for co in corpora[:6]:
        small = select_evidence(co, 20000)['read_sources']
        big = select_evidence(co, 80000)['read_sources']
        chars = lambda ss: sum(s['end'] - s['start'] for s in ss)
        assert chars(big) >= chars(small)


def test_selected_receipts_have_complete_qualified_dependencies(corpora):
    for co in corpora:
        pk = select_evidence(co, 20000)
        selected = set(pk['selected_ids'])
        units = build_units(co)
        for result in pk['read_sources']:
            if result['kind'] != 'result':
                continue
            parent = result['parent_source_id']
            paired = co.pairs.get(parent)
            if paired:
                required = {u['source_id'] for u in units
                            if u['parent_source_id'] in (parent, paired)}
                assert required <= selected
        assert all(r['status'] != 'PARTIAL_RECEIPT' for r in pk['receipt_dependencies'])


def test_hash_seed_determinism_across_processes():
    """Exercise production parsing and tied feedback on the frozen input bank."""
    root = Path(__file__).resolve().parents[1]
    code = '''
import json
from experiments.retrieval_bakeoff_v1.dataset import load_cases
from experiments.retrieval_bakeoff_v1.corpus import build_corpus
from guardian_truth.coverage_v2 import select_evidence
packets = [select_evidence(build_corpus(c), 20000) for c in load_cases()]
print(json.dumps([{k:p[k] for k in ('selected_ids','trace','failure','literal_ledger')}
                  for p in packets], sort_keys=True))
'''
    outputs = []
    for seed in (0, 1, 7, 11, 91):
        env = dict(os.environ, PYTHONHASHSEED=str(seed),
                   PYTHONPATH=os.pathsep.join((str(root), str(root / 'src'))))
        outputs.append(subprocess.run([sys.executable, '-c', code], cwd=root, env=env,
                                      check=True, capture_output=True, text=True).stdout)
    assert all(output == outputs[0] for output in outputs[1:])


def _synthetic(policy='general policy', user='latest request', call_padding='', result_padding=''):
    return build_corpus(dict(
        prompt=('⟦SYSTEM⟧\n' + policy + '\n⟦ASSISTANT⟧\n'
                '→ TOOL_CALL lookup: ' + json.dumps({'item_id': 'item_42', 'payload': call_padding}) + '\n'
                '← TOOL_RESPONSE lookup: ' + json.dumps({'item_id': 'item_42', 'payload': result_padding}) + '\n'
                '⟦USER⟧\n' + user),
        response='⟦ASSISTANT⟧\nThe item_42 result has been found.'))


def test_latest_user_windows_are_atomic_or_explicit_failure():
    co = _synthetic(user='latest consent ' * 700)
    users = {u['source_id'] for u in build_units(co) if u['role'] == 'user'}
    assert len(users) > 1
    small = select_evidence(co, 3000)
    assert small['failure'] == 'LATEST_USER_BUDGET_SKIPPED'
    assert not users.intersection(small['selected_ids'])
    assert any(t.get('status') == 'BUDGET_SKIPPED' for t in small['trace'])
    large = select_evidence(co, 30000)
    assert not large['failure']
    assert users <= set(large['selected_ids'])


def test_latest_user_anchor_uses_text_not_user_tool_event():
    co = build_corpus(dict(
        prompt=('⟦SYSTEM⟧\nrules\n⟦USER⟧\nPlease inspect the requested item.\n'
                '→ TOOL_CALL lookup: ' + json.dumps({'payload': 'argument ' * 800}) + '\n'
                '← TOOL_RESPONSE lookup: ' + json.dumps({'payload': 'result ' * 800}) + '\n'),
        response='⟦ASSISTANT⟧\nI will inspect it.'))
    pk = select_evidence(co, 3000)
    assert pk['failure'] is None
    user_text = [u for u in build_units(co) if u['role'] == 'user' and u['kind'] == 'text']
    assert len(user_text) == 1
    assert user_text[0]['source_id'] in pk['selected_ids']
    latest_anchors = {t['source_id'] for t in pk['trace'] if t['why'] == 'LATEST_USER_WHOLE'}
    assert latest_anchors == {user_text[0]['source_id']}


def test_whitespace_windows_partition_parent_in_full_input():
    co = build_corpus(dict(prompt='⟦USER⟧\nFirst.\n' + ' ' * 7000 + '\nConsent.',
                           response='⟦ASSISTANT⟧\nAcknowledged.'))
    units = build_units(co)
    assert any(not u['text'].strip() for u in units)
    parent = next(s for s in co.store.sources.values()
                  if s['document'] == 'prompt' and s['kind'] == 'text')
    intervals = sorted((u['start'], u['end']) for u in units)
    assert intervals[0][0] == parent['start'] and intervals[-1][1] == parent['end']
    assert all(left[1] == right[0] for left, right in zip(intervals, intervals[1:]))
    pk = select_evidence(co, 30000)
    assert pk['mode'] == 'FULL_INPUT'
    assert ''.join(s['text'] for s in pk['read_sources']) == co.row['prompt'][parent['start']:parent['end']]
    assert all(p['status'] == 'COMPLETE_PARENT' for p in pk['parent_coverage'])
    small = select_evidence(co, 3000)
    assert small['failure'] == 'LATEST_USER_BUDGET_SKIPPED'
    assert small['mode'] != 'FULL_INPUT'


def test_mandatory_overflow_is_explicit_failure():
    co = _synthetic()
    pk = select_evidence(co, 1)
    assert pk['failure'] == 'MANDATORY_SOURCES_EXCEED_BUDGET'
    assert pk['read_sources'] == []
    assert pk['cost']['source_utf8_bound'] > 1


def test_oversize_receipt_is_omitted_atomically():
    co = _synthetic(call_padding='call argument ' * 600, result_padding='result value ' * 600)
    units = build_units(co)
    result_parent = next(u['parent_source_id'] for u in units if u['kind'] == 'result')
    assert co.pairs[result_parent]
    results = {u['source_id'] for u in units if u['parent_source_id'] == result_parent}
    small = select_evidence(co, 7000)
    assert not results.intersection(small['selected_ids'])
    large = select_evidence(co, 50000)
    assert results <= set(large['selected_ids'])
    receipt = next(r for r in large['receipt_dependencies'] if r['result_source_id'] == result_parent)
    assert receipt['status'] == 'QUALIFIED_COMPLETE'


def test_user_actor_pair_is_explicitly_unqualified():
    co = build_corpus(dict(
        prompt=('⟦SYSTEM⟧\nrules\n⟦USER⟧\n'
                '→ TOOL_CALL lookup: {"item_id":"item_42"}\n'
                '← TOOL_RESPONSE lookup: {"item_id":"item_42"}\n'
                '⟦USER⟧\nPlease inspect item_42.'),
        response='⟦ASSISTANT⟧\nThe item_42 record was found.'))
    assert not co.pairs
    pk = select_evidence(co, 30000)
    assert pk['receipt_dependencies']
    assert all(r['status'] == 'UNQUALIFIED_RESULT' and not r['qualified']
               for r in pk['receipt_dependencies'])


def test_policy_whole_reports_actual_parent_coverage():
    co = _synthetic(policy='normative clause ' * 650)
    small = select_evidence(co, 6500)
    assert not small['policy_whole']
    policies = [p for p in small['parent_coverage'] if p['category'] == 'POLICY']
    assert any(p['status'] != 'COMPLETE_PARENT' for p in policies)
    assert all(u['parent_coverage'] == 'EXACT_WINDOW_NOT_COMPLETE_PARENT'
               for u in small['read_sources'] if u['category'] == 'POLICY')
    large = select_evidence(co, 30000)
    assert large['policy_whole']
    assert all(p['status'] == 'COMPLETE_PARENT' for p in large['parent_coverage']
               if p['category'] == 'POLICY')


def test_equal_budget_harness_preserves_mandatory_failure():
    from experiments.coverage_v2.evaluate import baseline_packet
    co = _synthetic()
    budget = 1
    packet = baseline_packet(co, list(co.sources), budget, 'coverage')
    assert packet['cost']['source_utf8_bound'] > budget
    assert packet['failure'] == 'MANDATORY_CONTEXT_BUDGET_EXCEEDED'
