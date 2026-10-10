import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

from scripts import build_platform_environment_probe as builder


def test_tiny_probe_archive_is_valid_and_cannot_be_mistaken_for_predictions(tmp_path):
    output=tmp_path/'guardian-environment-probe.zip'
    receipt=builder.build(output)
    assert receipt['purpose']=='DIAGNOSTIC_ONLY_NOT_FOR_SCORING'
    assert receipt['bytes']==output.stat().st_size<100000
    assert receipt['sha256']==hashlib.sha256(output.read_bytes()).hexdigest()
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        names=archive.namelist()
        assert 'scripts/predict.py' in names
        assert all(not name.startswith(('model/','runtime/','outputs/')) for name in names)
        manifest=json.loads(archive.read('MANIFEST.json'))
        assert manifest['expected_exit_code']==2
        for name,row in manifest['files'].items():
            raw=archive.read(name)
            assert len(raw)==row['bytes']
            assert hashlib.sha256(raw).hexdigest()==row['sha256']
    with pytest.raises(FileExistsError):builder.build(output)


def test_probe_wheel_has_no_runtime_dependencies_or_data(tmp_path):
    backend=Path(__file__).resolve().parents[1]/'submission/probe_build_backend.py'
    spec=importlib.util.spec_from_file_location('probe_backend_fixture',backend)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    name=module.build_wheel(tmp_path)
    with zipfile.ZipFile(tmp_path/name) as wheel:
        metadata=wheel.read(module.DIST+'/METADATA').decode()
        assert 'Requires-Dist:' not in metadata
        assert all('.dist-info/' in item for item in wheel.namelist())
        assert wheel.testzip() is None
