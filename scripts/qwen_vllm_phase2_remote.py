"""Phase 2 (install rescue + full B2 on vLLM/FP8) coordinator, run ON the research server.

New roots only; previous setup/phase directories and their logs stay untouched
except the model directory, which is renamed in place to its pinned revision
name after full verification (no copy of 31 GB).

    python3 scripts/qwen_vllm_phase2_remote.py --source-sha <FULL_SHA> [--start]

Without --start it only writes run.py + supervisor config and prints them.
Phases (each bounded by /usr/bin/timeout, ledger in phase_ledger.json):
  install            fresh venv, offline --no-index --no-deps from verified wheelhouse
  import_check       uv pip check + versions + torch.cuda
  processor_asset    pinned video_preprocessor_config.json (amended protocol saved separately)
  asset_verification upstream LFS SHA256 / Git blob for every file
  cpu_config_tokenizer AutoConfig/Tokenizer/Processor local_files_only, thinking off
  gpu_smoke          2 first rows, workers1 slots8 ctx32768, 180s HTTP, 600s, 24 calls, eager
  full_valid46       46 rows, workers8 slots8, 600s HTTP, 1800s, 400 calls, eager
  score_valid46      labels read only here
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--source-sha', required=True)
parser.add_argument('--start', action='store_true')
args = parser.parse_args()
if re.fullmatch(r'[0-9a-f]{40}', args.source_sha) is None:
    parser.error('full lowercase SHA required')

BASE = Path('/workspace/guardian/vllm_phase2_20261010')
BASE.mkdir(exist_ok=False)
CODE = BASE / 'code'
subprocess.run(['git', 'clone', '--filter=blob:none', '--sparse', '--depth', '1', '--single-branch',
                '--branch', 'perf/qwen-inference-20261010', 'https://github.com/MYC-A/Guardian-of-Truth.git',
                str(CODE)], check=True, timeout=120)
head = subprocess.check_output(['git', '-C', str(CODE), 'rev-parse', 'HEAD'], text=True).strip()
if head != args.source_sha:
    raise SystemExit(f'SOURCE_SHA_MISMATCH remote={head} expected={args.source_sha}')
subprocess.run(['git', '-C', str(CODE), 'sparse-checkout', 'set', 'src', 'scripts', 'tests',
                'experiments/guardian_semantic', 'experiments/guardian_addons', 'experiments/guardian_local_a100'],
               check=True, timeout=120)

RUNNER = r'''from pathlib import Path
import glob, hashlib, json, os, signal, subprocess, time, traceback
ROOT = Path(__file__).resolve().parent
CODE = ROOT / 'code'
OLD = Path('/workspace/guardian/vllm_probe_20261010')
RESCUE = Path('/workspace/guardian/vllm_rescue_20261010')
REV = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
VENV = ROOT / 'venv'
PYTHON = str(VENV / 'bin/python')
TARGET = OLD / REV
env = dict(os.environ, PYTHONPATH=str(CODE / 'src') + ':' + str(CODE), PYTHONUTF8='1',
           PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='8', PYTHONNOUSERSITE='1',
           HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1')
for key in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONHOME', 'VIRTUAL_ENV'):
    env.pop(key, None)
ledger = []

CHILD = []

def _stop(signum, frame):
    # timeout(1) puts itself in its own process group; forward TERM to it so
    # the running phase (and vLLM via the adapter's own cleanup) stops too.
    for proc in CHILD:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    raise SystemExit(128 + signum)

signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

def phase(name, command, timeout, extra_env=None):
    started = time.monotonic()
    (ROOT / 'ACTIVE_PHASE.json').write_text(json.dumps(dict(phase=name, started_unix=time.time(),
                                                            online=bool(extra_env))))
    with (ROOT / (name + '.stdout.log')).open('x') as out, (ROOT / (name + '.stderr.log')).open('x') as err:
        proc = subprocess.Popen(['/usr/bin/timeout', '--signal=TERM', '--kill-after=30', str(timeout), *command],
                                cwd=CODE, env=dict(env, **(extra_env or {})), stdout=out, stderr=err)
        CHILD[:] = [proc]
        try:
            rc = proc.wait()
        finally:
            CHILD.clear()
    ledger.append(dict(phase=name, returncode=rc, seconds=round(time.monotonic() - started, 2)))
    (ROOT / 'phase_ledger.json').write_text(json.dumps(ledger, indent=2))
    if rc:
        raise RuntimeError('PHASE_FAILED:' + name + ':' + str(rc))

try:
    fetch = json.loads((RESCUE / 'wheelhouse/FETCH_SUMMARY.json').read_text())
    report = json.loads((RESCUE / 'dep_report.json').read_text())
    if fetch.get('status') != 'COMPLETE' or fetch.get('incomplete'):
        raise RuntimeError('WHEELHOUSE_NOT_COMPLETE')
    from urllib.parse import unquote, urlsplit
    expected = {unquote(urlsplit(i['download_info']['url']).path.rsplit('/', 1)[1]):
                i['download_info']['archive_info']['hashes']['sha256'] for i in report['install']}
    fetched = {w['name']: w['sha256'] for w in fetch['wheels']}
    if expected != fetched or len(expected) != len(report['install']) or report.get('missing'):
        raise RuntimeError('WHEELHOUSE_REPORT_MISMATCH')
    lines = []
    for name, digest in sorted(expected.items()):
        path = RESCUE / 'wheelhouse' / name
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1 << 22), b''):
                h.update(block)
        if h.hexdigest() != digest:
            raise RuntimeError('WHEEL_SHA_MISMATCH:' + name)
        lines.append(f'{path} --hash=sha256:{digest}')
    (ROOT / 'wheels.lock.txt').write_text('\n'.join(lines) + '\n')
    if VENV.exists():
        raise RuntimeError('VENV_ALREADY_EXISTS')
    if (OLD / 'model').exists() and TARGET.exists():
        raise RuntimeError('BOTH_MODEL_AND_TARGET_EXIST')
    status = subprocess.run(['supervisorctl', 'status', 'guardian_vllm_phase_20261010', 'guardian_vllm_setup_20261010'],
                            capture_output=True, text=True, timeout=30).stdout
    if 'RUNNING' in status or 'STARTING' in status:
        raise RuntimeError('OLD_PHASE_ACTIVE:' + status)
    online = dict(HF_HUB_OFFLINE='0', TRANSFORMERS_OFFLINE='0')
    phase('install', ['bash', '-c', 'uv venv --python /usr/bin/python3.12 "$0" && uv pip install --python "$0/bin/python" '
          '--offline --no-index --no-deps --no-cache --require-hashes -r "$1"', str(VENV), str(ROOT / 'wheels.lock.txt')], 900)
    check = (r"""import json, sys, torch, vllm, transformers, pandas, pyarrow
print(json.dumps(dict(python=sys.version, torch=torch.__version__, cuda=torch.version.cuda,
    cuda_available=torch.cuda.is_available(), device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    vllm=vllm.__version__, transformers=transformers.__version__, pandas=pandas.__version__, pyarrow=pyarrow.__version__)))
assert vllm.__version__ == '0.19.1' and transformers.__version__ == '5.8.0' and torch.cuda.is_available()
""")
    phase('import_check', ['bash', '-c', 'uv pip check --python "$0" && "$0" -c "$1"', PYTHON, check], 300)
    frozen = subprocess.check_output(['uv', 'pip', 'freeze', '--python', PYTHON], env=env, text=True, timeout=120)
    (ROOT / 'requirements-frozen.txt').write_text(frozen)
    (RESCUE / 'SETUP_DONE.json').write_text(json.dumps(dict(status='COMPLETE', venv=str(VENV),
        wheels=len(lines), frozen_sha_lines=len(frozen.splitlines()))))
    source_model = OLD / 'model'
    model_dir = TARGET if TARGET.exists() else source_model
    patch = r"""import json, pathlib, sys
from huggingface_hub import snapshot_download
old = pathlib.Path('/workspace/guardian/vllm_probe_20261010')
out = pathlib.Path(sys.argv[1]); model = sys.argv[2]
p = json.loads((old / 'DOWNLOAD_PROTOCOL.json').read_text())
snapshot_download(p['repo'], revision=p['revision'], local_dir=model,
                  allow_patterns=['video_preprocessor_config.json'], max_workers=1)
p['files'] = sorted(set(p['files']) | {'video_preprocessor_config.json'})
p['amendment'] = 'Add pinned video processor config required for multimodal processor initialization'
(out / 'AMENDED_DOWNLOAD_PROTOCOL.json').write_text(json.dumps(p, indent=2))
"""
    phase('processor_asset', [str(OLD / 'download_venv/bin/python'), '-c', patch, str(ROOT), str(model_dir)], 300, online)
    phase('asset_verification', [str(OLD / 'download_venv/bin/python'), str(CODE / 'scripts/qwen_vllm_verify_assets.py'),
          '--model-dir', str(model_dir), '--download-protocol', str(ROOT / 'AMENDED_DOWNLOAD_PROTOCOL.json'),
          '--output', str(ROOT / 'verified_asset_manifest.json')], 900, online)
    if model_dir == source_model:
        source_model.rename(TARGET)
    cpu = r"""import json, pathlib, sys, transformers
from transformers import AutoConfig, AutoTokenizer, AutoProcessor
model = pathlib.Path(sys.argv[1])
config = AutoConfig.from_pretrained(model, local_files_only=True)
tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
processor = AutoProcessor.from_pretrained(model, local_files_only=True)
messages = [{'role': 'system', 'content': 'Be concise.'}, {'role': 'user', 'content': 'Say ok.'}]
ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
pathlib.Path(sys.argv[2]).write_text(json.dumps(dict(transformers=transformers.__version__, model_type=config.model_type,
    tokenizer=type(tokenizer).__name__, processor=type(processor).__name__, rendered_prompt=text,
    rendered_tokens=ids if isinstance(ids, list) else list(ids['input_ids']), status='COMPLETE'), indent=2))
"""
    phase('cpu_config_tokenizer', [PYTHON, '-c', cpu, str(TARGET), str(ROOT / 'CPU_SMOKE.json')], 300)
    def gpu_free():
        active = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid,process_name',
                                          '--format=csv,noheader'], text=True, timeout=60).strip()
        used = int(subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
                                           text=True, timeout=60).split()[0])
        if active or used > 2048:
            raise RuntimeError(f'GPU_OCCUPIED: apps={active!r} memory_used_mib={used}')
    gpu_free()
    common = [PYTHON, '-u', str(CODE / 'scripts/qwen_vllm_adapter.py'), '--python', PYTHON, '--model-dir', str(TARGET),
              '--asset-manifest', str(ROOT / 'verified_asset_manifest.json'), '--input', str(CODE / 'valid.parquet'),
              '--slots', '8', '--context', '32768', '--enforce-eager']
    phase('gpu_smoke', [*common, '--output', str(ROOT / 'smoke'), '--limit', '2', '--workers', '1',
          '--timeout', '180', '--duration', '600', '--max-calls', '24'], 660)
    smoke = json.loads((ROOT / 'smoke/DONE.json').read_text())
    if smoke['rows'] != 2 or smoke['default_zero_fallbacks'] or smoke['technical_calls']:
        raise RuntimeError('GPU_SMOKE_HAS_TECHNICAL_GAPS')
    gpu_free()
    phase('full_valid46', [*common, '--output', str(ROOT / 'valid46'), '--limit', '46', '--workers', '8',
          '--timeout', '600', '--duration', '1800', '--max-calls', '400'], 1860)
    scoring = r"""import json, pathlib, sys, pandas as pd
root = pathlib.Path(sys.argv[1])
truth = pd.read_parquet(root / 'code/valid.parquet').set_index('id')['label']
pred = pd.read_parquet(root / 'valid46/predictions.parquet').set_index('id')['label']
assert len(truth) == len(pred) == 46 and truth.index.is_unique and pred.index.is_unique and set(truth.index) == set(pred.index)
counts = {k: 0 for k in ('TP', 'FP', 'FN', 'TN')}
for i, label in truth.items():
    value = int(pred[i]); assert value in (0, 1)
    counts[('TN', 'FP', 'FN', 'TP')[2 * int(label) + value]] += 1
counts['F1'] = 2 * counts['TP'] / max(1, 2 * counts['TP'] + counts['FP'] + counts['FN'])
(root / 'score_valid46.json').write_text(json.dumps(dict(metrics=counts,
    scope='Full B2 on vLLM 0.19.1 + official FP8, one development repetition; engine+quant changed together'), indent=2))
"""
    phase('score_valid46', [PYTHON, '-c', scoring, str(ROOT)], 120)
    (ROOT / 'DONE.json').write_text(json.dumps(dict(status='COMPLETE', phases=ledger)))
except BaseException:
    (ROOT / 'FAILED.txt').write_text(traceback.format_exc())
    raise
'''
(BASE / 'run.py').write_text(RUNNER)
(BASE / 'STARTED.json').write_text(json.dumps(dict(source_sha=head, scope='vLLM install rescue + full B2 on FP8',
                                                    outer_cap_seconds=7200)))
name = 'guardian_vllm_phase2_20261010'
state = subprocess.run(['supervisorctl', 'status', name], capture_output=True, text=True, timeout=30).stdout
if 'RUNNING' in state or 'STARTING' in state:
    raise SystemExit('PHASE2_ALREADY_ACTIVE: ' + state)
with (Path('/etc/supervisor/conf.d') / (name + '.conf')).open('w') as stream:
    stream.write(f"""[program:{name}]
command=/usr/bin/timeout --signal=TERM --kill-after=30 7200 /usr/bin/python3 -u {BASE}/run.py
directory={BASE}
autostart=false
autorestart=false
startsecs=2
stopasgroup=true
killasgroup=true
stdout_logfile={BASE}/stdout.log
stderr_logfile={BASE}/stderr.log
""")
if args.start:
    for command in (['supervisorctl', 'reread'], ['supervisorctl', 'update', name], ['supervisorctl', 'start', name]):
        subprocess.run(command, check=True, timeout=30)
print(json.dumps(dict(status='LAUNCHED' if args.start else 'PREPARED', program=name, source_sha=head, root=str(BASE))))
