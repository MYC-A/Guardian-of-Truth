"""Finite sequential local-model generation; owns and stops only its own servers."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import time

BASE=Path('/workspace/guardian-lab-20261018')
DATA=BASE/'v4-20261019'


def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=('pilot','expanded'),required=True)
    p.add_argument('--attempt',type=int,default=1);a=p.parse_args()
    out=DATA/('natural-series-'+a.phase+'-v'+str(a.attempt));out.mkdir(exist_ok=False)
    records=[];start=time.time()
    (out/'START.json').write_text(json.dumps(dict(phase=a.phase,started_unix=start,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        per_domain=2 if a.phase=='pilot' else 8,turn_labels_assigned=False),indent=2))
    for model in ('4b','8b'):
        server='guardian-lab-v4-local-'+model
        target=DATA/('natural-'+model+'-'+a.phase+'-v'+str(a.attempt))
        assert not target.exists(),'NO_RESULT_CACHE_OR_RESTART'
        assert subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()=='0','GPU_IN_USE'
        rec=dict(model=model,out=str(target));records.append(rec)
        try:
            subprocess.run(['supervisorctl','start',server],check=True)
            cmd=[str(BASE/'v3-20261019/tau-venv/bin/python'),'-u',str(BASE/'code/scripts/v4_tau_simulate.py'),
                 '--out',str(target),'--config-name','v4-'+model,'--per-domain','2' if a.phase=='pilot' else '8']
            with (out/(model+'.log')).open('w') as log:
                r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=1800 if a.phase=='pilot' else 3600)
            rec['exit_code']=r.returncode
            if r.returncode==0:
                rec['result']=json.loads((target/'DONE.json').read_text())
                rec['complete']=True
            else:rec['complete']=False
        except Exception as exc:
            rec.update(complete=False,error_type=type(exc).__name__,error=str(exc))
        finally:
            subprocess.run(['supervisorctl','stop',server],check=False)
            for _ in range(30):
                if subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()=='0':break
                time.sleep(1)
            if target.exists():
                archive=DATA/(target.name+'.tar.gz')
                with tarfile.open(archive,'w:gz') as tar:tar.add(target,arcname=target.name)
                rec['archive']=dict(name=archive.name,bytes=archive.stat().st_size,
                    sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
            (out/'PROGRESS.json').write_text(json.dumps(records,indent=2)+'\n')
        if not rec.get('complete'):
            (out/'FAIL.json').write_text(json.dumps(dict(complete=False,records=records,seconds=time.time()-start),indent=2)+'\n')
            raise RuntimeError('NATURAL_MODEL_JOB_FAILED:'+model)
    (out/'DONE.json').write_text(json.dumps(dict(complete=True,records=records,seconds=time.time()-start,
        labels_assigned=False),indent=2)+'\n')


if __name__=='__main__':main()
