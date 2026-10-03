import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'experiments/searh_23/source_search_20261002'))
from replay_v10 import replay
from guardian_truth.source_search.id_contract import run_ids
from guardian_truth.source_search.pipeline import QUESTIONS


def test_saved_real46_a1_replay_retains_direct_raw_result():
    result = replay()
    assert result['arms']['direct'] == {'TP': 15, 'FP': 0, 'FN': 8, 'TN': 23} or result['arms']['direct'] == {'TP': 15, 'FN': 8, 'TN': 23}
    assert result['api_calls'] == 0


def test_checks_are_diagnostics_checked_without_id_is_not_closed():
    row = {'prompt': '⟦SYSTEM⟧\nA rule.\n⟦USER⟧\nHello.', 'response': 'Hello.'}
    vote = {'decision': 'NO_ERROR', 'explanation': 'Synthetic', 'findings': [],
        'checks': {q: {'status': 'NOT_APPLICABLE', 'reason': 'Synthetic', 'evidence_ids': []} for q in QUESTIONS}, 'open_questions': []}
    vote['checks']['scope']['status'] = 'CHECKED'
    result = run_ids(row, lambda _: {'status': 'OK', 'content': json.dumps({'assessment': vote})}, mode='direct', checks_mode='diagnostic')
    assert result['decision'] == 'NO_ERROR'
    assert result['assessment']['checks_incomplete']
    assert result['assessment']['unclosed_checks'] == ['scope']
    vote['checks']['scope']['evidence_ids'] = ['nonexistent']
    result = run_ids(row, lambda _: {'status': 'OK', 'content': json.dumps({'assessment': vote})}, mode='direct', checks_mode='diagnostic')
    assert result['decision'] == 'UNKNOWN'
