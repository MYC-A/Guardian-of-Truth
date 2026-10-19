"""Finite supervised invocation of the unchanged production-format 35B evaluator."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

LAB = Path('/workspace/guardian-lab-20261018')
ROOT = LAB / 'code'
JOB = LAB / 'v3-20261019/e2-reference-v1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n')


def main():
    start = time.time()
    assert not (JOB / 'START.json').exists(), 'NO_RESULT_CACHE_OR_AUTORESTART'
    plan = json.loads((JOB / 'INPUTS.json').read_bytes())
    for name, digest in plan['files'].items():
        assert sha(JOB / name) == digest, ('INPUT_CHANGED', name)
    config = LAB / 'runs/regression_r1/judge_config.json'
    assert json.loads(config.read_bytes()) == json.loads((JOB / 'judge_config.json').read_bytes())
    weights = json.loads((LAB / 'models/qwen36-awq/VERIFIED.json').read_bytes())
    assert weights['revision'] == '00fcea2d3bcf5389b518d4fc082e5590e0ba4844'
    assert weights['repository'] == 'cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit'
    source = [ROOT / 'scripts' / name for name in
              ('eval_judge_valid.py', 'judge_stage.py', 'judge_submission.py')]
    source += list((ROOT / 'src/guardian_truth').rglob('*.py'))
    for path in source:
        dest = JOB / 'executed_code' / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    shutil.copyfile(Path(__file__), JOB / 'executed_runner.py')
    record = dict(started_unix=start, protocol_commit='b037ed69', rows=455,
                  weights=weights, config_sha256=sha(config), input_manifest=plan,
                  source_sha256={str(p.relative_to(ROOT)): sha(p) for p in source},
                  runner_sha256=sha(Path(__file__)), status='EXPLORATORY_ONLY')
    dump(JOB / 'START.json', record)
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), HF_HUB_OFFLINE='1',
               TRANSFORMERS_OFFLINE='1', VLLM_NO_USAGE_STATS='1',
               TOKENIZERS_PARALLELISM='false', PYTHON_DOTENV_DISABLED='1')
    cmd = [sys.executable, str(ROOT / 'scripts/eval_judge_valid.py'),
           '--input', str(JOB / 'inputs.csv'), '--labels-file', str(JOB / 'labels.jsonl'),
           '--config', str(config), '--model', str(LAB / 'models/qwen36-awq'),
           '--rates', '.40', '--seconds', '7200', '--out', str(JOB / 'run')]
    try:
        with (JOB / 'eval.log').open('w', buffering=1) as stream:
            result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=7350)
        assert result.returncode == 0, ('EVALUATOR_EXIT', result.returncode)
        import csv
        with (JOB / 'run/rows.csv').open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 455
        for i, row in enumerate(rows):
            assert row['id'] == plan['rows'][i]['id']
            assert all(math.isfinite(float(row[k])) for k in ('score', 'primary_score', 'final_score'))
            assert float(row['score']) == max(float(row['primary_score']), float(row['final_score']))
        summary = json.loads((JOB / 'run/summary.json').read_bytes())
        assert summary['stage_exit'] == 0 and summary['review']['final_scored'] == 455
        assert summary['ranking'] == 'max_exact_overall_final'
        record.update(complete=True, exact_primary=455, exact_final=455, rows=455,
                      wall_seconds=time.time()-start,
                      outputs_sha256={p.name: sha(p) for p in (JOB / 'run').iterdir() if p.is_file()})
        dump(JOB / 'DONE.json', record)
        print(json.dumps(dict(complete=True, rows=455, seconds=time.time()-start)), flush=True)
    except Exception as exc:
        dump(JOB / 'FAIL.json', dict(complete=False, error_type=type(exc).__name__,
                                    error=str(exc), seconds=time.time()-start))
        raise


if __name__ == '__main__':
    main()
