import copy

import pytest

from scripts.qwen_source_completion_score import analyze


def inputs():
    return [dict(id='p', wire_identical=False, control_sha256='pc', completion_sha256='pt'),
            dict(id='n', wire_identical=True, control_sha256='nc', completion_sha256='nc')]


def records():
    return [dict(id=r['id'], mode=m, request_sha256=r[m + '_sha256'],
                 result=dict(status='ADMITTED', decision='NO_ERROR', binary=0), reply=dict(content='same'))
            for r in inputs() for m in ('control', 'completion')]


def test_complete_unchanged_fresh_control_cannot_be_credited_as_improvement():
    result = analyze(records(), inputs(), {'p': 1, 'n': 0}, {'p': 0, 'n': 0})
    assert result['execution_complete'] and not result['paired_changes']
    assert result['modes']['control']['primary']['fn'] == 1
    assert result['modes']['completion']['primary'] == result['modes']['control']['primary']


def test_recovery_must_be_paired_and_missing_mode_stays_unknown():
    rows = records(); rows[1]['result'].update(decision='ERROR', binary=1)
    result = analyze(rows, inputs(), {'p': 1, 'n': 0}, {'p': 0, 'n': 0})
    assert result['paired_true_positive_recoveries'] == ['p']
    assert result['source_cause_review'] == 'PENDING'
    result = analyze(rows[:-1], inputs(), {'p': 1, 'n': 0}, {'p': 0, 'n': 0})
    assert not result['execution_complete'] and result['modes']['completion']['missing_ids'] == ['n']


@pytest.mark.parametrize('mutation', ['duplicate', 'foreign_hash', 'noop_disagreement', 'gold_mismatch', 'boolean_binary'])
def test_invalid_cohort_or_wire_cannot_be_scored(mutation):
    rows = records(); gold = {'p': 1, 'n': 0}
    if mutation == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    elif mutation == 'foreign_hash': rows[0]['request_sha256'] = 'foreign'
    elif mutation == 'noop_disagreement': rows[-1]['result'].update(decision='ERROR', binary=1)
    elif mutation == 'gold_mismatch': gold['extra'] = 0
    else: rows[0]['result']['binary'] = True
    with pytest.raises(ValueError):
        analyze(rows, inputs(), gold, {'p': 0, 'n': 0})


def test_technical_and_semantic_unknown_stay_separate_from_base_fallback():
    rows = records()
    for row in rows[:2]: row['result'].update(status='ADMITTED', decision='UNKNOWN', binary=None)
    for row in rows[2:]: row['result'].update(status='TECHNICAL_FAILURE', decision=None, binary=None)
    result = analyze(rows, inputs(), {'p': 1, 'n': 0}, {'p': 1, 'n': 0})
    mode = result['modes']['control']
    assert mode['unknown_ids'] == ['p'] and mode['technical_or_rejected_ids'] == ['n']
    assert mode['primary']['undecided'] == 2
    assert mode['frozen_full_B2_OR_primary']['tp'] == 1
