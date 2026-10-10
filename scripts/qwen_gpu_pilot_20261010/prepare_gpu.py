import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import time

BASE = Path('/workspace/guardian/pilot_20261010')
BASE.mkdir(parents=True, exist_ok=True)
CODE = BASE / 'code'
ROOT = Path('/workspace/guardian/runtime')
MODEL = ROOT / 'model/Qwen3.8-27B-Q8_0.gguf'
MODEL.parent.mkdir(parents=True, exist_ok=True)
EXPECTED_MODEL = 'aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1'
EXPECTED_CODE = '8911b35f8ca895aad5c68bbe1fca7d1721f7f867'
START = time.monotonic()


def run(args):
    print('RUN', args[0], flush=True)
    subprocess.run(args, check=True)


def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(16*1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def download():
    if not MODEL.exists():
        partial = MODEL.with_suffix('.gguf.partial')
        url = ('https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/resolve/'
               '71bc7b627595dc8a91039addd9c791ae548d6747/Qwen3.8-27B-Q8_0.gguf?download=true')
        run(['curl','-L','--fail','--silent','--show-error','--retry','0',
             '--connect-timeout','20','--max-time','1800','--continue-at','-', '-o',str(partial),url])
        if partial.stat().st_size != 28595763648 or digest(partial) != EXPECTED_MODEL:
            raise ValueError('MODEL_FINGERPRINT_MISMATCH')
        partial.rename(MODEL)
    if MODEL.stat().st_size != 28595763648 or digest(MODEL) != EXPECTED_MODEL:
        raise ValueError('MODEL_FINGERPRINT_MISMATCH')
    print('MODEL_READY', flush=True)


def environment():
    if not CODE.exists():
        run(['git','clone','--depth','1','--filter=blob:none','--sparse','--branch',
             'fix/qwen-compact-prepass-20261010','https://github.com/MYC-A/Guardian-of-Truth.git',str(CODE)])
    run(['git','-C',str(CODE),'sparse-checkout','set','src','experiments/guardian_addons',
         'experiments/guardian_semantic','scripts','tests','docs/qwen_submission_20261008',
         'docs/qwen_compact_prepass_20261010','outputs/guardian_semantic/data'])
    actual = subprocess.check_output(['git','-C',str(CODE),'rev-parse','HEAD'],text=True).strip()
    if actual != EXPECTED_CODE:
        raise ValueError('CODE_HEAD_MISMATCH')
    registry = json.loads((CODE/'docs/qwen_submission_20261008/PINNED_VENDOR_FILES.json').read_text())
    venv = BASE/'venv'
    if not (venv/'bin/python').exists():
        run(['uv','venv','--python','python3.12',str(venv)])
    packages = [d['name']+'=='+d['version'] for d in registry['distributions']]
    run(['uv','pip','install','--python',str(venv/'bin/python'),*packages,'pytest==8.4.2'])
    native = BASE/'llama.tar.gz'
    deadline = time.monotonic() + 900
    while not (native.exists() and native.stat().st_size == 52600725):
        if time.monotonic() > deadline:
            raise TimeoutError('NATIVE_UPLOAD_NOT_COMPLETE')
        time.sleep(5)
    if digest(native) != '3f748999b9e59269768fc81350a4526bacafcc57d87c5d4510b3ccdd4f606771':
        raise ValueError('NATIVE_UPLOAD_SHA_MISMATCH')
    native_root = ROOT/'runtime'
    native_root.mkdir(exist_ok=True)
    run(['tar','-xzf',str(native),'-C',str(native_root)])
    run(['chmod','755',str(native_root/'llama/llama-server')])
    run([str(native_root/'llama/llama-server'),'--version'])
    print('ENVIRONMENT_READY',flush=True)


try:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(download), ex.submit(environment)]
        for f in futures:
            f.result()
    (BASE/'setup.json').write_text(json.dumps(dict(status='READY',code_sha=EXPECTED_CODE,
        model_sha=EXPECTED_MODEL,seconds=time.monotonic()-START),indent=2))
except Exception as e:
    (BASE/'setup.json').write_text(json.dumps(dict(status='FAILED',error_type=type(e).__name__,
        error=str(e),seconds=time.monotonic()-START),indent=2))
    raise
