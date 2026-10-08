"""Linux ZIP permission, offline install and unprivileged native-runtime smoke.

Uses a tiny declared model fixture to roundtrip the runtime without copying
30GB. This is NOT a GPU/model-quality test or a Docker-engine test.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    a = ap.parse_args()
    if sys.platform != 'linux' or os.getuid() != 0:
        raise RuntimeError('SMOKE_REQUIRES_LINUX_ROOT_FOR_RUNUSER')
    if a.output_dir.exists():
        raise ValueError('SMOKE_OUTPUT_ALREADY_EXISTS')
    a.output_dir.mkdir(parents=True)
    a.output_dir.chmod(0o755)
    started = time.monotonic()
    fixture, extracted, work = (a.output_dir / n for n in ('fixture', 'extracted', 'work'))
    shutil.copytree(a.stage, fixture, copy_function=os.link,
                    ignore=shutil.ignore_patterns('model', 'MANIFEST.json', '__pycache__', '*.pyc'))
    (fixture / 'model').mkdir()
    model = fixture / 'model/Qwen3.8-27B-Q8_0.gguf'
    model.write_bytes(b'CPU_ZIP_PERMISSION_FIXTURE_NOT_MODEL_WEIGHTS\n')
    spec = importlib.util.spec_from_file_location('builder', ROOT / 'scripts/build_qwen_submission.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    manifest = dict(fixture_only=True, model_sha256=builder.digest(model), model_bytes=model.stat().st_size,
                    files={p.relative_to(fixture).as_posix(): dict(bytes=p.stat().st_size, sha256=builder.digest(p))
                           for p in builder.artifact_files(fixture) if p != model})
    (fixture / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
    archive = a.output_dir / 'runtime-only-fixture.zip'
    builder.archive(fixture, archive)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError('ZIP_CRC_FAILURE')
    subprocess.run(['unzip', '-q', str(archive), '-d', str(extracted)], check=True)
    work.mkdir(mode=0o777)
    work.chmod(0o777)
    source = work / 'empty.csv'
    source.write_text('id,prompt,response\n', encoding='utf-8')
    logs = {}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PIP_NO_INDEX='1', PIP_NO_CACHE_DIR='1')
    def run(name, command, environment=env):
        result = subprocess.run(['runuser', '-u', 'nobody', '--', *command], env=environment,
                                text=True, capture_output=True, timeout=120)
        (a.output_dir / (name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        logs[name] = result.returncode
        if result.returncode:
            raise RuntimeError(name + '_FAILED')
    run('offline_install', [sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                            '--target', str(work / 'installed'), str(extracted)])
    run('empty_entrypoint', [sys.executable, str(extracted / 'scripts/predict.py'),
                             '--input', str(source), '--output', str(work / 'predictions.csv')])
    if (work / 'predictions.csv').read_bytes()[:4] != b'PAR1':
        raise RuntimeError('DEFAULT_OUTPUT_NOT_PARQUET')
    native_env = dict(env, PYTHONHOME=str(extracted / 'runtime/python'), GUARDIAN_BUNDLED_PYTHON='1',
                      LD_LIBRARY_PATH=str(extracted / 'runtime/lib'))
    code = ('import sys; from pathlib import Path; p=Path(sys.argv[1]); '
            'sys.path[:0]=[str(p/"src"),str(p),str(p/"runtime/site-packages")]; '
            'import pandas, pyarrow, pydantic, jsonschema; '
            'from guardian_truth.repair.v5 import run_v5; '
            'from guardian_truth.v6fix.pipeline import Layers; '
            'from experiments.guardian_addons.variants2 import Hook2; '
            'print("BUNDLED_NATIVE_IMPORTS_OK",sys.version)')
    run('bundled_imports', [str(extracted / 'runtime/lib/ld-linux-x86-64.so.2'), '--library-path',
                            str(extracted / 'runtime/lib'), str(extracted / 'runtime/python/bin/python3.12'),
                            '-c', code, str(extracted)], native_env)
    report = dict(scope='runtime-only ZIP fixture, no GPU, no Docker daemon',
                  stage=str(a.stage), cli_sha256=builder.digest(extracted / 'src/guardian_truth/submission/cli.py'),
                  elapsed_seconds=time.monotonic() - started, zip_bytes=archive.stat().st_size,
                  zip_sha256=builder.digest(archive), logs=logs,
                  model_quality_test=False, actual_weight_roundtrip=False)
    (a.output_dir / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
