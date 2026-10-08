"""Final acceptance boundaries with private pytest fixtures, never real weights."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('final_submission_verifier', ROOT / 'scripts/verify_qwen_submission.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def candidate(tmp_path, *, changes=None, extra=None, missing=None, known_model=False):
    """Create a self-consistent but synthetic ZIP confined to pytest's temp path."""
    model = b'DECLARED_PRIVATE_UNIT_TEST_FIXTURE_NOT_MODEL_WEIGHTS'
    reference = dict(verifier.MODEL_REFERENCE)
    if not known_model:
        reference.update(bytes=len(model), sha256=hashlib.sha256(model).hexdigest())
    header = b'\x7fELF\x02\x01' + b'\0' * 12 + struct.pack('<H', 62)
    files = {name: header + b'DECLARED_UNIT_FIXTURE' for name in verifier.runtime.EXECUTABLES}
    files.update({'pyproject.toml': b'[build-system]\nrequires=[]\n',
                  'scripts/predict.py': b'# Private unit fixture\n', 'Dockerfile': b'FROM fixture\n',
                  'model/' + reference['filename']: model})
    files.update(extra or {})
    manifest = dict(version='guardian-qwen-offline-1', runtime_only=False, profile='B2',
                    model_reference=reference, model_bytes=reference['bytes'], model_sha256=reference['sha256'],
                    runtime_build=dict(llama_revision=verifier.runtime.LLAMA_REVISION),
                    commit='UNIT_FIXTURE_NOT_REAL_CODE_IDENTITY',
                    files={name: dict(bytes=len(value), sha256=hashlib.sha256(value).hexdigest())
                           for name, value in files.items() if not name.startswith('model/')})
    manifest.update(changes or {})
    files['MANIFEST.json'] = json.dumps(manifest).encode()
    path = tmp_path / 'DECLARED_UNIT_FIXTURE.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, value in files.items():
            if name == missing:
                continue
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            mode = 0o100755 if name in verifier.runtime.EXECUTABLES else 0o100644
            entry.external_attr = mode << 16
            archive.writestr(entry, value)
    return path, reference


def test_self_consistent_tiny_weights_cannot_pass_final_acceptance(tmp_path):
    path, _ = candidate(tmp_path)
    # The legacy checksum verifier accepts this internally consistent fixture.
    verifier.archive_reader.verify_archive(path)
    # The final verifier additionally requires the actual original model identity.
    with pytest.raises(ValueError, match='PINNED_ORIGINAL_MODEL_IDENTITY'):
        verifier.verify_submission(path)


def test_claiming_real_identity_cannot_conceal_truncated_model(tmp_path):
    path, _ = candidate(tmp_path, known_model=True)
    with pytest.raises(ValueError, match='COMPLETE_ORIGINAL_MODEL_SIZE'):
        verifier.verify_submission(path)


@pytest.mark.parametrize('change,error', [({'fixture_only': True}, 'NOT_RUNTIME_OR_FIXTURE'),
                                        ({'runtime_only': True}, 'NOT_RUNTIME_OR_FIXTURE'),
                                        ({'profile': 'R_comb'}, 'APPROVED_B2'),
                                        ({'runtime_build': {'llama_revision': 'unverified'}}, 'PINNED_LLAMA')])
def test_unapproved_fixture_profile_or_engine_refused(tmp_path, monkeypatch, change, error):
    path, reference = candidate(tmp_path, changes=change)
    monkeypatch.setattr(verifier, 'MODEL_REFERENCE', reference)  # Test process only.
    with pytest.raises(ValueError, match=error):
        verifier.verify_submission(path)


def test_missing_root_runtime_file_is_not_a_complete_zip(tmp_path, monkeypatch):
    path, reference = candidate(tmp_path, missing='scripts/predict.py')
    monkeypatch.setattr(verifier, 'MODEL_REFERENCE', reference)
    with pytest.raises(ValueError, match='ZIP_MANIFEST_FILE_SET_MISMATCH'):
        verifier.verify_submission(path)


@pytest.mark.parametrize('name,error', [('runtime/lib/libcuda.so.1', 'HOST_NVIDIA_DRIVER'),
                                     ('outputs/bench/results.json', 'UNAPPROVED_SUBMISSION_ROOT'),
                                     ('model/cache/state.json', 'UNAPPROVED_MODEL'),
                                     ('licenses/secrets/mistral.env', 'RESEARCH_CACHE_FIXTURE_OR_SECRET'),
                                     ('src/module/password.env', 'CREDENTIAL_OR_GENERATED_CACHE')])
def test_forbidden_extra_data_and_host_driver_refused(tmp_path, monkeypatch, name, error):
    path, reference = candidate(tmp_path, extra={name: b'Forbidden private unit fixture'})
    monkeypatch.setattr(verifier, 'MODEL_REFERENCE', reference)
    with pytest.raises(ValueError, match=error):
        verifier.verify_submission(path)


def test_literal_private_key_never_accepted_as_source(tmp_path, monkeypatch):
    path, reference = candidate(tmp_path, extra={'src/module/config.py': b'-----BEGIN OPENSSH PRIVATE KEY-----'})
    monkeypatch.setattr(verifier, 'MODEL_REFERENCE', reference)
    with pytest.raises(ValueError, match='POSSIBLE_LITERAL_CREDENTIAL'):
        verifier.verify_submission(path)


def test_receipt_does_not_claim_gpu_execution_or_quality(tmp_path, monkeypatch):
    path, reference = candidate(tmp_path)
    monkeypatch.setattr(verifier, 'MODEL_REFERENCE', reference)
    # Only inside this unit process can the explicit synthetic model be checked;
    # production constants still authenticate the28.6GB original checkpoint.
    report = verifier.verify_submission(path, verifier.sha256(path))
    assert report['status'] == 'VERIFIED_OFFLINE_PACKAGING'
    assert report['GPU_INFERENCE'].startswith('NOT_EXECUTED')
    assert report['rebuilt_runtime_quality'].startswith('NOT_EVALUATED')
    assert report['zip_sha256'] == verifier.sha256(path)
    with pytest.raises(ValueError, match='EXPECTED_SUBMISSION_ZIP_SHA256'):
        verifier.verify_submission(path, '0' * 64)


def test_existing_receipt_is_preserved_without_archive_read(tmp_path, monkeypatch):
    receipt = tmp_path / 'immutable.json'
    receipt.write_text('Historical receipt', encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['verify_qwen_submission.py', '--archive', str(tmp_path / 'missing.zip'),
                                     '--receipt', str(receipt)])
    with pytest.raises(ValueError, match='RECEIPT_ALREADY_EXISTS'):
        verifier.main()
    assert receipt.read_text(encoding='utf-8') == 'Historical receipt'
