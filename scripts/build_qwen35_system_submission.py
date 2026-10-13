"""Finalize a verified model stage with original B2 and small host-compat overlay."""
import argparse
from email import message_from_bytes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import zipfile
import sys

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from packaging.requirements import Requirement
from scripts.assemble_vllm_submission import json_bytes,zip_entries
from scripts.build_b2_rowfix_submission import SOURCE_SHA256,sha256_file,validate_members
from scripts.build_platform_startup_probe import file_info

def normalized(name):return re.sub('[-_.]+','-',name).lower()

def compatibility_members(source):
    """Exact dependency closure, excluding platform Torch/NumPy/CUDA stack."""
    distributions={}
    names=set(source.namelist())
    prefix='runtime/site-packages/'
    for name in source.namelist():
        if (name.startswith(prefix) and name.endswith('.dist-info/METADATA')
                and name.removeprefix(prefix).count('/')==1):
            metadata=message_from_bytes(source.read(name))
            distributions[normalized(metadata['Name'])]=(name,metadata)
    roots=['transformers','huggingface-hub','tokenizers','safetensors','regex','typer','pydantic','jsonschema']
    skip={'torch','numpy','vllm','pip','setuptools','torchvision','torchaudio'}
    selected=set();todo=list(roots)
    context={'python_version':'3.12','python_full_version':'3.12.12','platform_system':'Linux',
        'sys_platform':'linux','os_name':'posix','platform_machine':'x86_64','extra':''}
    while todo:
        package=normalized(todo.pop())
        if package in selected or package in skip:continue
        if package not in distributions:raise ValueError('MISSING_COMPAT_DISTRIBUTION:'+package)
        selected.add(package);_,metadata=distributions[package]
        for raw in metadata.get_all('Requires-Dist',[]):
            requirement=Requirement(raw)
            if requirement.marker and not requirement.marker.evaluate(context):continue
            dependency=normalized(requirement.name)
            if dependency not in skip:
                if dependency not in distributions:raise ValueError('MISSING_COMPAT_DEPENDENCY:'+dependency)
                version=distributions[dependency][1]['Version']
                if requirement.specifier and version not in requirement.specifier:raise ValueError('COMPAT_VERSION_MISMATCH:'+dependency)
                todo.append(dependency)
    members=set();versions={}
    for package in selected:
        name,metadata=distributions[package];record=name.rsplit('/',1)[0]+'/RECORD'
        import csv,io,posixpath
        for row in csv.reader(io.StringIO(source.read(record).decode())):
            relative=row[0]
            if relative.startswith('../'):continue # CLI entrypoints are not imported.
            member=prefix+posixpath.normpath(relative)
            if member not in names:
                if Path(member).name in ('INSTALLER','REQUESTED','direct_url.json'):
                    continue # Installation bookkeeping was excluded from the frozen runtime.
                if member.endswith('.pyc') or '/__pycache__/' in member:continue
                raise ValueError('COMPAT_RECORD_MISSING:'+member)
            if member.endswith(('.pyc',)) or '/__pycache__/' in member:continue
            members.add(member)
        versions[package]=metadata['Version']
    return members,versions

def finalize(stage,output,source_zip,*,repo_root=None,expected_source_sha=SOURCE_SHA256):
    stage,output,source_zip=map(lambda p:Path(p).resolve(),(stage,output,source_zip))
    repo=Path(repo_root or Path(__file__).resolve().parents[1])
    receipt=stage.with_name(stage.name+'.weights.json')
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    state=json.loads(receipt.read_text())
    if not state.get('all_model_files_verified'):raise ValueError('WEIGHTS_STAGE_NOT_COMPLETE')
    if (state['repository'],state['revision']) != ('Qwen/Qwen3.5-35B-A3B-FP8','9d1823d2dee688a6b25e77009dc727688c44936e'):
        raise ValueError('MODEL_IDENTITY_MISMATCH')
    print('VERIFY_SOURCE_SHA256',flush=True)
    _,actual=sha256_file(source_zip,'verify_source_progress')
    if actual!=expected_source_sha:raise ValueError('SOURCE_ZIP_SHA256_MISMATCH')
    expected=dict(state['files'])
    with zipfile.ZipFile(stage) as weights:
        if set(weights.namelist())!=set(expected):raise ValueError('WEIGHT_STAGE_FILE_SET_MISMATCH')
        config=json.loads(weights.read('model/'+state['revision']+'/config.json'))
        index=json.loads(weights.read('model/'+state['revision']+'/model.safetensors.index.json'))
        shards={Path(n).name for n in expected if n.endswith('.safetensors')}
        if set(index['weight_map'].values())!=shards:raise ValueError('SHARD_INDEX_MISMATCH')
        if config.get('model_type')!='qwen3_5_moe' or config.get('quantization_config',{}).get('quant_method')!='fp8':raise ValueError('MODEL_ARCHITECTURE_MISMATCH')
    additions={}
    with zipfile.ZipFile(source_zip) as source:
        manifest=json.loads(source.read('MANIFEST.json'))
        entries=zip_entries(source)
        overlay,versions=compatibility_members(source)
        for name in overlay:
            data=source.read(name);record=manifest['files'][name]
            if hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('SOURCE_COMPAT_HASH_MISMATCH')
            additions['compat/site-packages/'+name.removeprefix('runtime/site-packages/')]=(data,record['mode'])
        for name in entries:
            if name.startswith(('src/','experiments/')) and not name.endswith(('.pyc','.parquet','.jsonl','.log')):
                data=source.read(name);record=manifest['files'][name]
                if hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('SOURCE_CODE_HASH_MISMATCH')
                additions[name]=(data,record['mode'])
    paths={'scripts/predict.py':'submission/predict_qwen35_system.py',
        'scripts/qwen35_b2_runner.py':'scripts/qwen35_b2_runner.py',
        'scripts/qwen35_system_adapter.py':'scripts/qwen35_system_adapter.py',
        'submission/predict_vllm.py':'submission/predict_vllm.py',
        'submission/platform_environment_probe.py':'submission/platform_environment_probe.py',
        'README.md':'docs/qwen35_system_20261013/README.md',
        'build_backend.py':'submission/probe_build_backend.py'}
    for name,path in paths.items():additions[name]=((repo/path).read_bytes().replace(b'\r\n',b'\n'),0o644)
    additions['submission/__init__.py']=(b'',0o644)
    additions['scripts/__init__.py']=(b'',0o644)
    additions['pyproject.toml']=(b'[build-system]\nrequires=[]\nbuild-backend="build_backend"\nbackend-path=["."]\n',0o644)
    assets=dict(repository=state['repository'],revision=state['revision'],
        files=[dict(path=Path(name).name,size=row['bytes'],sha256=row['sha256']) for name,row in state['files'].items()])
    additions['MODEL_MANIFEST.json']=(json_bytes(assets),0o644)
    provenance=dict(profile='QWEN35_B2_HOST_VLLM_EXPERIMENTAL',model_repository=state['repository'],
        model_revision=state['revision'],system_python_torch_vllm=True,bundled_runtime=False,
        compatibility_versions=versions,source_zip_sha256=actual,
        operator_commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),
        full_b2_logic_unchanged=True,workers=16,slots=32,max_num_batched_tokens=8192,
        language_model_only=True,kv_cache_dtype='auto',gpu_memory_utilization=.88,
        prefix_caching=True,chunked_prefill=True,real_gpu_quality_and_time_tested=False)
    for name,(data,mode) in additions.items():expected[name]=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),mode=mode)
    final=dict(provenance,files=expected)
    additions['MANIFEST.json']=(json_bytes(final),0o644)
    data=additions['MANIFEST.json'][0]
    expected['MANIFEST.json']=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),mode=0o644)
    with zipfile.ZipFile(stage,'a',allowZip64=True) as z:
        if set(z.namelist()).intersection(additions):raise ValueError('DUPLICATE_FINAL_MEMBER')
        for name,(data,mode) in additions.items():z.writestr(file_info(name,mode),data)
    if stage.stat().st_size>=40_000_000_000:raise ValueError('ARCHIVE_CAP_EXCEEDED')
    print('VERIFY_ALL_FINAL_MEMBERS',flush=True);validate_members(stage,expected)
    size,checksum=sha256_file(stage,'hash_final_progress')
    result=dict(bytes=size,sha256=checksum,under_cap=size<40_000_000_000,
        all_members_verified=True,files=len(expected),output=str(output),**provenance)
    os.link(stage,output);stage.unlink()
    output.with_suffix('.verification.json').write_bytes(json_bytes(result))
    output.with_suffix('.ready.json').write_bytes(json_bytes(dict(result,status='CPU_VERIFIED_GPU_UNTESTED')))
    output.with_name(output.name+'.sha256').write_text(checksum+'  '+output.name+'\n',encoding='ascii')
    print(json.dumps(result),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',required=True);p.add_argument('--output',required=True);p.add_argument('--source-zip',required=True)
    a=p.parse_args();finalize(a.stage,a.output,a.source_zip)
