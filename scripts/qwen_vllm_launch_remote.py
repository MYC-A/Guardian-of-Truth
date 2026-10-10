from pathlib import Path
import json
import subprocess

import argparse
import re

parser = argparse.ArgumentParser(description='Launch pinned isolated vLLM B2 phase on the research server')
parser.add_argument('--source-sha', required=True)
args = parser.parse_args()
PIN = args.source_sha
if re.fullmatch(r'[0-9a-f]{40}', PIN) is None:
    parser.error('source SHA must be a full lowercase Git SHA')
base=Path('/workspace/guardian/vllm_phase_20261010')
base.mkdir(exist_ok=False)
code=base/'code'
subprocess.run(['git','clone','--filter=blob:none','--sparse','--depth','1','--single-branch',
    '--branch','perf/qwen-inference-20261010','https://github.com/MYC-A/Guardian-of-Truth.git',str(code)],
    check=True,timeout=40)
head=subprocess.check_output(['git','-C',str(code),'rev-parse','HEAD'],text=True).strip()
assert head==PIN,(head,PIN)
subprocess.run(['git','-C',str(code),'sparse-checkout','set','src','scripts','tests',
    'experiments/guardian_semantic','experiments/guardian_addons','experiments/guardian_local_a100'],
    check=True,timeout=40)
runner=r'''from pathlib import Path
import json, os, subprocess, time, traceback
ROOT=Path(__file__).resolve().parent
CODE=ROOT/'code'
SETUP=Path('/workspace/guardian/vllm_probe_20261010')
REV='017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
PYTHON=str(SETUP/'venv/bin/python')
env=dict(os.environ,PYTHONPATH=str(CODE/'src')+':'+str(CODE),PYTHONUTF8='1',
    PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='8',PYTHONNOUSERSITE='1',
    UV_HTTP_TIMEOUT='120',UV_CONCURRENT_DOWNLOADS='8')
for key in ('LD_LIBRARY_PATH','LD_PRELOAD','PYTHONHOME'):
    env.pop(key,None)
ledger=[]
def phase(name,command,timeout):
    started=time.monotonic()
    (ROOT/'ACTIVE_PHASE.json').write_text(json.dumps(dict(phase=name)),encoding='utf-8')
    with (ROOT/(name+'.stdout.log')).open('x',encoding='utf-8') as out, \
         (ROOT/(name+'.stderr.log')).open('x',encoding='utf-8') as err:
        rc=subprocess.run(['/usr/bin/timeout','--signal=TERM','--kill-after=20',str(timeout),*command],
            cwd=CODE,env=env,stdout=out,stderr=err).returncode
    ledger.append(dict(phase=name,returncode=rc,seconds=time.monotonic()-started))
    (ROOT/'phase_ledger.json').write_text(json.dumps(ledger,indent=2),encoding='utf-8')
    if rc:
        raise RuntimeError('PHASE_FAILED:'+name+':'+str(rc))
try:
    # Dependency polling happens inside this bounded script, not model/tool turns.
    limit=time.monotonic()+1800
    while not (SETUP/'SETUP_DONE.json').exists():
        if (SETUP/'SETUP_FAILED.txt').exists():
            raise RuntimeError('UPSTREAM_SETUP_FAILED')
        if time.monotonic()>limit:
            raise TimeoutError('SETUP_DEPENDENCY_DEADLINE')
        time.sleep(30)
    phase('transformers_compatibility',['uv','pip','install','--python',PYTHON,'--no-cache',
        'transformers==5.8.0'],300)
    # Pin and preserve the small processor amendment separately from original download phase.
    amendment=SETUP/'AMENDED_DOWNLOAD_PROTOCOL.json'
    patch=r"""import json, pathlib
from huggingface_hub import snapshot_download
root=pathlib.Path('/workspace/guardian/vllm_probe_20261010')
p=json.loads((root/'DOWNLOAD_PROTOCOL.json').read_text())
snapshot_download(p['repo'],revision=p['revision'],local_dir=root/'model',
                  allow_patterns=['video_preprocessor_config.json'],max_workers=1)
p['files']=sorted(set(p['files'])|{'video_preprocessor_config.json'})
p['amendment']='Add pinned video processor config required for multimodal processor initialization'
(root/'AMENDED_DOWNLOAD_PROTOCOL.json').write_text(json.dumps(p,indent=2),encoding='utf-8')
"""
    phase('processor_asset',[str(SETUP/'download_venv/bin/python'),'-c',patch],180)
    phase('asset_verification',[str(SETUP/'download_venv/bin/python'),
        str(CODE/'scripts/qwen_vllm_verify_assets.py'),'--model-dir',str(SETUP/'model'),
        '--download-protocol',str(amendment),'--output',str(SETUP/'verified_asset_manifest.json')],300)
    target=SETUP/REV
    assert target.parent.resolve()==SETUP.resolve() and not target.exists()
    (SETUP/'model').rename(target)
    cpu=r"""import json, pathlib, transformers
from transformers import AutoConfig, AutoTokenizer, AutoProcessor
root=pathlib.Path('/workspace/guardian/vllm_probe_20261010')
model=root/'017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
config=AutoConfig.from_pretrained(model,local_files_only=True)
tokenizer=AutoTokenizer.from_pretrained(model,local_files_only=True)
processor=AutoProcessor.from_pretrained(model,local_files_only=True)
messages=[{'role':'system','content':'Be concise.'},{'role':'user','content':'Say ok.'}]
ids=tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False)
text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
(root/'CPU_SMOKE.json').write_text(json.dumps(dict(transformers=transformers.__version__,
    model_type=config.model_type,tokenizer=type(tokenizer).__name__,processor=type(processor).__name__,
    rendered_prompt=text,rendered_tokens=ids,status='COMPLETE'),indent=2),encoding='utf-8')
"""
    phase('cpu_config_tokenizer',[PYTHON,'-c',cpu],180)
    frozen=subprocess.check_output(['uv','pip','freeze','--python',PYTHON],env=env,text=True)
    (ROOT/'requirements-frozen.txt').write_text(frozen,encoding='utf-8')
    # All native arms must have released the GPU before another engine starts.
    native=Path('/workspace/guardian/engine_screen_20261010_ea8d8c8b')
    limit=time.monotonic()+1800
    while not ((native/'DONE.json').exists() or (native/'FAILED.txt').exists()):
        if time.monotonic()>limit:
            raise TimeoutError('NATIVE_GPU_PHASE_DEADLINE')
        time.sleep(30)
    active=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,process_name',
        '--format=csv,noheader'],text=True).strip()
    if active:
        raise RuntimeError('GPU_OCCUPIED_BY_OTHER_PROCESS')
    common=[PYTHON,'-u',str(CODE/'scripts/qwen_vllm_adapter.py'),'--python',PYTHON,
        '--model-dir',str(target),'--asset-manifest',str(SETUP/'verified_asset_manifest.json'),
        '--input',str(CODE/'valid.parquet'),'--slots','8','--context','32768','--enforce-eager']
    phase('gpu_smoke',[*common,'--output',str(ROOT/'smoke'),'--limit','2','--workers','1',
        '--timeout','180','--duration','600','--max-calls','24'],630)
    smoke=json.loads((ROOT/'smoke/DONE.json').read_text())
    if smoke['rows']!=2 or smoke['default_zero_fallbacks'] or smoke['technical_calls']:
        raise RuntimeError('GPU_SMOKE_HAS_TECHNICAL_GAPS')
    phase('full_valid46',[*common,'--output',str(ROOT/'valid46'),'--limit','46','--workers','8',
        '--timeout','600','--duration','1800','--max-calls','400'],1830)
    # Scoring is a separate operation after inference, with original labels.
    scoring=r"""import json, pathlib, pandas as pd
root=pathlib.Path('/workspace/guardian/vllm_phase_20261010')
truth=pd.read_parquet(root/'code/valid.parquet').set_index('id')['label']
pred=pd.read_parquet(root/'valid46/predictions.parquet').set_index('id')['label']
assert len(truth)==len(pred)==46 and truth.index.is_unique and pred.index.is_unique and set(truth.index)==set(pred.index)
counts={k:0 for k in ('TP','FP','FN','TN')}
for i,label in truth.items():
    value=int(pred[i]); assert value in (0,1)
    counts[('TN','FP','FN','TP')[2*int(label)+value]]+=1
counts['F1']=2*counts['TP']/(2*counts['TP']+counts['FP']+counts['FN'])
(root/'score_valid46.json').write_text(json.dumps(dict(metrics=counts,
    scope='Full B2 on new vLLM+FP8 profile, one development repetition, no independent engine-only attribution'),indent=2),encoding='utf-8')
"""
    phase('score_valid46',[PYTHON,'-c',scoring],60)
    (ROOT/'DONE.json').write_text(json.dumps(dict(status='COMPLETE',phases=ledger)),encoding='utf-8')
except BaseException:
    (ROOT/'FAILED.txt').write_text(traceback.format_exc(),encoding='utf-8')
    raise
'''
(base/'run.py').write_text(runner,encoding='utf-8')
(base/'STARTED.json').write_text(json.dumps(dict(source_sha=head,scope='Separate vLLM+officialFP8 full B2 candidate',
    waits_for_setup=True,smoke_then_full46=True,outer_cap_seconds=6000,max_smoke_calls=24,max_full_calls=400)),encoding='utf-8')
name='guardian_vllm_phase_20261010'
with (Path('/etc/supervisor/conf.d')/(name+'.conf')).open('x',encoding='utf-8') as stream:
    stream.write(f'''[program:{name}]
command=/usr/bin/timeout --signal=TERM --kill-after=30 6000 /usr/bin/python3 -u {base}/run.py
directory={base}
autostart=false
autorestart=false
startsecs=2
stopasgroup=true
killasgroup=true
stdout_logfile={base}/stdout.log
stderr_logfile={base}/stderr.log
''')
for args in (['supervisorctl','reread'],['supervisorctl','update',name],['supervisorctl','start',name]):
    subprocess.run(args,check=True,timeout=15)
print(json.dumps(dict(status='LAUNCHED',program=name,source_sha=head,root=str(base))))
