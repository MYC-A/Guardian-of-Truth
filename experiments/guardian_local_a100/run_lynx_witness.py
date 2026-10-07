"""Finite supervised server lifecycle for the preregistered Lynx witness repair."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from guardian_truth.file_lock import process_lock
from experiments.guardian_local_a100.continue_circle import publish

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('/workspace/guardian')
BRANCH = 'fix/guardian-lynx-witness-20261007'
MODEL = 'llama-3-patronus-lynx-70b@581017200918:IQ4_XS:llamacpp-b11459'
OUT = ROOT/'outputs/guardian_lynx_witness_20261007'


def main():
    os.environ.update(PYTHONPATH=str(ROOT/'src')+':'+str(ROOT), PYTHONDONTWRITEBYTECODE='1',
                      GUARDIAN_DATA_ROOT=str(BASE/'data_root_403d811e'),
                      LOCAL_LLAMACPP_ENDPOINT='http://127.0.0.1:8081/v1/chat/completions',
                      GIT_TERMINAL_PROMPT='0')
    # The publication helper's ROOT/BRANCH are bound in its original module.
    from experiments.guardian_local_a100 import continue_circle as publication
    publication.ROOT, publication.BRANCH = ROOT, BRANCH
    OUT.mkdir(parents=True,exist_ok=True)
    def state(status, **extra):
        value=dict(status=status,utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**extra)
        (OUT/'state.tmp').write_text(json.dumps(value),encoding='utf-8')
        (OUT/'state.tmp').replace(OUT/'state.json')
        print(json.dumps(value),flush=True)
    with process_lock(OUT/'job.lock'):
        if (OUT/'done.json').exists():
            return
        server=None
        try:
            with socket.socket() as test:
                test.settimeout(2)
                if test.connect_ex(('127.0.0.1',8081))==0:
                    raise RuntimeError('PORT_ALREADY_OWNED')
            weights=BASE/'models/Llama-3-Patronus-Lynx-70B-Instruct-IQ4_XS.gguf'
            if not weights.is_file():
                raise RuntimeError('LYNX_WEIGHTS_MISSING')
            state('LOADING')
            with (BASE/'logs/lynx_witness_server.log').open('a') as log:
                server=subprocess.Popen([str(BASE/'llamacpp-src/build/bin/llama-server'),'-m',str(weights),
                                         '--alias',MODEL,'--host','127.0.0.1','--port','8081','-ngl','999',
                                         '-c','64000','-np','8','--jinja','--no-context-shift','-fa','on'],
                                        stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+300
            while time.monotonic()<deadline:
                if server.poll() is not None:
                    raise RuntimeError('SERVER_EXITED')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=2) as response:
                        if response.status==200:
                            break
                except Exception:
                    time.sleep(2)
            else:
                raise TimeoutError('SERVER_READY_DEADLINE')
            state('RUNNING_VALID46_AND_PAIRED_ACCUSATIONS',pid=server.pid)
            root=ROOT/'outputs/guardian_local_a100/llamacpp'
            qwen=root/'qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/runs'
            distill=root/'qwen3.8-27b-opus-distill-v2@64d56b13ea8d:Q8_0:llamacpp-b11459/runs'
            legacy=root/MODEL/'lynx-native-object-v3/runs.jsonl'
            subprocess.run([sys.executable,'-X','utf8','-m','experiments.guardian_local_a100.lynx_witness',
                            '--model-id',MODEL,'--qwen-root',str(qwen),'--distill-root',str(distill),
                            '--legacy-runs',str(legacy),'--output',str(OUT),'--workers','8','--max-calls','150'],
                           cwd=ROOT,check=True,timeout=1800)
            if not (OUT/'score.json').exists():
                subprocess.run([sys.executable,'-X','utf8','-m','experiments.guardian_local_a100.score_lynx_witness',
                                '--input',str(OUT),'--qwen-root',str(qwen),'--output',str(OUT/'score.json')],
                               cwd=ROOT,check=True,timeout=90)
            state('DONE')
            (OUT/'done.json').write_text(json.dumps(dict(status='DONE',quality='diagnostic only')),encoding='utf-8')
            publish([OUT],'lynx: preserve full valid46 witness repair and paired source controls')
        except Exception as error:
            state('BLOCKED',error=type(error).__name__,detail=str(error)[:250])
            publish([OUT],'lynx: preserve failed witness phase and partial receipts')
            raise
        finally:
            if server is not None and server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


if __name__=='__main__':
    main()
