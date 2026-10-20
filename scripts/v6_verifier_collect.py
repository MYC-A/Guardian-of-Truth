"""Finite off-box status/export collector. Does not start or promote models."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def write(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');tmp.replace(path)


def main():
    p=argparse.ArgumentParser()
    for n in ('ssh','scp','key','out'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--host',required=True);p.add_argument('--port',type=int,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    ssh=[str(a.ssh),'-T','-i',str(a.key),'-o','BatchMode=yes','-o','ConnectTimeout=12','-p',str(a.port),a.host,'python3 -']
    scp=[str(a.scp),'-i',str(a.key),'-o','BatchMode=yes','-o','ConnectTimeout=12','-P',str(a.port)]
    remote_root='/workspace/guardian-lab-20261018/v6-verifier-20261020'
    names=['run-v2/PROGRESS.json','run-v2/FAIL.json','run-v2/TRAINING_CHAIN_DONE.json',
        'run-v2/prepared/DONE.json','run-v2/prepared/SOURCE_AUDIT.json','run-v2/prepared/SELECTION.json',
        'run-v2/training/START.json','run-v2/training/MODEL_READY.json','run-v2/training/TECHNICAL_GATE.json',
        'run-v2/training/PROGRESS.json','run-v2/training/CURRENT_ROW.json','run-v2/training/FAIL.json','run-v2/training/TRAINED.json',
        'run-v2-training-export.INDEX.json','first-checkpoint-export.INDEX.json',
        'evaluation-v2/START.json','evaluation-v2/DONE.json','evaluation-v2/FAIL.json','evaluation-v2/RESULTS.json',
        'evaluation-v2-export.INDEX.json']
    for arm in ('base','old','new'):
        names += ['evaluation-v2/'+arm+'/'+n for n in ('PROGRESS.json','DONE.json','ADAPTER_BINDING.json')]
    write(a.out/'COLLECTOR_STARTED.json',dict(remote_root=remote_root,budget_seconds=14400,interval_seconds=60,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),training_or_promotion_started=False))
    errors=[];downloaded={}
    while time.monotonic()-started<14400:
        # The first committed update is backed up once, without copying mutable files.
        code='''from pathlib import Path
import json,tarfile,hashlib
r=Path(ROOT)
cp=r/'run-v2/training/checkpoint-001'
first=r/'first-checkpoint-export.tar.gz';index=r/'first-checkpoint-export.INDEX.json'
if (cp/'CHECKPOINT.json').exists() and not index.exists():
 with tarfile.open(first,'w:gz',compresslevel=3) as tar:tar.add(cp,arcname='checkpoint-001')
 with first.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
 index.write_text(json.dumps(dict(name=first.name,bytes=first.stat().st_size,sha256=digest)))
print(json.dumps({n:json.loads((r/n).read_bytes()) for n in NAMES if (r/n).exists()}))
'''
        code='ROOT='+repr(remote_root)+'\nNAMES='+repr(names)+'\n'+code
        try:
            response=subprocess.run(ssh,input=code.encode(),capture_output=True,timeout=55)
            if response.returncode:raise RuntimeError('SSH_EXIT:'+str(response.returncode))
            state=json.loads(response.stdout)
            write(a.out/'LIVE_STATE.json',dict(seconds=time.monotonic()-started,receipts=state))
            for name,value in state.items():
                if name.endswith('.INDEX.json'):
                    archive=value['name']
                    if Path(archive).name!=archive or not archive.endswith('.tar.gz') or value['bytes']>300_000_000:
                        raise ValueError('UNSAFE_EXPORT_INDEX')
                    target=a.out/archive
                    if downloaded.get(archive)==value['sha256']:continue
                    partial=target.with_suffix(target.suffix+'.partial')
                    transfer=subprocess.run(scp+[a.host+':'+remote_root+'/'+archive,str(partial)],capture_output=True,timeout=1200)
                    if transfer.returncode:raise RuntimeError('SCP_EXIT:'+str(transfer.returncode))
                    with partial.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
                    if digest!=value['sha256'] or partial.stat().st_size!=value['bytes']:raise ValueError('EXPORT_HASH_OR_SIZE')
                    partial.replace(target);downloaded[archive]=digest
                    write(a.out/(archive+'.INDEX.json'),dict(value,verified_offbox=True))
                    write(a.out/'DOWNLOADED.json',downloaded)
            eval_finished='evaluation-v2-export.INDEX.json' in state
            train_failed='run-v2/FAIL.json' in state or 'run-v2/training/FAIL.json' in state
            if eval_finished or train_failed:
                write(a.out/'COLLECTOR_DONE.json',dict(complete=True,seconds=time.monotonic()-started,
                    evaluation_complete='evaluation-v2/DONE.json' in state,downloaded=downloaded,
                    training_failed=train_failed,quality_passed=(state.get('evaluation-v2/RESULTS.json',{}).get('offline_gate') or {}).get('passed')))
                return
        except Exception as e:
            errors.append(dict(seconds=time.monotonic()-started,error=str(e)));write(a.out/'COLLECTOR_ERRORS.json',errors[-30:])
        time.sleep(60)
    write(a.out/'COLLECTOR_EXPIRED.json',dict(seconds=time.monotonic()-started,downloaded=downloaded))


if __name__=='__main__':main()
