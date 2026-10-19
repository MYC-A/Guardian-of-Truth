"""Independent offline release inspection, including every ZIP member and tensor index."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.build_judge_submission import CODE,runtime_closure,CAP
from scripts.build_platform_startup_probe import stream_digest
from guardian_truth.judge.ensemble import BASE_ID,BASE_REVISION,ADAPTER_SHA256,PRIMARY_ID,PRIMARY_REVISION,validate


def check(value,reason):
    if not value:raise ValueError(reason)


def tensor_header(stream,size):
    raw=stream.read(8);check(len(raw)==8,'SHORT_SAFETENSORS')
    length=struct.unpack('<Q',raw)[0];check(2<=length<=64<<20 and 8+length<=size,'SAFETENSORS_HEADER_BOUNDS')
    header=json.loads(stream.read(length));payload=size-8-length;spans=[]
    for name,row in header.items():
        if name=='__metadata__':continue
        check(isinstance(row,dict) and isinstance(row.get('shape'),list),'TENSOR_SHAPE')
        check(all(type(v) is int and v>=0 for v in row['shape']),'TENSOR_DIMENSIONS')
        offsets=row.get('data_offsets');check(isinstance(offsets,list) and len(offsets)==2,'TENSOR_OFFSETS')
        lo,hi=offsets;check(type(lo) is int and type(hi) is int and 0<=lo<=hi<=payload,'TENSOR_DATA_BOUNDS')
        spans.append((lo,hi))
    cursor=0
    for lo,hi in sorted(spans):check(lo==cursor,'TENSOR_OVERLAP_OR_GAP');cursor=hi
    check(cursor==payload,'TENSOR_PAYLOAD_LENGTH')
    return {k:v for k,v in header.items() if k!='__metadata__'}


def model_index(z,prefix,expected_keys,expected_shards):
    index=json.loads(z.read(prefix+'model.safetensors.index.json'))['weight_map']
    shards=set(index.values());check(len(index)==expected_keys and len(shards)==expected_shards,'MODEL_INDEX_COUNT')
    all_tensors={}
    for shard in sorted(shards):
        with z.open(prefix+shard) as stream:header=tensor_header(stream,z.getinfo(prefix+shard).file_size)
        check(set(header)=={k for k,v in index.items() if v==shard},'MODEL_SHARD_INDEX_KEYS')
        all_tensors.update(header)
    return len(all_tensors)


def main():
    p=argparse.ArgumentParser()
    for name in ('archive','source','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--commit',required=True);a=p.parse_args()
    receipt=json.loads(a.archive.with_suffix('.verification.json').read_bytes())
    check(receipt['all_members_verified'] and receipt['under_cap'],'BUILDER_UNVERIFIED')
    check(a.archive.stat().st_size<CAP,'ARCHIVE_CAP')
    with a.archive.open('rb') as f:size,digest=stream_digest(f)
    check((size,digest)==(receipt['bytes'],receipt['sha256']),'ARCHIVE_SHA256')
    with zipfile.ZipFile(a.archive) as z,zipfile.ZipFile(a.source) as source:
        names=z.namelist();check(len(names)==len(set(names)),'DUPLICATE_MEMBERS')
        check(all(not n.startswith('/') and '\\' not in n and ':' not in n and '..' not in n.split('/') and '\x00' not in n for n in names),'UNSAFE_MEMBER_PATH')
        manifest=json.loads(z.read('MANIFEST.json'));files=manifest['files'];check(set(files)==set(names)-{'MANIFEST.json'},'MANIFEST_FILE_SET')
        check(manifest['judge_build']['source_revision']==a.commit,'CODE_REVISION')
        cfg=json.loads(z.read('JUDGE_CONFIG.json'));validate(cfg)
        pinned=lambda path:subprocess.check_output(['git','show',a.commit+':'+path],cwd=ROOT).replace(b'\r\n',b'\n')
        check(cfg==json.loads(pinned('submission/JUDGE_BLEND40.json')),'CONFIG_NOT_PINNED')
        check(cfg['positive_rate']==.4 and cfg['bounded_turn_shape'] is True,'DECISION_CONFIG')
        check(cfg['watchdog_seconds']<1800 and cfg['kill_seconds']<cfg['watchdog_seconds'],'DEADLINE_CONFIG')
        for name,path in CODE.items():
            if name=='JUDGE_CONFIG.json':continue
            if name=='README.md':path='docs/judge_20261013/README_BLEND40.md'
            check(z.read(name)==pinned(path),'SOURCE_BYTES:'+name)
        check(all(name in files for name in runtime_closure(ROOT)),'RUNTIME_SOURCE_CLOSURE')
        for name in files:
            if name.startswith(('src/','scripts/')) and name.endswith('.py'):ast.parse(z.read(name),filename=name)
        original=json.loads(source.read('MANIFEST.json'))['files']
        runtime={n:r for n,r in files.items() if n.startswith('runtime/')}
        check(runtime=={n:r for n,r in original.items() if n.startswith('runtime/')},'RUNTIME_BYTES_OR_MODES_CHANGED')
        for name in ('runtime/python/bin/python3.12.real','runtime/lib/ld-linux-x86-64.so.2'):
            with z.open(name) as f:header=f.read(20)
            check(header[:4]==b'\x7fELF' and header[4]==2 and int.from_bytes(header[18:20],'little')==62,'EXECUTABLE_ELF')
            check(stat.S_IMODE(z.getinfo(name).external_attr>>16)&0o111,'EXECUTABLE_MODE')
        models=json.loads(z.read('JUDGE_MANIFEST.json'));secondary=models['secondary']
        check((models['repository'],models['revision'])==(PRIMARY_ID,PRIMARY_REVISION),'PRIMARY_MODEL_IDENTITY')
        check((secondary['repository'],secondary['revision'])==(BASE_ID,BASE_REVISION),'SECONDARY_MODEL_IDENTITY')
        check(secondary['adapter']['sha256']==ADAPTER_SHA256,'ADAPTER_IDENTITY')
        for prefix,rows in [('model/judge/',models['files']),('model/judge4b/',secondary['files']),('model/judge4b-adapter/',secondary['adapter']['files'])]:
            for row in rows:
                member=files[prefix+row['path']];check((member['bytes'],member['sha256'])==(row['size'],row['sha256']),'MODEL_MANIFEST_HASH')
        primary_count=model_index(z,'model/judge/',95427,6);secondary_count=model_index(z,'model/judge4b/',398,3)
        adapter_name='model/judge4b-adapter/adapter_model.safetensors'
        with z.open(adapter_name) as f:adapter=tensor_header(f,z.getinfo(adapter_name).file_size)
        check(len(adapter)==36*7*2 and all('.lora_A.' in k or '.lora_B.' in k for k in adapter),'ADAPTER_TENSOR_SET')
        config=json.loads(z.read('model/judge4b-adapter/adapter_config.json'))
        check(config['r']==16 and config['lora_alpha']==32 and config['peft_type']=='LORA','ADAPTER_CONFIG')
        # CRC + bytes + SHA + mode for every actual archive member, independently
        # of the builder. Only MANIFEST itself is covered by the full ZIP SHA.
        for i,name in enumerate(names):
            with z.open(name) as f:actual_size,actual_digest=stream_digest(f)
            if name!='MANIFEST.json':
                row=files[name];check((actual_size,actual_digest,stat.S_IMODE(z.getinfo(name).external_attr>>16))==
                    (row['bytes'],row['sha256'],row['mode']),'MEMBER_VERIFICATION:'+name)
            if i%10000==0:print(json.dumps(dict(event='verify_members',done=i,of=len(names))),flush=True)
    result=dict(archive=str(a.archive),bytes=size,sha256=digest,files=len(names),source_commit=a.commit,
        all_members_verified=True,runtime_preserved=True,primary_tensors=primary_count,secondary_tensors=secondary_count,
        adapter_tensors=len(adapter),tensor_indexes_verified=True,models_pinned=True,under_cap=True,
        gpu_evidence_separate=True,private_test_time_proven=False)
    a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result),flush=True)


if __name__=='__main__':main()
