import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from scripts import build_qwen35_system_submission as builder
from scripts.prepare_qwen35_weights import info

REVISION='9d1823d2dee688a6b25e77009dc727688c44936e'

def source(tmp_path):
    files={}
    for package in ('transformers','huggingface-hub','tokenizers','safetensors','regex','typer','pydantic','jsonschema'):
        module=package.replace('-','_');dist=module+'-1.0.dist-info'
        files[f'runtime/site-packages/{module}/__init__.py']=b'# controlled package'
        files[f'runtime/site-packages/{dist}/METADATA']=f'Name: {package}\nVersion: 1.0\n'.encode()
        rows=io.StringIO();writer=csv.writer(rows)
        writer.writerow([f'{module}/__init__.py','',''])
        writer.writerow([f'{dist}/METADATA','',''])
        writer.writerow([f'{dist}/RECORD','',''])
        files[f'runtime/site-packages/{dist}/RECORD']=rows.getvalue().encode()
    # An embedded metadata fixture must never override a top-level distribution.
    files['runtime/site-packages/fixtures/nested/transformers-999.dist-info/METADATA']=b'Name: transformers\nVersion: 999\n'
    files['src/guardian_truth/__init__.py']=b'# preserved source'
    files['runtime/site-packages/torch/__init__.py']=b'# excluded platform torch'
    manifest={'files':{n:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),mode=0o644) for n,data in files.items()}}
    path=tmp_path/'source.zip'
    with zipfile.ZipFile(path,'w') as z:
        for n,data in files.items():z.writestr(info(n),data)
        z.writestr(info('MANIFEST.json'),builder.json_bytes(manifest))
    return path

def stage(tmp_path):
    prefix='model/'+REVISION+'/'
    payloads={'config.json':json.dumps(dict(model_type='qwen3_5_moe',quantization_config=dict(quant_method='fp8'))).encode(),
              'model.safetensors.index.json':json.dumps(dict(weight_map={'weight':'weights.safetensors'})).encode(),
              'weights.safetensors':b'controlled weights'}
    path=tmp_path/'stage.partial'
    with zipfile.ZipFile(path,'w') as z:
        for n,data in payloads.items():z.writestr(info(prefix+n),data)
    files={prefix+n:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),mode=0o644) for n,data in payloads.items()}
    path.with_name(path.name+'.weights.json').write_text(json.dumps(dict(repository='Qwen/Qwen3.5-35B-A3B-FP8',
        revision=REVISION,all_model_files_verified=True,files=files)))
    return path

def test_compat_closure_ignores_nested_metadata_and_torch(tmp_path):
    path=source(tmp_path)
    with zipfile.ZipFile(path) as z:members,versions=builder.compatibility_members(z)
    assert versions['transformers']=='1.0'
    assert not any('/torch/' in n or '/fixtures/' in n for n in members)

def test_whole_build_preserves_weights_and_has_no_bundled_runtime(tmp_path):
    original=source(tmp_path);partial=stage(tmp_path);out=tmp_path/'out.zip'
    result=builder.finalize(partial,out,original,expected_source_sha=hashlib.sha256(original.read_bytes()).hexdigest())
    assert result['all_members_verified'] and result['under_cap'] and result['bundled_runtime'] is False
    with zipfile.ZipFile(out) as z:
        assert not any(n.startswith('runtime/') for n in z.namelist())
        assert z.read('model/'+REVISION+'/weights.safetensors')==b'controlled weights'
        assert z.read('src/guardian_truth/__init__.py')==b'# preserved source'
        assert b'compat/site-packages' in z.read('scripts/predict.py')
        assert result['full_b2_logic_unchanged'] is True
    assert not partial.exists()
    assert hashlib.sha256(out.read_bytes()).hexdigest()==result['sha256']
    with pytest.raises(FileExistsError):builder.finalize(partial,out,original)

def test_wrong_source_hash_does_not_append_any_code(tmp_path):
    original=source(tmp_path);partial=stage(tmp_path);before=partial.read_bytes()
    with pytest.raises(ValueError,match='SOURCE_ZIP_SHA256_MISMATCH'):
        builder.finalize(partial,tmp_path/'out.zip',original,expected_source_sha='0'*64)
    assert partial.read_bytes()==before
