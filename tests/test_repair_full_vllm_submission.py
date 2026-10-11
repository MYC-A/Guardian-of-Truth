import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.build_platform_startup_probe import file_info
from scripts.repair_full_vllm_submission import adapter_patch, repair
from tests.test_toolchain_private_libc import fixture_source


OLD = b'''class OwnedVllmServer:
    def __init__(self):
        self.value = 42
    def __enter__(self):
        try:
            return self
        except BaseException:
            self.__exit__()
            raise
'''
NEW = b'''import sys
STARTUP_LOG_TAIL_BYTES = 65536
class OwnedVllmServer:
    def __init__(self):
        self.value = 42
        self.popen_started = None
    def __enter__(self):
        try:
            self.popen_started = 1
            return self
        except BaseException as error:
            self.__exit__()
            self._report_startup_failure(error)
            raise
    def _redact_startup_text(self, text):
        return text
    def _report_startup_failure(self, error):
        print('GUARDIAN VLLM STARTUP FAILURE BEGIN', file=sys.stderr)
'''


def full_source(tmp_path):
    path, data = fixture_source(tmp_path)
    data['scripts/qwen_vllm_adapter.py'] = OLD
    data['scripts/predict.py'] = b'PUBLIC ENTRYPOINT UNCHANGED'
    data['src/b2.py'] = b'B2 UNCHANGED'
    manifest = dict(model_mode='FULL_MODELS_SHA256_VERIFIED', source_sha='f' * 40, files={})
    with zipfile.ZipFile(path, 'w') as target:
        for name, raw in data.items():
            target.writestr(file_info(name, 0o755), raw)
            manifest['files'][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), mode=0o755)
        target.writestr(file_info('MANIFEST.json'), json.dumps(manifest))
    reference = tmp_path / 'adapter.py'
    reference.write_bytes(NEW)
    return path, data, reference


def test_full_repair_preserves_weights_b2_launcher_and_manifest_identity(tmp_path):
    source, data, reference = full_source(tmp_path)
    output = tmp_path / 'full-fixed.zip'
    receipt = repair(source, output, adapter_path=reference,
                     source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                     adapter_sha256=hashlib.sha256(OLD).hexdigest())
    changes = receipt['operator_repair']['changes']
    assert len(changes) == 11
    assert receipt['all_members_sha256_crc_modes_verified']
    with zipfile.ZipFile(output) as target:
        for name, raw in data.items():
            if name not in changes:
                assert target.read(name) == raw
        assert target.read('scripts/qwen_vllm_adapter.py') == NEW
        manifest = json.loads(target.read('MANIFEST.json'))
        assert manifest['source_sha'] == 'f' * 40
        assert manifest['model_mode'] == 'FULL_MODELS_SHA256_VERIFIED'
        assert manifest['operator_repair']['system_compiler_fallback'] is False
        assert target.testzip() is None
    assert hashlib.sha256(output.read_bytes()).hexdigest() == receipt['sha256']


def test_unrelated_adapter_change_is_rejected():
    with pytest.raises(ValueError, match='NON_DIAGNOSTIC_ADAPTER_CHANGE'):
        adapter_patch(OLD, NEW.replace(b'self.value = 42', b'self.value = 43'))


def test_source_hash_mismatch_does_not_publish(tmp_path):
    source, _, reference = full_source(tmp_path)
    output = tmp_path / 'not-created.zip'
    with pytest.raises(ValueError, match='SOURCE_ZIP_SHA256_MISMATCH'):
        repair(source, output, adapter_path=reference, source_sha256='0' * 64)
    assert not output.exists()
    assert not Path(str(output) + '.partial').exists()
