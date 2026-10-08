"""A local HTTP server exercises range integrity and exclusive publication."""
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixture_zip(tmp_path):
    builder = module('build_qwen_submission')
    stage = tmp_path / 'stage'
    names = ['pyproject.toml', 'scripts/predict.py', 'Dockerfile', 'runtime/llama/llama-server',
             'runtime/python/bin/python3.12', 'runtime/lib/ld-linux-x86-64.so.2', 'model/Qwen3.8-27B-Q8_0.gguf']
    for name in names:
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('fixture ' + name).encode())
    model = stage / names[-1]
    manifest = dict(commit='fixture', files={name: dict(bytes=(stage / name).stat().st_size,
                                                        sha256=builder.digest(stage / name)) for name in names[:-1]},
                    model_bytes=model.stat().st_size, model_sha256=builder.digest(model))
    (stage / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
    archive = tmp_path / 'source.zip'
    builder.archive(stage, str(archive))
    return archive


@pytest.mark.parametrize('corrupt', [False, True])
def test_parallel_download_requires_authoritative_full_hash(tmp_path, corrupt):
    archive = fixture_zip(tmp_path)
    original_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps(dict(state='READY_ON_SERVER', path=str(archive),
                                       bytes=archive.stat().st_size, sha256=original_sha)), encoding='utf-8')
    token = tmp_path / 'token'
    token.write_text('LOCAL_TEST_TOKEN_32_CHARACTERS_LONG', encoding='utf-8')
    if corrupt:
        with archive.open('r+b') as handle:
            handle.seek(60)
            handle.write(b'tampered')
    server = ThreadingHTTPServer(('127.0.0.1', 0), module('serve_qwen_submission').make_handler(
        archive, receipt, token.read_text()))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / 'download.zip'
    try:
        downloader = module('download_qwen_submission_http')
        arguments = (f'http://127.0.0.1:{server.server_port}/artifact', token,
                     original_sha, archive.stat().st_size, output)
        if corrupt:
            with pytest.raises(ValueError, match='AUTHORITATIVE_ARCHIVE_HASH_MISMATCH'):
                downloader.download(*arguments, workers=3, range_bytes=128, timeout=5)
            assert not output.exists()
            assert json.loads(output.with_suffix('.zip.status.json').read_text())['state'] == 'FAILED'
        else:
            status = downloader.download(*arguments, workers=3, range_bytes=128, timeout=5)
            assert status['state'] == 'READY'
            assert output.read_bytes() == archive.read_bytes()
            with pytest.raises(ValueError, match='DOWNLOAD_PATH_ALREADY_EXISTS'):
                downloader.download(*arguments, workers=3, range_bytes=128, timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
