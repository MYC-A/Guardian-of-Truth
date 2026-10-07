"""Checks for the offline analysis' coverage and overlap accounting."""
import json

import pytest

from experiments.guardian_local_a100.method_synthesis import load_rows, metrics, pair_report


def test_unavailable_rows_are_bounded_not_silent_negatives():
    result = metrics({'positive': 1, 'negative': 0},
                     {'positive': 1, 'negative': 0, 'missing_positive': 1, 'missing_negative': 0})
    assert result['usable_rows'] == 2
    assert result['conditional_f1'] == 1.0
    assert result['unavailable_positive'] == result['unavailable_negative'] == 1
    assert result['full_set_f1_assignment_bounds'] == [0.5, 1.0]


def test_pair_does_not_invent_missing_model_answers():
    result = pair_report({'a': 1, 'b': 1}, {'a': 0}, {'a': 1, 'b': 1})
    assert result['common_rows'] == 1
    assert result['excluded_ids'] == ['b']
    assert result['offline_or']['TP'] == 1
    assert result['offline_and']['FN'] == 1


def test_duplicate_or_foreign_ids_fail_closed():
    data = json.dumps({'id': 'a'}).encode()
    with pytest.raises(ValueError, match='Duplicate or unexpected'):
        load_rows(data + b'\n' + data, {'a': 1})
    with pytest.raises(ValueError, match='Duplicate or unexpected'):
        load_rows(data, {'b': 1})


def test_zero_positive_denominator_is_defined():
    assert metrics({'a': 0}, {'a': 0})['conditional_f1'] == 0.0
