"""Reuse verified best ZIP records; replace code and add one completed 35B adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
import time
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.build_platform_startup_probe import raw_copy
from scripts.build_judge_submission import runtime_closure

ADAPTER_SHA='4a44903c463d9244f2816ffd84d8f0bd8ba032a1340ca9b3716e6ae887101313'


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def payload():
    paths=['scripts/judge_submission.py','scripts/judge_stage.py','scripts/judge35_submission.py',
           'scripts/lora35_support.py','scripts/v8_quote_contract.py']
    paths+=runtime_closure(ROOT,entry_points=paths[:3])
    values={p:(ROOT/p).read_bytes() for p in paths}
    values['scripts/__init__.py']=b''
    values['scripts/predict.py']=(ROOT/'submission/predict_judge.py').read_bytes()
    adapter=ROOT/'artifacts/release35/adapter'
    if digest(adapter/'adapter_model.safetensors')!=ADAPTER_SHA:raise ValueError('ADAPTER_DRIFT')
    for name in ('adapter_config.json','adapter_model.safetensors'):
        values['model/lora35_v7/'+name]=(adapter/name).read_bytes()
    cfg=json.loads((ROOT/'submission/JUDGE_OPEN_REVIEW40.json').read_bytes())
    cfg.update(bounded_turn_shape=True,chunk=64,dtype='bfloat16',
        engine_overrides=dict(enforce_eager=True,async_scheduling=False),
        judge_stop_seconds=1050,kill_seconds=1140,watchdog_seconds=1680,
        lora35_verifier=dict(adapter_dir='model/lora35_v7',adapter_sha256=ADAPTER_SHA,
            stop_seconds=1560,threshold=0,review_max_tokens=192,quota_refill=False,
            incomplete_policy='global_baseline_fallback'))
    values['JUDGE_CONFIG.json']=(json.dumps(cfg,indent=2)+'\n').encode()
    values['README.md']=('Guardian 35B open/MAX .40 + bounded-turn fixes + completed V7 35B LoRA verifier.\n'
        'The primary model runs without an adapter. The same 35B weights are reloaded with the V7 adapter\n'
        'only to verify baseline positives. Exact Rule/Evidence quotes, exact YES-NO odds, threshold0,\n'
        'hard protection, no refill. Incomplete verification preserves the complete baseline globally.\n'
        'Only one adapter is included. No 4B model, old adapter, training set or optimizer checkpoint.\n'
        'The last native training attempt made zero optimizer updates and is NOT included.\n'
        'Exploratory: V7 did not beat the base verifier on the previously used 1893-row set;\n'
        'private improvement and full cold competition timing are not established.\n'
        'Operator explicitly requested immediate experimental ZIP assembly.\n').encode()
    values['RELEASE35_MANIFEST.json']=(json.dumps(dict(adapter_sha256=ADAPTER_SHA,
        adapter_version='V7_COMPLETE_LAST16_35B',new_native_optimizer_updates=0,
        original_human_acceptance_gate_passed=False,experimental=True,
        files={p:dict(size=len(v),sha256=hashlib.sha256(v).hexdigest()) for p,v in values.items()}),indent=2)+'\n').encode()
    return values


def run(a):
    start=time.monotonic();values=payload();a.out.parent.mkdir(parents=True,exist_ok=True)
    part=a.out.with_suffix('.building.zip')
    if a.out.exists() or part.exists():raise ValueError('OUTPUT_ALREADY_EXISTS')
    dropped=[];copied=0
    with zipfile.ZipFile(a.source) as src,zipfile.ZipFile(part,'w',allowZip64=True) as dst:
        infos=sorted(src.infolist(),key=lambda f:f.header_offset)
        if len({f.filename for f in infos})!=len(infos):raise ValueError('DUPLICATE_SOURCE_PATHS')
        for i,info in enumerate(infos):
            name=info.filename
            if (name in values or name in ('scripts/judge_blend_submission.py','scripts/judge_lora_stage.py')
                or name.startswith(('model/secondary/','model/adapter/','model/lora35_v7/'))):
                dropped.append(name);continue
            boundary=infos[i+1].header_offset if i+1<len(infos) else src.start_dir
            raw_copy(src,dst,info,boundary);copied+=1
            if copied%10000==0:print(json.dumps(dict(phase='copy',entries=copied,seconds=time.monotonic()-start)),flush=True)
        for name,data in values.items():
            info=zipfile.ZipInfo(name);info.compress_type=zipfile.ZIP_DEFLATED;info.create_system=3
            info.external_attr=(stat.S_IFREG|0o644)<<16
            dst.writestr(info,data,compresslevel=3)
    with zipfile.ZipFile(a.source) as src,zipfile.ZipFile(part) as built:
        names=built.namelist()
        if len(names)!=len(set(names)):raise ValueError('DUPLICATE_OUTPUT_PATHS')
        for name,data in values.items():
            if built.read(name)!=data:raise ValueError('PATCH_BYTES_DRIFT:'+name)
        old={f.filename:f for f in src.infolist()}
        for f in built.infolist():
            if f.filename in values:continue
            o=old[f.filename]
            if (f.CRC,f.file_size,f.compress_size,f.external_attr)!=(o.CRC,o.file_size,o.compress_size,o.external_attr):
                raise ValueError('PRESERVED_RECORD_DRIFT:'+f.filename)
        if any(n.startswith(('model/secondary/','model/adapter/')) for n in names):raise ValueError('STALE_MODEL')
    if part.stat().st_size>=40_000_000_000:raise ValueError('ARCHIVE_SIZE_CAP')
    part.replace(a.out)
    receipt=dict(complete=True,archive=str(a.out),bytes=a.out.stat().st_size,sha256=digest(a.out),
        adapter_sha256=ADAPTER_SHA,copied_records=copied,replaced_or_removed=dropped,
        added_or_updated=len(values),seconds=time.monotonic()-start,
        experimental=True,new_native_optimizer_updates=0,full_private_validation=False)
    a.out.with_suffix('.verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    run(p.parse_args())
