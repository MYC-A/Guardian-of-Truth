"""Finite off-box collection of immutable checkpoints, frozen data and results."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

def write(p,v):
    temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8');temp.replace(p)

def run(a):
    a.out.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    ssh=['C:/Program Files/Git/usr/bin/ssh.exe','-T','-i','C:/Users/Igor/.ssh/guardian_vast_me',
        '-o','BatchMode=yes','-o','ConnectTimeout=12','-p','18293','root@209.137.198.14','python3 -']
    scp=['C:/Program Files/Git/usr/bin/scp.exe','-i','C:/Users/Igor/.ssh/guardian_vast_me',
        '-o','BatchMode=yes','-o','ConnectTimeout=12','-P','18293']
    names=['prepared-v1/PREPARED.json','prepared-v1/EVAL_PROTOCOL.json','prepared-v1/REPLAY_PROTOCOL.json','mining-v1/PROGRESS.json','mining-v1/DONE.json',
        'training-v1/DONE.json','training-v1/FAIL.json','training-v1/TECHNICAL_FALLBACK.json','training-v1-export.INDEX.json',
        'evaluation-v1/DONE.json','evaluation-v1/FAIL.json','evaluation-v1/RESULTS.json','evaluation-v1/PAIR_RESULTS.json',
        'evaluation-v1-export.INDEX.json','evaluation-v1-pair-export.INDEX.json',
        'data-export.INDEX.json','first-checkpoint-export.INDEX.json']
    names+=['final-recovery-export.INDEX.json']
    for profile in ('layers16','layers8'):
        names+=['training-v1/'+profile+'/'+n for n in ('START.json','TECHNICAL_GATE.json','MODEL_READY.json','RESUME_PROOF.json','PROGRESS.json','CURRENT_ROW.json','TRAINED.json','FAIL.json')]
    for arm in ('base','old','new'):
        names+=['evaluation-v1/'+arm+'/'+n for n in ('PROGRESS.json','DONE.json','ADAPTER_BINDING.json')]
    names=[n.replace('training-v1',a.training_folder).replace('evaluation-v1',a.evaluation_folder) for n in names]
    names+=['training-v1/DONE.json','training-v1-export.INDEX.json','evaluation-v1/SUPERSEDED_BEFORE_QUALITY.json']
    remote_root=a.remote_root
    write(a.out/'COLLECTOR_START.json',dict(remote_root=remote_root,interval_seconds=60,expires_unix=a.expires,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    downloaded={};errors=[]
    previous=a.out/'DOWNLOADED.json'
    if previous.exists():
        for name,digest in json.loads(previous.read_bytes()).items():
            path=a.out/name
            if path.exists():
                with path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
                if actual==digest:downloaded[name]=digest
    while time.time()<a.expires:
        code='ROOT='+repr(remote_root)+'\nNAMES='+repr(names)+'\nTRAINING='+repr(a.training_folder)+'\n'+'''
from pathlib import Path
import json,tarfile,hashlib
r=Path(ROOT)
def archive(name,paths):
 index=r/(name+'.INDEX.json');target=r/(name+'.tar.gz')
 if index.exists():return
 with tarfile.open(target,'w:gz',compresslevel=3) as tar:
  for p in paths:tar.add(p,arcname=str(p.relative_to(r)))
 with target.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 temp=index.with_suffix('.tmp');temp.write_text(json.dumps(dict(name=target.name,bytes=target.stat().st_size,sha256=digest)));temp.replace(index)
if (r/'prepared-v1/PREPARED.json').exists() and (r/'mining-v1/DONE.json').exists() and (r/'prepared-v1/EVAL_PROTOCOL.json').exists():
 archive('data-export',[r/'prepared-v1',r/'mining-v1'])
for profile in ('layers16','layers8'):
 cp=r/TRAINING/profile/'checkpoint-001'
 if (cp/'CHECKPOINT.json').exists():
  archive('first-checkpoint-export',[cp/'adapter',cp/'CHECKPOINT.json'])
if (r/TRAINING/'DONE.json').exists():
 destination=Path(json.loads((r/TRAINING/'DONE.json').read_bytes())['training_path'])
 if destination.parent!=r/TRAINING:raise ValueError('UNSAFE_RECOVERY_PATH')
 archive('final-recovery-export',[destination/'final',destination/'TRAINED.json',destination/'ORDER.json'])
print(json.dumps({n:json.loads((r/n).read_bytes()) for n in NAMES if (r/n).exists()}))
'''
        try:
            proc=subprocess.run(ssh,input=code.encode(),capture_output=True,timeout=55)
            if proc.returncode:raise RuntimeError('SSH_EXIT:'+str(proc.returncode))
            state=json.loads(proc.stdout);write(a.out/'LIVE_STATE.json',dict(seconds=time.monotonic()-started,receipts=state))
            for name,value in state.items():
                if not name.endswith('.INDEX.json'):continue
                archive=value['name']
                if Path(archive).name!=archive or not archive.endswith('.tar.gz') or value['bytes']>600_000_000:raise ValueError('UNSAFE_EXPORT')
                if downloaded.get(archive)==value['sha256']:continue
                target=a.out/archive;partial=target.with_suffix('.partial')
                transfer=subprocess.run(scp+['root@209.137.198.14:'+remote_root+'/'+archive,str(partial)],capture_output=True,timeout=900)
                if transfer.returncode:raise RuntimeError('SCP_EXIT:'+str(transfer.returncode))
                with partial.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
                if digest!=value['sha256'] or partial.stat().st_size!=value['bytes']:raise ValueError('OFFBOX_HASH_OR_SIZE')
                partial.replace(target);downloaded[archive]=digest
                write(a.out/(archive+'.INDEX.json'),dict(value,verified_offbox=True));write(a.out/'DOWNLOADED.json',downloaded)
            if a.evaluation_folder+'-export.INDEX.json' in state or (a.training_folder+'/FAIL.json' in state and a.training_folder+'-export.INDEX.json' in state):
                write(a.out/'COLLECTOR_DONE.json',dict(seconds=time.monotonic()-started,downloaded=downloaded,
                    evaluation_complete=a.evaluation_folder+'/DONE.json' in state,training_failed=a.training_folder+'/FAIL.json' in state));return
        except Exception as e:
            errors.append(dict(seconds=time.monotonic()-started,error=str(e)));write(a.out/'ERRORS.json',errors[-40:])
        time.sleep(60)
    write(a.out/'COLLECTOR_EXPIRED.json',dict(downloaded=downloaded,seconds=time.monotonic()-started))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--expires',type=float,required=True)
    p.add_argument('--training-folder',default='training-v1');p.add_argument('--evaluation-folder',default='evaluation-v1')
    p.add_argument('--remote-root',default='/workspace/guardian-lab-20261018/v7-workflow-20261020')
    run(p.parse_args())
