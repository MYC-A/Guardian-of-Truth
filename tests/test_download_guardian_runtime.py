import hashlib
import shlex
import subprocess
import sys
import pytest
from scripts import download_guardian_runtime as download


def test_verified_parts_publish_exact_zip_bytes(tmp_path):
    parts = [tmp_path/'part0', tmp_path/'part1']
    parts[0].write_bytes(b'PK-first')
    parts[1].write_bytes(b'-second')
    output = tmp_path/'runtime.zip'
    raw = b'PK-first-second'
    download.publish(parts, output, len(raw), hashlib.sha256(raw).hexdigest())
    assert output.read_bytes() == raw
    assert all(p.exists() for p in parts)
    download.publish(parts, output, len(raw), hashlib.sha256(raw).hexdigest())


def test_corrupt_transfer_does_not_publish_final(tmp_path):
    part = tmp_path/'part'
    part.write_bytes(b'wrong')
    output = tmp_path/'runtime.zip'
    with pytest.raises(RuntimeError, match='mismatch'):
        download.publish([part], output, 5, hashlib.sha256(b'right').hexdigest())
    assert not output.exists()
    assert part.read_bytes() == b'wrong'


def test_existing_other_archive_is_preserved(tmp_path):
    output = tmp_path/'runtime.zip'
    output.write_bytes(b'original')
    with pytest.raises(RuntimeError, match='not be overwritten'):
        download.publish([], output, 0, hashlib.sha256(b'').hexdigest())
    assert output.read_bytes() == b'original'


@pytest.mark.parametrize('prefix', [0, 4, 11])
def test_remote_range_hash_covers_existing_prefix_on_resume(tmp_path, monkeypatch, prefix):
    source = tmp_path/'server.zip'
    source.write_bytes(b'abcdefghijk')
    monkeypatch.setattr(download, 'SIZE', 11)
    command = download.remote_command(prefix, 11-prefix, str(source), verify_start=0, verify_count=11)
    program = shlex.split(command)[2]
    result = subprocess.run([sys.executable, '-c', program], capture_output=True, timeout=5)
    assert result.returncode == 0
    assert result.stdout == source.read_bytes()[prefix:]
    expected = 'GUARDIAN_CHUNK_SHA256='+hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.stderr.decode().strip() == expected
