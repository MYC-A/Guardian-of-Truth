"""Independent release inspection of a full open-review ZIP, no GPU inference.

The builder separately verifies every member hash/size/mode. This inspector checks
the selected profile and exact source bytes, runtime preservation, executable ELF,
model/shard manifests and the actual extracted entrypoint with a fake model.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]


def check(ok,reason):
    if not ok:raise ValueError(reason)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--source-runtime',type=Path,required=True)
    p.add_argument('--commit',required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    from scripts.build_judge_submission import CODE,runtime_closure
    receipt=json.loads(a.archive.with_suffix('.verification.json').read_text())
    check(receipt['all_members_verified'] and receipt['pinned_download_manifest_verified'],'BUILD_UNVERIFIED')
    check(receipt['release_commit']==a.commit,'COMMIT')
    result=dict(archive=str(a.archive),code_commit=a.commit,gpu_status='GPU_UNTESTED')
    with zipfile.ZipFile(a.archive) as z,zipfile.ZipFile(a.source_runtime) as source:
        names=z.namelist();manifest=json.loads(z.read('MANIFEST.json'))
        check(len(names)==len(set(names))==receipt['files'],'DUPLICATE_MEMBERS')
        check(all(not n.startswith('/') and '\\' not in n and ':' not in n and '..' not in Path(n).parts for n in names),'UNSAFE_PATH')
        check(set(manifest['files'])==set(names)-{'MANIFEST.json'},'MANIFEST_FILE_SET')
        check(manifest['judge_build']['source_revision']==a.commit,'SOURCE_REVISION')
        cfg=json.loads(z.read('JUDGE_CONFIG.json'))
        check(cfg==json.loads((ROOT/'submission/JUDGE_OPEN_REVIEW40.json').read_text()),'WRONG_CONFIG')
        check(cfg['review_ranking']=='max_exact' and cfg['positive_rate']==.4 and cfg['review_mode']=='open','PROFILE')
        check(cfg['review_content']=='answer_audit' and cfg['review_schedule']=='per_chunk','CONTENT_SCHEDULE')
        check(cfg['require_exact_scores'] is True and cfg['questions']==['overall'],'SCORING')
        old=json.loads(source.read('MANIFEST.json'))
        runtime={n:r for n,r in manifest['files'].items() if n.startswith('runtime/')}
        check(runtime=={n:r for n,r in old['files'].items() if n.startswith('runtime/')},'RUNTIME_CHANGED')
        check(manifest['judge_build']['source_zip_sha256']=='f54329f9c8fd7779fe31a66fdeca76f520de699c2969421355d29d45182c56c7','SOURCE_RUNTIME_PIN')
        for name,local in CODE.items():
            if name in ('README.md','JUDGE_CONFIG.json'):continue
            check(z.read(name)==(ROOT/local).read_bytes().replace(b'\r\n',b'\n'),'CODE:'+name)
        check(z.read('README.md')==(ROOT/'docs/judge_20261013/README_OPEN_REVIEW40.md').read_bytes().replace(b'\r\n',b'\n'),'README')
        closure=runtime_closure(ROOT)
        check(all(n in names for n in closure),'IMPORT_CLOSURE')
        check('src/guardian_truth/judge/answer_review.py' in closure,'AUDIT_MODULE_MISSING')
        check(not any('/research/' in n or '/experiments/' in n for n in closure),'RESEARCH_DEPENDENCY')
        for name in closure+['scripts/predict.py','scripts/judge_stage.py','scripts/judge_submission.py']:
            ast.parse(z.read(name),filename=name)
        model=json.loads(z.read('JUDGE_MANIFEST.json'))
        check((model['repository'],model['revision'])==('cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit',
            '00fcea2d3bcf5389b518d4fc082e5590e0ba4844'),'MODEL_IDENTITY')
        for row in model['files']:
            m=manifest['files']['model/judge/'+row['path']]
            check((row['size'],row['sha256'])==(m['bytes'],m['sha256']),'MODEL_MANIFEST')
        index=json.loads(z.read('model/judge/model.safetensors.index.json'))['weight_map']
        check(len(index)==95427 and len(set(index.values()))==6,'SHARD_INDEX')
        for name in ('runtime/python/bin/python3.12.real','runtime/lib/ld-linux-x86-64.so.2'):
            with z.open(name) as stream:header=stream.read(20)
            check(header[:4]==b'\x7fELF' and header[4]==2 and int.from_bytes(header[18:20],'little')==62,'ELF')
            check(stat.S_IMODE(z.getinfo(name).external_attr>>16)&0o111,'EXECUTABLE')
        wrapper=z.read('runtime/python/run_python.sh').decode()
        check(all(v in wrapper for v in ('HF_HUB_OFFLINE=1','TRANSFORMERS_OFFLINE=1',
            '--argv0 "$ROOT/runtime/python/bin/python3.12"','--library-path')),'OFFLINE_LOADER')
        with tempfile.TemporaryDirectory(prefix='open40-inspection-',dir=a.out.parent) as folder:
            extracted=Path(folder)
            for name in set(CODE)|set(closure):
                path=extracted/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(z.read(name))
            env=dict(os.environ,PYTHONPATH=os.pathsep.join([str(extracted/'src'),str(extracted)]),
                     PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
            run=subprocess.run([sys.executable,str(ROOT/'scripts/check_open_review_archive_cpu.py'),str(extracted),str(ROOT)],
                cwd=extracted,env=env,capture_output=True,text=True,timeout=120)
            check(run.returncode==0,'EXTRACTED_PIPELINE:'+run.stderr[-5000:])
            cpu=json.loads(run.stdout.strip().split('\n')[-1])
        result.update(files=len(names),runtime_files=len(runtime),runtime_unchanged=True,config=cfg,
            closure_files=len(closure),model_files=len(model['files']),tensors=len(index),cpu_pipeline=cpu)
    h=hashlib.sha256()
    with a.archive.open('rb') as f:
        for block in iter(lambda:f.read(16<<20),b''):h.update(block)
    check(h.hexdigest()==receipt['sha256'],'ARCHIVE_SHA256')
    check(a.archive.stat().st_size==receipt['bytes']<40_000_000_000,'SIZE')
    result.update(sha256=h.hexdigest(),bytes=a.archive.stat().st_size,all_checks_passed=True)
    a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
