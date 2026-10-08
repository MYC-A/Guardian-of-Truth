"""Complete-input projection must be gold-blind and preserve old raw files."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run_projection(source, trace, output):
    return subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts/qwen_submission_reproject.py'),
                           '--input', str(source), '--traces', str(trace), '--output-dir', str(output),
                           '--expected-input-sha256', hashlib.sha256(source.read_bytes()).hexdigest()],
                          capture_output=True, text=True)


def test_full_projection_does_not_use_gold_and_keeps_original_trace(tmp_path):
    rows, records = [], []
    for identifier, decision, binary in [('001', 'NO_ERROR', 0), ('1', 'ERROR', 1)]:
        rows.append(dict(id=identifier, prompt='arbitrary input', response='arbitrary output', label=binary))
        records.append(dict(id=identifier, binary=None, error='PRIMARY_INFERENCE_FAILURE',
                            pre_steps=[dict(tag='pre_injection_budget', injected=False,
                                            transport=dict(status='NOT_EXECUTED_INPUT_BUDGET'))],
                            rec=dict(base_error=bool(binary),
                                     A=dict(final=decision, reasons=[], steps=[dict(raw_content='{}', transport=dict(status=200))]),
                                     A_adm2=dict(admission='ADMITTED', decision=decision)),
                            layer_trace=dict(findings=[])))
    trace = tmp_path / 'raw.jsonl'
    trace.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')
    original = trace.read_bytes()
    predictions = []
    for i in range(2):
        source = tmp_path / f'input{i}.parquet'
        frame = pd.DataFrame(rows)
        if i:
            frame['label'] = 1 - frame['label']
        frame.to_parquet(source)
        output = tmp_path / f'projection{i}'
        process = run_projection(source, trace, output)
        assert process.returncode == 0, process.stderr
        predictions.append(pd.read_parquet(output / 'predictions.parquet').to_dict('records'))
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        assert report['rows'] == 2 and report['model_calls'] == 0
        assert report['before']['complete'] is False
        assert report['after']['complete'] is True
        assert report['after']['metrics']['F1'] == (1 if i == 0 else 0)
    assert predictions[0] == predictions[1] == [dict(id='001', label=0), dict(id='1', label=1)]
    assert trace.read_bytes() == original


def test_missing_trace_ids_refuse_whole_input_score(tmp_path):
    source = tmp_path / 'input.parquet'
    pd.DataFrame([dict(id='a', prompt='p', response='r', label=1)]).to_parquet(source)
    trace = tmp_path / 'raw.jsonl'
    trace.write_text('', encoding='utf-8')
    output = tmp_path / 'projection'
    process = run_projection(source, trace, output)
    assert process.returncode != 0
    assert 'INCOMPLETE_OR_UNEXPECTED_TRACE_IDS' in process.stderr
    assert not output.exists()


def test_same_id_different_source_bytes_cannot_reuse_a_bound_trace(tmp_path):
    from guardian_truth.submission.cli import row_fingerprint
    source = tmp_path / 'input.parquet'
    pd.DataFrame([dict(id='a', prompt='changed policy', response='r', label=1)]).to_parquet(source)
    trace = tmp_path / 'raw.jsonl'
    trace.write_text(json.dumps(dict(id='a', input_row_sha256=row_fingerprint(dict(prompt='original policy', response='r')))),
                     encoding='utf-8')
    output = tmp_path / 'projection'
    process = run_projection(source, trace, output)
    assert process.returncode != 0
    assert 'TRACE_SOURCE_FINGERPRINT_MISMATCH' in process.stderr
    assert not output.exists()
