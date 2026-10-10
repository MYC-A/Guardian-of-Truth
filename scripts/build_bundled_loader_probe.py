"""Build a compact probe with the exact private Python/loader, no model weights."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import zipfile

RUNTIME_SHA256='bd8fae06c167df4b166e708cccc76022e013755efb741409e533c4b3db1f5e2f'
PREFIXES=('runtime/python/','runtime/lib/','runtime/toolchain/','licenses/')
CAP=200_000_000


def digest(path):
    checksum=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(4<<20),b''):checksum.update(chunk)
    return checksum.hexdigest()


def build(runtime,output,expected_sha=RUNTIME_SHA256):
    runtime,output=Path(runtime).resolve(),Path(output).resolve()
    partial=output.with_name(output.name+'.partial')
    receipt_path=output.with_suffix('.verification.json')
    if any(path.exists() for path in (output,partial,receipt_path)):
        raise FileExistsError('OUTPUT_ALREADY_EXISTS')
    if runtime in (output,partial,receipt_path):raise ValueError('INPUT_OUTPUT_COLLISION')
    identity=(runtime.stat().st_size,runtime.stat().st_mtime_ns)
    if digest(runtime)!=expected_sha:raise ValueError('RUNTIME_SHA256_MISMATCH')
    root=Path(__file__).resolve().parents[1]
    output.parent.mkdir(parents=True,exist_ok=True)
    manifest=dict(purpose='BUNDLED_LOADER_DIAGNOSTIC_ONLY_NOT_FOR_SCORING',
                  expected_exit_code=2,full_runtime_sha256=expected_sha,files={})
    with zipfile.ZipFile(runtime) as source:
        original=json.loads(source.read('MANIFEST.json'))
        manifest['runtime_source_sha']=original['source_sha']
        wrapper=source.read('runtime/python/run_python.sh')
        manifest['original_launcher_sha256']=hashlib.sha256(wrapper).hexdigest()
        marker=b'# Children start this same wrapper via sys.executable.'
        if wrapper.count(marker)!=1:raise ValueError('UNKNOWN_LAUNCHER_CONTRACT')
        contrast=wrapper.replace(marker,
            b'LIBRARY_PATHS="$LIBRARY_PATHS${GUARDIAN_PROBE_DRIVER_DIRS:+:$GUARDIAN_PROBE_DRIVER_DIRS}"\n'+marker)
        generated={
            'scripts/predict.py':(root/'submission/bundled_loader_probe.py').read_bytes(),
            'scripts/probe_supervisor.py':(root/'submission/platform_environment_probe.py').read_bytes(),
            'probe_build_backend.py':(root/'submission/probe_build_backend.py').read_bytes(),
            'pyproject.toml':b'[build-system]\nrequires=[]\nbuild-backend="probe_build_backend"\nbackend-path=["."]\n',
            'runtime/python/run_python_driver_probe.sh':contrast,
            'DIAGNOSTIC_ONLY_NOT_FOR_SCORING.txt':b'No weights, input reads, predictions or scoring. Expected exit2 after printing diagnosis.\n',
        }
        selected=[row for row in source.infolist() if row.filename.startswith(PREFIXES)]
        names=[row.filename for row in selected]
        if len(names)!=len(set(names)) or set(names)&set(generated):raise ValueError('DUPLICATE_PATH')
        if not all(name in names for name in ('runtime/python/run_python.sh',
                'runtime/python/bin/python3.12.real','runtime/lib/ld-linux-x86-64.so.2',
                'runtime/toolchain/lib/x86_64-linux-gnu/libc.so.6')):
            raise ValueError('REQUIRED_PRIVATE_RUNTIME_MISSING')
        try:
            with partial.open('xb') as raw, zipfile.ZipFile(raw,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as target:
                def put(name,mode,stream,expected=None):
                    if name.startswith('/') or '\\' in name or '..' in Path(name).parts:
                        raise ValueError('UNSAFE_PATH')
                    info=zipfile.ZipInfo(name,(1980,1,1,0,0,0))
                    info.create_system=3;info.external_attr=(stat.S_IFREG|mode)<<16
                    info.compress_type=zipfile.ZIP_DEFLATED;info._compresslevel=1
                    checksum=hashlib.sha256();size=0
                    with target.open(info,'w',force_zip64=True) as destination:
                        for chunk in iter(lambda:stream.read(4<<20),b''):
                            destination.write(chunk);checksum.update(chunk);size+=len(chunk)
                    row=dict(bytes=size,sha256=checksum.hexdigest(),mode=mode)
                    if expected is not None and row!=expected:raise ValueError('SOURCE_MEMBER_MISMATCH:'+name)
                    manifest['files'][name]=row
                    if raw.tell()>CAP:raise ValueError('PROBE_TOO_LARGE')
                for member in selected:
                    with source.open(member) as stream:
                        put(member.filename,(member.external_attr>>16)&0o777,stream,original['files'][member.filename])
                for name,value in generated.items():
                    with io.BytesIO(value) as stream:put(name,0o755 if name.endswith('.sh') else 0o644,stream)
                target.writestr('MANIFEST.json',(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode())
            if partial.stat().st_size>CAP:raise ValueError('PROBE_TOO_LARGE')
            if identity!=(runtime.stat().st_size,runtime.stat().st_mtime_ns):raise ValueError('RUNTIME_CHANGED')
            with zipfile.ZipFile(partial) as archive:
                if set(archive.namelist())!=set(manifest['files'])|{'MANIFEST.json'}:
                    raise ValueError('PROBE_FILE_SET_MISMATCH')
                for name,row in manifest['files'].items():
                    checksum=hashlib.sha256();size=0
                    with archive.open(name) as stream:
                        for chunk in iter(lambda:stream.read(4<<20),b''):checksum.update(chunk);size+=len(chunk)
                    if (size,checksum.hexdigest())!=(row['bytes'],row['sha256']):
                        raise ValueError('PROBE_VALIDATION_FAILED:'+name)
            receipt=dict(output=str(output),bytes=partial.stat().st_size,sha256=digest(partial),
                files=len(manifest['files'])+1,original_launcher_sha256=manifest['original_launcher_sha256'],
                full_runtime_sha256=expected_sha,purpose=manifest['purpose'],
                scope='Exact private loader/Python/native closure; no vendor packages or weights',
                validation='All included source member SHA256 and all final member CRC/SHA256 verified')
            os.link(partial,output)
            with receipt_path.open('x',encoding='utf-8',newline='\n') as stream:
                json.dump(receipt,stream,indent=2);stream.write('\n')
            return receipt
        finally:
            partial.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.runtime,args.output)))
