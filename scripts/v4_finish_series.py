"""Finite post-training reference/analysis/archive chain with explicit failures."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tarfile
import time

LAB=Path('/workspace/guardian-lab-20261018');DATA=LAB/'v4-20261019';SCRIPTS=LAB/'code/scripts'


def write(path,value):
    p=path.with_suffix(path.suffix+'.tmp');p.write_text(json.dumps(value,indent=2)+'\n');p.replace(path)


def wait_gpu():
    for _ in range(120):
        used=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()
        if used=='0':return
        time.sleep(1)
    raise RuntimeError('GPU_NOT_RELEASED_BY_OWN_PREVIOUS_PHASE')


def main():
    out=DATA/'finish-v1';out.mkdir(exist_ok=False);start=time.time();records=[]
    write(out/'START.json',dict(started_unix=start,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        steps=['wait_for_training_and_paired_evaluation','new_frozen_R0_reference','paired_grouped_analysis','archive'],
        human_reviewed=False,production_promotion=False))
    def run(name,cmd,timeout):
        rec=dict(phase=name,started_unix=time.time());records.append(rec);write(out/'PROGRESS.json',records)
        with (out/(name+'.log')).open('w',buffering=1) as log:
            result=subprocess.run(cmd,cwd=LAB/'code',stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        rec.update(exit_code=result.returncode,seconds=time.time()-rec['started_unix']);write(out/'PROGRESS.json',records)
        assert result.returncode==0,('PHASE_FAILED',name,result.returncode)
    try:
        while not (DATA/'train-v1/DONE.json').exists():
            state=subprocess.check_output(['supervisorctl','status','guardian-lab-v4-train-v1'],text=True)
            if any(s in state for s in ('EXITED','FATAL','STOPPED')):raise RuntimeError('TRAINING_EXITED_WITHOUT_DONE:'+state.strip())
            if time.time()-start>10000:raise TimeoutError('TRAINING_CHAIN_WAIT_LIMIT')
            time.sleep(20)
        done=json.loads((DATA/'train-v1/DONE.json').read_bytes());assert done['complete']
        scores=[json.loads(l) for l in (DATA/'train-v1/scores.jsonl').read_bytes().splitlines()]
        expected=2*(152+336+917)
        assert len(scores)==expected and len({(r['partition'],r['arm'],r['id']) for r in scores})==expected
        assert all(r['exact'] and r.get('score') is not None and math.isfinite(r['score']) for r in scores),'INCOMPLETE_SCORE_COVERAGE'
        wait_gpu()
        run('reference',[sys.executable,str(SCRIPTS/'v4_reference.py'),'--frozen',str(DATA/'frozen-v2'),'--out',str(DATA/'reference-v1')],5700)
        wait_gpu()
        run('analysis',[sys.executable,str(SCRIPTS/'v4_analyze.py'),'--run',str(DATA/'train-v1'),'--frozen',str(DATA/'frozen-v2'),
            '--protected',str(LAB/'data/guardian-judge-eval-data-v1'),'--saved',str(LAB/'runs'),
            '--combined',str(DATA/'external-combined-v1'),'--old_run',str(LAB/'v3-20261019/hours-l1-v1'),
            '--reference',str(DATA/'reference-v1'),'--out',str(DATA/'analysis-v1')],3600)
        write(out/'QUALITY_DONE.json',dict(complete=True,records=records,seconds=time.time()-start,
            epoch_complete=done['epoch_complete'],private_improvement_measured=False,acceptance=False))
    except Exception as e:
        write(out/'FAIL.json',dict(complete=False,error_type=type(e).__name__,error=str(e),records=records,seconds=time.time()-start));raise
    finally:
        # Preserve complete artifacts even if a later phase failed; never turn
        # a partial archive into an ACCEPT claim or retry a failed quality run.
        archive=DATA/'completed-v1.tar.gz'
        with tarfile.open(archive,'w:gz',compresslevel=3) as tar:
            for name in ['frozen-v2','technical-input-v2','technical-pilot-v1','train-v1','source-audit-v1',
                         'external-combined-v1','reference-v1','analysis-v1','finish-v1','SOURCE_ADJUDICATION.json','TRAIN_START_AUTHORIZATION.json']:
                p=DATA/name
                if p.exists():tar.add(p,arcname=name)
        digest=hashlib.sha256()
        with archive.open('rb') as stream:
            for chunk in iter(lambda:stream.read(8*1024*1024),b''):digest.update(chunk)
        write(DATA/'completed-v1.INDEX.json',dict(name=archive.name,bytes=archive.stat().st_size,sha256=digest.hexdigest(),
            quality_complete=(out/'QUALITY_DONE.json').exists(),failure_recorded=(out/'FAIL.json').exists()))
    write(out/'DONE.json',dict(complete=True,seconds=time.time()-start,quality_complete=True,archive='completed-v1.INDEX.json'))


if __name__=='__main__':main()
