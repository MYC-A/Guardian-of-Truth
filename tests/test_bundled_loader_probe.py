import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

import pytest
from scripts import build_bundled_loader_probe as builder
from submission import platform_environment_probe as supervisor


def module(monkeypatch):
    monkeypatch.setitem(sys.modules,'probe_supervisor',supervisor)
    spec=importlib.util.spec_from_file_location('bundled_probe_fixture',
        Path(__file__).resolve().parents[1]/'submission/bundled_loader_probe.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def runtime_fixture(tmp_path):
    output=tmp_path/'runtime.zip'
    wrapper=b'#!/bin/sh\nLIBRARY_PATHS="$ROOT/runtime/lib"\n# Children start this same wrapper via sys.executable.\nexec actual-loader\n'
    files={
        'runtime/python/run_python.sh':wrapper,
        'runtime/python/bin/python3.12.real':b'fixture-python',
        'runtime/lib/ld-linux-x86-64.so.2':b'fixture-loader',
        'runtime/toolchain/lib/x86_64-linux-gnu/libc.so.6':b'fixture-libc',
        'runtime/site-packages/large.so':b'NOT_TO_SHIP_VENDOR',
        'model/weights.safetensors':b'NOT_TO_SHIP_WEIGHTS',
    }
    manifest=dict(source_sha='fixture-source',files={name:dict(bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),mode=0o755) for name,raw in files.items()})
    with zipfile.ZipFile(output,'w') as archive:
        for name,raw in files.items():
            info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=(stat.S_IFREG|0o755)<<16
            archive.writestr(info,raw)
        archive.writestr('MANIFEST.json',json.dumps(manifest))
    return output,wrapper


def test_build_keeps_exact_original_launcher_and_native_bytes_without_weights(tmp_path):
    runtime,wrapper=runtime_fixture(tmp_path)
    original=runtime.read_bytes()
    output=tmp_path/'probe.zip'
    receipt=builder.build(runtime,output,expected_sha=hashlib.sha256(original).hexdigest())
    assert runtime.read_bytes()==original
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert archive.read('runtime/python/run_python.sh')==wrapper
        assert not any(name.startswith(('runtime/site-packages/','model/')) for name in archive.namelist())
        manifest=json.loads(archive.read('MANIFEST.json'))
        assert manifest['purpose'].endswith('NOT_FOR_SCORING')
        changed=archive.read('runtime/python/run_python_driver_probe.sh')
        assert changed.replace(b'LIBRARY_PATHS="$LIBRARY_PATHS${GUARDIAN_PROBE_DRIVER_DIRS:+:$GUARDIAN_PROBE_DRIVER_DIRS}"\n',b'')==wrapper
        assert (archive.getinfo('runtime/python/run_python.sh').external_attr>>16)&0o777==0o755
        assert 'Requires-Dist' not in archive.read('pyproject.toml').decode()
    assert receipt['sha256']==hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):builder.build(runtime,output,expected_sha=receipt['full_runtime_sha256'])


def test_wrong_source_identity_fails_before_creating_output(tmp_path):
    runtime,_=runtime_fixture(tmp_path)
    output=tmp_path/'probe.zip'
    with pytest.raises(ValueError,match='RUNTIME_SHA256_MISMATCH'):
        builder.build(runtime,output,expected_sha='0'*64)
    assert not output.exists() and not output.with_name('probe.zip.partial').exists()


def test_driver_contrast_keeps_only_absolute_existing_driver_directories(tmp_path,monkeypatch):
    probe=module(monkeypatch)
    driver=tmp_path/'nvidia';driver.mkdir();(driver/'libcuda.so.1').write_bytes(b'fixture')
    foreign=tmp_path/'hpcx';foreign.mkdir();(foreign/'libmpi.so').write_bytes(b'fixture')
    result=probe.driver_directories({'LD_LIBRARY_PATH':os.pathsep.join(map(str,
        (driver,foreign,Path('.'),driver)))+os.pathsep+'/missing\npath'})
    assert str(driver) in result and str(foreign) not in result and '.' not in result
    assert result.count(str(driver))==1


def test_probe_never_reads_input_or_writes_predictions_and_runs_both_arms(tmp_path,monkeypatch):
    probe=module(monkeypatch)
    script=tmp_path/'scripts/predict.py';script.parent.mkdir()
    monkeypatch.setattr(probe,'__file__',str(script))
    files={}
    for name in ('run_python.sh','run_python_driver_probe.sh'):
        path=tmp_path/'runtime/python'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'fixture-wrapper')
        files[path.relative_to(tmp_path).as_posix()]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (tmp_path/'MANIFEST.json').write_text(json.dumps(dict(files=files,runtime_source_sha='fixture',
        full_runtime_sha256='fixture',original_launcher_sha256='fixture')))
    calls=[]
    monkeypatch.setattr(supervisor,'run_probe',lambda name,code,**kwargs:calls.append((name,code,kwargs)))
    monkeypatch.setattr(supervisor,'emit',lambda *args:None)
    target=tmp_path/'predictions.parquet'
    assert probe.main(['--input',str(tmp_path/'nonexistent'),'--output',str(target)])==2
    assert not target.exists()
    assert [row[0] for row in calls]==['original_bundled_loader','driver_path_contrast']
    assert calls[0][2]['environment_overrides']=={}
    assert 'GUARDIAN_PROBE_DRIVER_DIRS' in calls[1][2]['environment_overrides']
    assert calls[0][1]==calls[1][1]


def test_supervisor_custom_wrapper_retains_timeout_and_redaction(monkeypatch):
    calls=[]
    class Process:
        pid=700
        def wait(self,timeout):return 0
    def spawn(command,**kwargs):
        calls.append((command,kwargs['env']))
        return Process()
    monkeypatch.setattr(supervisor,'require_cleanup_support',lambda:None)
    monkeypatch.setattr(supervisor.subprocess,'Popen',spawn)
    monkeypatch.setattr(supervisor,'cleanup_child',lambda *args:None)
    monkeypatch.setattr(supervisor,'emit',lambda *args:None)
    result=supervisor.run_probe('wrapper','unused',python='/private/run_python.sh',
        environment_overrides={'GUARDIAN_PROBE_DRIVER_DIRS':'/driver'})
    assert calls[0][0][0]=='/private/run_python.sh'
    assert calls[0][1]['GUARDIAN_PROBE_DRIVER_DIRS']=='/driver'
    assert result['returncode']==0
