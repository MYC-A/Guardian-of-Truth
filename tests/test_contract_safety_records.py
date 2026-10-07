import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import pytest

from experiments.research_records import charged_usage, expected_for_score, freeze_phase, load_records, technical_gaps, failed_record
from guardian_truth.file_lock import process_lock


def write(path, *records):
    path.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')


def test_retry_only_after_technical_failure_and_full_denominator(tmp_path):
    path = tmp_path / 'rep.jsonl'
    write(path, dict(id='a', error='timeout'), dict(id='a', binary=1), dict(id='b', binary=0))
    records, receipt = load_records(path, ['a', 'b'])
    assert records['a']['binary'] == 1 and receipt['retry_chains'] == {'a': 2}
    with pytest.raises(ValueError, match='MISSING_IDS'):
        load_records(path, ['a', 'b', 'c'])
    assert load_records(path, ['a', 'b', 'c'], allow_missing=True)[1]['missing'] == ['c']


@pytest.mark.parametrize('last', [dict(id='a', binary=0), dict(id='a', binary=1), dict(id='a', error='late failure')])
def test_no_second_attempt_after_a_success(tmp_path, last):
    path = tmp_path / 'rep.jsonl'
    write(path, dict(id='a', binary=1), last)
    with pytest.raises(ValueError, match='RECORD_AFTER_SUCCESS'):
        load_records(path, ['a'])


def test_partial_phase_requires_explicit_manifest_or_override(tmp_path):
    path = tmp_path / 'C_rep2.jsonl'
    write(path, dict(id='a', binary=1))
    assert expected_for_score(path, ['a', 'b']) == ['a', 'b']
    assert expected_for_score(path, ['a', 'b'], {'C_rep2': ['a']}) == ['a']
    with pytest.raises(ValueError, match='EXPECTED_IDS_OUTSIDE_GOLD'):
        expected_for_score(path, ['a'], {'C_rep2': ['invented']})


def test_process_lock_releases_on_exception(tmp_path):
    path = tmp_path / 'ledger.lock'
    with pytest.raises(RuntimeError):
        with process_lock(path):
            raise RuntimeError('test')
    with process_lock(path):
        assert path.exists()


@pytest.mark.parametrize('binary', [None, True, '0', 2])
def test_malformed_success_is_not_a_negative_prediction(tmp_path, binary):
    path = tmp_path / 'bad.jsonl'
    write(path, dict(id='a', binary=binary))
    with pytest.raises(ValueError, match='INVALID_BINARY_RECORD'):
        load_records(path, ['a'])


def test_resume_fingerprint_covers_input_code_and_config(tmp_path):
    source = tmp_path / 'src/guardian_truth/example.py'
    source.parent.mkdir(parents=True)
    source.write_text('value = 1\n', encoding='utf-8')
    helper = tmp_path / 'experiments/research_records.py'
    helper.parent.mkdir(parents=True)
    helper.write_text('# helper\n', encoding='utf-8')
    path = tmp_path / 'runs/rep1.jsonl'
    config, inputs = {'model': 'test'}, [{'id': 'a', 'prompt': 'original'}]
    first = freeze_phase(path, tmp_path, config, inputs)
    assert freeze_phase(path, tmp_path, config, inputs) == first
    for new_config, new_inputs in [({'model': 'changed'}, inputs), (config, [{'id': 'a', 'prompt': 'changed'}])]:
        with pytest.raises(ValueError, match='PHASE_FINGERPRINT_CHANGED'):
            freeze_phase(path, tmp_path, new_config, new_inputs)
    source.write_text('value = 2\n', encoding='utf-8')
    with pytest.raises(ValueError, match='PHASE_FINGERPRINT_CHANGED'):
        freeze_phase(path, tmp_path, config, inputs)


@pytest.mark.parametrize('module_name', ['guardian_semantic', 'guardian_addons'])
def test_missing_usage_keeps_output_reservation_and_429_attempts_are_bounded(tmp_path, monkeypatch, module_name):
    import importlib
    budget = importlib.import_module('experiments.' + module_name + '.budget')
    folder = tmp_path / module_name
    monkeypatch.setattr(budget, 'DIR', folder)
    monkeypatch.setattr(budget, 'LEDGER', folder / 'ledger.jsonl')
    monkeypatch.setattr(budget, 'LOCK', folder / 'lock')
    monkeypatch.setattr(budget, 'MIN_INTERVAL', 0)
    monkeypatch.setattr(budget, 'CAPS', dict(attempts=2, requests=2, tokens=10000, usd=1))
    payload = dict(model='ministral-14b-2512', messages=[dict(role='user', content='тест')], max_tokens=512)
    monkeypatch.setattr(budget.T, 'post', lambda *a, **k: ({'choices': []}, {'status': 200}))
    budget.sender('unused', 'unused', payload)
    expected = len(json.dumps(payload).encode('utf-8')) + 256 + 512
    assert budget.totals()['tokens'] == expected
    monkeypatch.setattr(budget.T, 'post', lambda *a, **k: (None, {'status': 429}))
    assert budget.sender('unused', 'unused', payload)[1]['status'] == 'RATE_LIMITED_GIVE_UP'
    assert budget.totals()['attempts'] == 2
    assert budget.sender('unused', 'unused', payload)[1]['status'] == 'BUDGET_REFUSED'


@pytest.mark.parametrize('usage', [None, {}, {'total_tokens': 4000}, {'prompt_tokens': 5},
                                  {'prompt_tokens': -1, 'completion_tokens': 4},
                                  {'prompt_tokens': True, 'completion_tokens': 4}])
def test_partial_usage_cannot_release_reservation(usage):
    assert charged_usage({'usage': usage}, 300, 500) == (300, 500, True)


def test_exact_zero_usage_is_valid():
    assert charged_usage({'usage': {'prompt_tokens': 0, 'completion_tokens': 0}}, 300, 500) == (0, 0, False)


def test_lock_serializes_independent_processes(tmp_path):
    counter = tmp_path / 'counter'
    counter.write_text('0', encoding='utf-8')
    program = '''from pathlib import Path
import sys
from guardian_truth.file_lock import process_lock
counter = Path(sys.argv[1])
for _ in range(20):
    with process_lock(counter.with_suffix('.lock')):
        value = int(counter.read_text(encoding='utf-8'))
        counter.write_text(str(value + 1), encoding='utf-8')
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'), PYTHONDONTWRITEBYTECODE='1')
    def run(_):
        return subprocess.run([sys.executable, '-c', program, str(counter)], env=env,
                              capture_output=True, text=True, timeout=30)
    with ThreadPoolExecutor(4) as executor:
        results = list(executor.map(run, range(4)))
    assert all(result.returncode == 0 for result in results), [result.stderr for result in results]
    assert counter.read_text(encoding='utf-8') == '80'


def test_optional_verifier_failure_is_visible_without_forcing_whole_row_retry():
    record = dict(id='a', binary=0, rec=dict(A=dict(steps=[]), pool=[dict(verification_status='TECHNICAL_FAILURE')]))
    assert not failed_record(record)
    assert technical_gaps(record) == [dict(path='/rec/pool/0', status='TECHNICAL_FAILURE')]


def test_successful_retry_does_not_count_resolved_first_failure():
    record = dict(rec=dict(pool=[dict(verification_status='SUPPORTED', verify=dict(admission='ADMITTED',
                  first_invalid=dict(admission='INVALID_JSON')))]))
    assert technical_gaps(record) == []
