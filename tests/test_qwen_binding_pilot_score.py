"""Offline scoring invariants, independent of model quality or a live pilot."""
import copy
import json
import sys

import pytest

from scripts import qwen_binding_pilot_score as scorer


@pytest.fixture(autouse=True)
def offline_baseline_classification(monkeypatch):
    # These tests exercise score/cohort projection, not the existing B2 parser.
    monkeypatch.setattr(scorer, 'classify_row',
                        lambda row, *_: row.get('test_class', 'verdict') if row else 'missing')


def record(identifier, mode, addition=False, status='PROCESSED', **extra):
    return dict(id=identifier, mode=mode, status=status, automatic_addition=addition, **extra)


def paired(*ids, addition=False):
    return [record(identifier, mode, addition) for identifier in ids for mode in ('blind', 'visible')]


def analyze(records, ids=('positive', 'negative'), external=None, contrasts=None, baseline=None):
    external = {'positive': {'label': 1}, 'negative': {'label': 0}} if external is None else external
    baseline = {'positive': {'binary': 0}, 'negative': {'binary': 0}} if baseline is None else baseline
    return scorer.analyze(records, list(ids), external, contrasts or {}, baseline)


def test_complete_paired_negative_detector_keeps_binary_base_and_separate_detector_metrics():
    result = analyze(paired('positive', 'negative'))
    for mode in ('blind', 'visible'):
        row = result['modes'][mode]
        assert row['execution_complete'] and row['quality_claim_eligible']
        assert row['extra_detector_external']['decided'] == 2
        assert row['extra_detector_external']['fn'] == 1
        assert row['valid_base_with_explicit_fallback']['candidate'] == row['valid_base_with_explicit_fallback']['QB2']
        assert not row['fn_recoveries'] and not row['new_false_positive_rows']
    assert result['cause_truth'] == 'PENDING_INDEPENDENT_SOURCE_REVIEW'


def test_partial_modes_remain_distinct_and_missing_positive_is_not_detector_zero():
    rows = paired('positive', 'negative')
    rows = [r for r in rows if not (r['id'] == 'positive' and r['mode'] == 'visible')]
    result = analyze(rows)
    assert result['modes']['blind']['execution_complete']
    visible = result['modes']['visible']
    assert visible['missing_ids'] == ['positive']
    assert not visible['execution_complete'] and not visible['quality_claim_eligible']
    assert visible['extra_detector_external']['undecided_positive'] == 1
    assert visible['extra_detector_external']['fn'] == 0


def test_optional_failed_checker_fallback_is_explicit_not_detector_prediction():
    rows = paired('positive', 'negative')
    rows[0].update(status='TECHNICAL_FAILURE', automatic_addition=None)
    result = analyze(rows)['modes']['blind']
    assert result['execution_complete'] and not result['quality_claim_eligible']
    assert result['technical_or_unmeasured_ids'] == ['positive']
    assert result['extra_detector_external']['undecided_positive'] == 1
    assert result['valid_base_with_explicit_fallback']['candidate']['fn'] == 1


def test_failed_base_stays_unknown_until_candidate_positive_and_historical_projection_separate():
    baseline = {'positive': {'binary': 0, 'test_class': 'no_solution'}, 'negative': {'binary': 0}}
    rows = paired('positive', 'negative')
    before = analyze(rows, baseline=baseline)['modes']['blind']
    assert before['archived_binary_projection']['candidate']['fn'] == 1
    assert before['valid_base_with_explicit_fallback']['candidate']['undecided_positive'] == 1
    rows[0]['automatic_addition'] = True
    after = analyze(rows, baseline=baseline)['modes']['blind']
    assert after['valid_base_with_explicit_fallback']['candidate']['tp'] == 1
    assert after['fn_recoveries'] == ['positive']


def test_true_addition_to_negative_and_contrast_has_separate_false_positive_lists():
    rows = paired('positive', 'negative', 'contrast')
    for row in rows:
        if row['id'] in ('negative', 'contrast'):
            row['automatic_addition'] = True
    result = analyze(rows, ids=('positive', 'negative', 'contrast'), contrasts={'contrast': {'label': 0}})
    for mode in ('blind', 'visible'):
        assert result['modes'][mode]['new_false_positive_rows'] == ['negative']
        assert result['modes'][mode]['contrast_false_positive_rows'] == ['contrast']


@pytest.mark.parametrize('mutation', ['duplicate', 'foreign_id', 'foreign_mode'])
def test_foreign_or_duplicated_records_are_rejected(mutation):
    rows = paired('positive', 'negative')
    if mutation == 'duplicate':
        rows.append(copy.deepcopy(rows[0]))
    elif mutation == 'foreign_id':
        rows[0]['id'] = 'unregistered'
    else:
        rows[0]['mode'] = 'third-arm'
    with pytest.raises(ValueError):
        analyze(rows)


@pytest.mark.parametrize('addition', [0, 1, 'false', 'true', [], {}])
def test_non_boolean_addition_cannot_be_quality_eligible(addition):
    rows = paired('positive', 'negative')
    rows[0]['automatic_addition'] = addition
    with pytest.raises(ValueError):
        analyze(rows)


def test_gold_outside_registered_input_cannot_be_reported_as_complete():
    with pytest.raises(ValueError):
        analyze(paired('positive'), ids=('positive',))


def test_external_and_contrast_gold_cannot_double_count_same_row():
    with pytest.raises(ValueError):
        analyze(paired('positive', 'negative'), contrasts={'positive': {'label': 1}})


def test_unlabelled_runtime_id_is_counted_in_coverage_and_explicitly_reported():
    result = analyze(paired('positive', 'negative', 'unlabelled'), ids=('positive', 'negative', 'unlabelled'))
    for mode in ('blind', 'visible'):
        row = result['modes'][mode]
        assert row['observed'] == 3 and row['labelled_external'] == 2
        assert row['unlabelled_external_ids'] == ['unlabelled']
        assert row['extra_detector_external']['expected'] == 2


def test_analysis_does_not_mutate_frozen_records_or_gold():
    rows = paired('positive', 'negative')
    external = {'positive': {'label': 1}, 'negative': {'label': 0}}
    before = copy.deepcopy((rows, external))
    analyze(rows, external=external)
    assert (rows, external) == before


def test_main_refuses_duplicate_expected_inventory_before_reading_archived_gold(tmp_path, monkeypatch):
    inputs, records = tmp_path / 'inputs.jsonl', tmp_path / 'records.jsonl'
    inputs.write_text('{"id":"duplicate"}\n{"id":"duplicate"}\n', encoding='utf-8')
    records.write_text('', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['score', '--inputs', str(inputs), '--records', str(records),
                                    '--output', str(tmp_path / 'score.json')])
    monkeypatch.setattr(scorer, 'blob', lambda _: pytest.fail('invalid inventory must fail before gold read'))
    with pytest.raises(ValueError, match='DUPLICATE_EXPECTED_ID'):
        scorer.main()


def test_accounting_counts_saved_receipts_and_exposes_missing_usage():
    rows = paired('positive', 'negative')
    rows[0]['extraction'] = {'usage': {'completion_tokens': 7, 'prompt_tokens': 101}, 'cached': True}
    rows[0]['verifications'] = [{'judgment': {'verdict': 'UNRESOLVED'}, 'reply': {'usage': None, 'cached': False}}]
    result = analyze(rows)['modes']['blind']
    assert result['receipt_calls'] == 2 and result['noncached_receipts'] == 1
    assert result['input_tokens'] == 101 and result['output_tokens'] == 7
    assert result['usage_missing'] == 1
    # These are receipt counts, not the durable reservation/HTTP ledger count.
    assert result['verifier_counts'] == {'UNRESOLVED': 1}


def baseline_record():
    return dict(id='same', binary=0, status='OK',
                rec={'A': {'steps': [{'cached': False, 'key': 'exact-request-key',
                                     'raw_content': '{"decision":"NO_ERROR"}', 'admission': 'ADMITTED'}]}},
                pre_steps=[{'cached': False, 'key': 'exact-prepass-key', 'parsed_ok': True}])


def test_baseline_loader_accepts_only_cache_metadata_duplicate_and_returns_audit_receipt():
    first = baseline_record()
    second = copy.deepcopy(first)
    second['rec']['A']['steps'][0]['cached'] = True
    second['pre_steps'][0]['cached'] = True
    before = copy.deepcopy((first, second))
    mapping, receipt = scorer.load_baseline([first, second])
    assert set(mapping) == {'same'} and mapping['same']['binary'] == 0
    assert isinstance(receipt, dict) and receipt
    assert (first, second) == before


@pytest.mark.parametrize('mutation', ['raw', 'request_key', 'admission', 'binary'])
def test_same_binary_or_same_id_does_not_justify_selecting_a_changed_archived_attempt(mutation):
    first = baseline_record()
    second = copy.deepcopy(first)
    step = second['rec']['A']['steps'][0]
    if mutation == 'raw':
        step['raw_content'] = '{"decision":"UNKNOWN"}'
    elif mutation == 'request_key':
        step['key'] = 'different-request-key'
    elif mutation == 'admission':
        step['admission'] = 'REJECTED_ACTOR'
    else:
        second['binary'] = 1
    with pytest.raises(ValueError):
        scorer.load_baseline([first, second])
