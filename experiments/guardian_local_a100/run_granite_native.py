"""Finite supervised Granite reproduction, offline inference and publication."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from experiments.guardian_local_a100 import continue_circle as publication

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/guardian_granite_qwen_20261007'
BRANCH='research/guardian-granite-qwen-20261007'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src')+':'+str(ROOT),PYTHONDONTWRITEBYTECODE='1',
             GUARDIAN_DATA_ROOT='/workspace/guardian/data_root_403d811e',GIT_TERMINAL_PROMPT='0',
             HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    publication.ROOT,publication.BRANCH=ROOT,BRANCH
    def state(status,**extra):
        value=dict(status=status,utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**extra)
        (OUT/'state.tmp').write_text(json.dumps(value),encoding='utf-8')
        (OUT/'state.tmp').replace(OUT/'state.json')
        print(json.dumps(value),flush=True)
    try:
        state('RUNNING_NATIVE_VALID46')
        subprocess.run([sys.executable,'-X','utf8','-m','experiments.guardian_local_a100.granite_native',
                        '--model-path','/workspace/guardian/models/granite-guardian-3.3-8b-b3421eda',
                        '--output',str(OUT)],cwd=ROOT,env=env,check=True,timeout=1200)
        score=json.loads((OUT/'score.json').read_text(encoding='utf-8'))
        state('DONE' if score['granite_new']['usable_rows']==46 else 'INCOMPLETE',actual_calls=score['actual_calls'])
        setup=Path('/workspace/guardian/models/granite_download_setup.json')
        if setup.exists() and not (OUT/'download_setup.json').exists():
            (OUT/'download_setup.json').write_bytes(setup.read_bytes())
        publication.publish([OUT],'granite: preserve native valid46 reproduction and Qwen complementarity')
    except Exception as exc:
        state('BLOCKED',error=type(exc).__name__,detail=str(exc)[:200])
        publication.publish([OUT],'granite: preserve bounded failed phase and technical receipts')
        raise


if __name__=='__main__':main()
