from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request

BASE = Path('/workspace/guardian/pilot_20261010')
MODEL = Path('/workspace/guardian/runtime/model/Qwen3.8-27B-Q8_0.gguf')
TOTAL = 28595763648
SHA = 'aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1'
URL = ('https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/resolve/'
       '71bc7b627595dc8a91039addd9c791ae548d6747/Qwen3.8-27B-Q8_0.gguf?download=true')
prefix = MODEL.with_suffix('.gguf.partial')
target = MODEL.with_suffix('.gguf.parallel.partial')
START = time.monotonic()
lock = threading.Lock()
progress = {}


def record(status):
    data = dict(status=status, prefix_bytes=begin, written_bytes=begin+sum(progress.values()),
                total_bytes=TOTAL, seconds=round(time.monotonic()-START,2))
    tmp = BASE/'download_progress.tmp'
    tmp.write_text(json.dumps(data))
    tmp.replace(BASE/'download_progress.json')


def fetch(index, start, end):
    req = urllib.request.Request(URL,headers={'Range':f'bytes={start}-{end}'})
    with urllib.request.urlopen(req,timeout=60) as response:
        if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{TOTAL}':
            raise ValueError('RANGE_RESPONSE_MISMATCH')
        pos = start
        fd = os.open(target,os.O_WRONLY)
        try:
            while pos <= end:
                if time.monotonic()-START > 1800:
                    raise TimeoutError('DOWNLOAD_DEADLINE')
                block = response.read(min(4*1024*1024,end-pos+1))
                if not block:
                    raise ValueError('INCOMPLETE_RANGE')
                offset = 0
                while offset < len(block):
                    n = os.pwrite(fd,block[offset:],pos+offset)
                    if n <= 0: raise OSError('SHORT_PWRITE')
                    offset += n
                pos += len(block)
                with lock:
                    progress[index] = pos-start
                    record('DOWNLOADING')
        finally:
            os.close(fd)
    print('RANGE_COMPLETE',index,end-start+1,flush=True)


if MODEL.exists():
    raise ValueError('MODEL_ALREADY_PRESENT')
if target.exists():
    raise ValueError('PARALLEL_TARGET_EXISTS')
begin = prefix.stat().st_size
if not 0 <= begin < TOTAL:
    raise ValueError('INVALID_PREFIX_SIZE')
subprocess.run(['cp','--reflink=auto',str(prefix),str(target)],check=True)
with target.open('r+b') as f: f.truncate(TOTAL)
record('DOWNLOADING')
try:
    with ThreadPoolExecutor(max_workers=4) as ex:
        size = (TOTAL-begin+3)//4
        fs = [ex.submit(fetch,i,begin+i*size,min(TOTAL-1,begin+(i+1)*size-1))
              for i in range(4) if begin+i*size < TOTAL]
        for f in as_completed(fs): f.result()
    record('VERIFYING_SHA256')
    h = hashlib.sha256()
    with target.open('rb') as f:
        for block in iter(lambda:f.read(16*1024*1024),b''):h.update(block)
    if target.stat().st_size != TOTAL or h.hexdigest() != SHA:
        raise ValueError('MODEL_SHA_MISMATCH')
    target.rename(MODEL)
    record('VERIFIED')
    subprocess.run(['/usr/bin/python3','-u',str(BASE/'prepare_gpu.py')],check=True)
    runner = BASE/'run_pilot.py'
    deadline = time.monotonic()+300
    while not runner.exists():
        if time.monotonic()>deadline:raise TimeoutError('PILOT_RUNNER_MISSING')
        time.sleep(5)
    subprocess.run([str(BASE/'venv/bin/python'),'-u',str(runner)],check=True)
except Exception:
    record('FAILED')
    raise
