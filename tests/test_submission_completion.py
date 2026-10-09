"""Operator supervisor identity and extraction bounds; no network/GPU requests."""
import importlib.util
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('submission_completion', ROOT / 'scripts/complete_qwen_submission.py')
completion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(completion)


def test_supervisor_requires_exact_ci_commit_and_stops_terminal_failure():
    sha = '1' * 40
    base = dict(head_sha=sha, path=completion.WORKFLOW, status='in_progress', conclusion=None)
    assert completion.check_run(base, sha) is False
    assert completion.check_run(dict(base, status='completed', conclusion='success'), sha) is True
    with pytest.raises(ValueError, match='EXACT_COMMIT'):
        completion.check_run(dict(base, head_sha='2' * 40), sha)
    with pytest.raises(ValueError, match='EXACT_COMMIT'):
        completion.check_run(dict(base, path='.github/workflows/unrelated.yml'), sha)
    with pytest.raises(RuntimeError, match='TERMINAL_FAILURE_NO_AUTOMATIC_RERUN'):
        completion.check_run(dict(base, status='completed', conclusion='failure'), sha)


def transport(tmp_path, extra=None):
    source = tmp_path / 'transport.zip'
    with zipfile.ZipFile(source, 'w') as archive:
        for name in ['guardian-qwen-a100-runtime.tar.gz', 'guardian-qwen-a100-runtime.tar.gz.sha256',
                     'RUNTIME_MANIFEST.json']:
            archive.writestr(name, b'DECLARED_PRIVATE_TEST_NOT_REAL_RUNTIME')
        if extra:
            archive.writestr(extra, b'DECLARED_PRIVATE_TEST_NOT_REAL_RUNTIME')
    return source


@pytest.mark.parametrize('name,symlink', [('../escape', False), ('C:/escape', False),
                                       ('arbitrary.py', False), ('cpu-smoke.json', True)])
def test_transport_rejects_traversal_unapproved_root_and_links_before_writing(tmp_path, name, symlink):
    entry = zipfile.ZipInfo(name)
    if symlink:
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
    source = transport(tmp_path, entry)
    destination = tmp_path / 'extracted'
    with pytest.raises(ValueError, match='UNSAFE_OR_UNAPPROVED'):
        completion.extract_transport(source, destination)
    assert not destination.exists()
    assert not (tmp_path / 'escape').exists()


def test_transport_extracts_exact_flat_files_and_never_overwrites(tmp_path):
    source = transport(tmp_path)
    destination = tmp_path / 'extracted'
    completion.extract_transport(source, destination)
    assert {p.name for p in destination.iterdir()} == {
        'guardian-qwen-a100-runtime.tar.gz', 'guardian-qwen-a100-runtime.tar.gz.sha256', 'RUNTIME_MANIFEST.json'}
    with pytest.raises(ValueError, match='ALREADY_EXISTS'):
        completion.extract_transport(source, destination)


def test_verified_publication_refuses_existing_file_and_moves_exact_bytes(tmp_path):
    source, destination = tmp_path / 'candidate.zip.partial', tmp_path / 'candidate.zip'
    source.write_bytes(b'DECLARED_PRIVATE_PUBLICATION_FIXTURE')
    destination.write_bytes(b'OTHER_OPERATOR_OUTPUT')
    with pytest.raises(FileExistsError):
        completion.publish_verified(source, destination)
    assert destination.read_bytes() == b'OTHER_OPERATOR_OUTPUT' and source.exists()
    destination.unlink()
    completion.publish_verified(source, destination)
    assert destination.read_bytes() == b'DECLARED_PRIVATE_PUBLICATION_FIXTURE'
    assert not source.exists()
