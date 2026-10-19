import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from v3_analyze_e2 import choose_veto, evaluated, matched_prefix


def test_veto_preserves_hard_and_does_not_refill_vacated_quota():
    y = np.array([0, 1, 0, 1, 0])
    _, p, _ = evaluated(y, [5,4,3,2,1], [-8,-1,3,5,2], [0]*5, [0]*5, .01)
    assert p['current35b'].tolist() == [1,1,0,0,0]
    assert p['veto'].tolist() == [0,1,0,0,0]
    _, p, _ = evaluated(y, [5,4,3,2,1], [-8,-1,3,5,2], [0]*5, [1,0,0,0,0], .2)
    assert p['veto'].tolist() == [1,1,0,0,0]


def test_dev_threshold_selection_prefers_smallest_safe_threshold():
    result = choose_veto(np.array([0,1,1,0,0]), np.array([5,4,3,2,1]),
                         np.array([-8,-1,3,5,2]), np.zeros(5), np.zeros(5,dtype=bool))
    assert result['selected_v'] == .01
    unsafe = choose_veto(np.array([1,0,1,0,0]), np.array([5,4,3,2,1]),
                         np.array([-8,5,3,5,2]), np.zeros(5), np.zeros(5,dtype=bool))
    assert unsafe['selected_v'] == 0


def test_percentile_ranks_are_local_and_ties_share_average_rank():
    scores, _, _ = evaluated(np.array([0,1,0]), [100,100,1], [1,2,3], [0]*3, [0]*3, 0)
    assert np.allclose(scores['blend'], [3.5/6, 4.5/6, 4/6])
    sub, _, _ = evaluated(np.array([0,1]), [100,100], [1,2], [0]*2, [0]*2, 0)
    assert np.allclose(sub['blend'], [2.5/4, 3.5/4])
    assert not np.allclose(scores['blend'][:2], sub['blend'])


def test_matched_prefix_uses_same_tp_with_hard_rows_and_stable_ties():
    assert matched_prefix(np.array([0,1,1]), [3,2,1], 1, [False]*3)['fp'] == 1
    assert matched_prefix(np.array([0,1,1]), [3,2,1], 1, [False,False,True])['fp'] == 0
    assert matched_prefix(np.array([0,1,1]), [2,2,1], 1, [False]*3)['fp'] == 1
