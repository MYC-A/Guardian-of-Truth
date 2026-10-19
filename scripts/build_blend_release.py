"""Pinned operator release driver. Wait for verified assets/GPU receipt, build and inspect."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.build_judge_submission import build,CODE
from guardian_truth.judge.ensemble import PRIMARY_ID,PRIMARY_REVISION


def main():
    p=argparse.ArgumentParser()
    for key in ('source','primary','secondary','adapter','gpu_receipt','out','state'):
        p.add_argument('--'+key.replace('_','-'),type=Path,required=True)
    p.add_argument('--commit',required=True);p.add_argument('--source-sha256',required=True)
    p.add_argument('--wait-seconds',type=float,default=10800);a=p.parse_args();start=time.monotonic()
    def status(phase,**extra):
        value=dict(phase=phase,seconds=time.monotonic()-start,output=str(a.out),source_commit=a.commit,**extra)
        temp=a.state.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');temp.replace(a.state)
        print(json.dumps(value),flush=True)
    def pinned_code():
        for name,path in CODE.items():
            if name=='README.md':path='docs/judge_20261013/README_BLEND40.md'
            if name=='JUDGE_CONFIG.json':path='submission/JUDGE_BLEND40.json'
            expected=subprocess.check_output(['git','show',a.commit+':'+path],cwd=ROOT).replace(b'\r\n',b'\n')
            if (ROOT/path).read_bytes().replace(b'\r\n',b'\n')!=expected:raise ValueError('RELEASE_SOURCE_DRIFT:'+path)
    try:
        pinned_code();status('WAIT_VERIFIED_ASSETS_AND_GPU')
        while True:
            try:
                weights=json.loads((a.secondary/'VERIFIED.json').read_bytes());gpu=json.loads(a.gpu_receipt.read_bytes())
                if weights.get('verified') and gpu.get('complete'):
                    assert gpu['pipeline']['ranking']=='rank_50_50' and gpu['pipeline']['secondary_exact_rows']==46
                    break
            except (OSError,ValueError):pass
            if time.monotonic()-start>a.wait_seconds:raise TimeoutError('RELEASE_ASSET_WAIT_LIMIT')
            time.sleep(5)
        pinned_code();status('BUILDING')
        result=build(a.source,a.source_sha256,a.primary,PRIMARY_ID,PRIMARY_REVISION,a.out,
            judge_config=ROOT/'submission/JUDGE_BLEND40.json',source_revision=a.commit,
            secondary_model_dir=a.secondary,adapter_dir=a.adapter)
        result.update(release_source_commit=a.commit,gpu_scope='A6000 host-venv valid46 only',
            gpu_receipt_sha256=hashlib.sha256(a.gpu_receipt.read_bytes()).hexdigest(),
            gpu_valid46_seconds=gpu['seconds'],gpu_private_test_validated=False,experimental=True)
        a.out.with_suffix('.verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        status('INDEPENDENT_ARCHIVE_INSPECTION')
        inspection=a.out.with_suffix('.inspection.json')
        subprocess.run([sys.executable,str(ROOT/'scripts/verify_blend_archive.py'),'--archive',str(a.out),
            '--source',str(a.source),'--commit',a.commit,'--out',str(inspection)],cwd=ROOT,check=True)
        status('READY',bytes=result['bytes'],sha256=result['sha256'],inspection=str(inspection))
    except Exception as error:
        status('FAILED',error_type=type(error).__name__,error=str(error));raise


if __name__=='__main__':main()
