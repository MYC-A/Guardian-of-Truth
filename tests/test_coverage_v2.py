"""Property tests for coverage_v2 (no case-specific expectations)."""
import json

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
        assert used <= budget + 64
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
