"""Operator-only CPU runtime export coordinator, executed on the research server."""
from pathlib import Path
import argparse
import json
import re
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-sha', required=True)
args = p.parse_args()
if re.fullmatch('[0-9a-f]{40}', args.source_sha) is None:
    p.error('full source SHA required')
base = Path('/workspace/guardian/vllm_submission_build_20261010')
base.mkdir(exist_ok=False)
code = base / 'code'
subprocess.run(['git', 'clone', '--filter=blob:none', '--sparse', '--branch',
                'build/qwen-vllm-fp8-submission-20261010',
                'https://github.com/MYC-A/Guardian-of-Truth.git', str(code)], check=True, timeout=90)
subprocess.run(['git', '-C', str(code), 'checkout', '--detach', args.source_sha], check=True, timeout=30)
subprocess.run(['git', '-C', str(code), 'sparse-checkout', 'set', 'src', 'scripts', 'submission',
                'docs/qwen_vllm_submission_20261010', 'experiments/guardian_semantic',
                'experiments/guardian_addons'], check=True, timeout=60)
runner = r'''from pathlib import Path
import json,os,subprocess,time,traceback
ROOT=Path(__file__).resolve().parent
CODE=ROOT/'code'
PYTHON='/workspace/guardian/vllm_phase2_20261010/venv/bin/python'
STAGE=ROOT/'stage'
env=dict(os.environ,PYTHONPATH=str(CODE/'src')+':'+str(CODE),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='8',PYTHONNOUSERSITE='1')
for key in ('LD_LIBRARY_PATH','LD_PRELOAD','PYTHONHOME','VIRTUAL_ENV'):env.pop(key,None)
ledger=[]
def phase(name,command,cap):
    started=time.monotonic()
    (ROOT/'ACTIVE_PHASE.json').write_text(json.dumps(dict(phase=name)),encoding='utf-8')
    with (ROOT/(name+'.stdout.log')).open('x') as out,(ROOT/(name+'.stderr.log')).open('x') as err:
        rc=subprocess.run(['/usr/bin/timeout','--signal=TERM','--kill-after=20',str(cap),*command],env=env,cwd=CODE,stdout=out,stderr=err).returncode
    ledger.append(dict(phase=name,seconds=time.monotonic()-started,returncode=rc))
    (ROOT/'ledger.json').write_text(json.dumps(ledger,indent=2),encoding='utf-8')
    if rc:raise RuntimeError('BUILD_PHASE_FAILED:'+name+':'+str(rc))
try:
    phase('prepare',[PYTHON,'scripts/build_vllm_submission.py','prepare','--repo',str(CODE),'--stage',str(STAGE),'--model-dir','/workspace/guardian/vllm_probe_20261010/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a','--asset-manifest','/workspace/guardian/vllm_phase2_20261010/verified_asset_manifest.json'],900)
    phase('cpu_smoke',[PYTHON,'scripts/build_vllm_submission.py','smoke','--stage',str(STAGE)],240)
    probe="""import json,pathlib,subprocess,sys
root=pathlib.Path(sys.argv[1]);result=[]
for binary in (root/'runtime/site-packages/triton/backends/nvidia/bin').glob('ptxas*'):
    if binary.is_file():
        p=subprocess.run([str(binary),'--version'],capture_output=True,text=True,timeout=20)
        result.append(dict(binary=str(binary.relative_to(root)),rc=p.returncode,stdout=p.stdout[-800:],stderr=p.stderr[-800:]))
        if p.returncode:raise RuntimeError('PTXAS_SMOKE_FAILED')
(root.parent/'native_tools.json').write_text(json.dumps(result,indent=2))
"""
    phase('native_tools',[str(STAGE/'runtime/python/run_python.sh'),'-c',probe,str(STAGE)],60)
    phase('empty_input',[PYTHON,'-c','import pandas as p,sys;p.DataFrame(columns=["id","prompt","response"]).to_parquet(sys.argv[1],index=False)',str(ROOT/'empty.parquet')],30)
    phase('public_empty',['python3',str(STAGE/'scripts/predict.py'),'--input',str(ROOT/'empty.parquet'),'--output',str(ROOT/'empty-predictions.parquet'),'--work-dir',str(ROOT/'public_empty')],120)
    phase('runtime_export',[PYTHON,'scripts/build_vllm_submission.py','zip','--runtime-only','--stage',str(STAGE),'--destination',str(ROOT/'guardian-vllm-runtime.zip'),'--report',str(ROOT/'runtime-export.json')],900)
    (ROOT/'DONE.json').write_text(json.dumps(dict(status='RUNTIME_EXPORT_COMPLETE',phases=ledger,gpu_validation='NOT_EXECUTED_BY_THIS_PHASE'),indent=2))
except BaseException:
    (ROOT/'FAILED.txt').write_text(traceback.format_exc(),encoding='utf-8');raise
'''
(base / 'run.py').write_text(runner, encoding='utf-8')
(base / 'STARTED.json').write_text(json.dumps(dict(source_sha=args.source_sha, gpu=False)), encoding='utf-8')
name = 'guardian_vllm_submission_build_20261010'
with (Path('/etc/supervisor/conf.d') / (name + '.conf')).open('x') as stream:
    stream.write(f'''[program:{name}]
command=/usr/bin/timeout --signal=TERM --kill-after=30 2400 /usr/bin/python3 -u {base}/run.py
directory={base}
autostart=false
autorestart=false
startsecs=2
stopasgroup=true
killasgroup=true
stdout_logfile={base}/stdout.log
stderr_logfile={base}/stderr.log
''')
for command in (['supervisorctl', 'reread'], ['supervisorctl', 'update', name], ['supervisorctl', 'start', name]):
    subprocess.run(command, check=True, timeout=15)
print(json.dumps(dict(status='LAUNCHED', program=name, root=str(base))))
