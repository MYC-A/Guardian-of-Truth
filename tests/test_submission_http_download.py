"""A local HTTP server exercises range integrity and exclusive publication."""
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
from contextlib import contextmanager

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


@contextmanager
def range_server(body, digest, behavior):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            assert self.headers['Authorization'] == 'Bearer TEST_TOKEN'
            start, end = map(int, self.headers['Range'][6:].split('-'))
            seen.append(start)
            mode = behavior(start)
            if mode == 'headers_trickle':
                try:
                    self.connection.sendall(b'HTTP/1.1 206 Partial Content\r\n')
                    for _ in range(100):
                        self.connection.sendall(b'X-Delay: yes\r\n')
                        time.sleep(0.03)
                except OSError:
                    pass
                return
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start + (mode == "wrong")}-{end}/{len(body)}')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Content-Encoding', 'identity')
            self.send_header('ETag', '"' + digest + '"')
            self.end_headers()
            try:
                if mode == 'drop':
                    self.wfile.write(body[start:start + 3])
                    self.wfile.flush()
                elif mode == 'trickle':
                    for byte in body[start:end + 1]:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.03)
                else:
                    self.wfile.write(body[start:end + 1])
            except OSError:
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/artifact', seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('behavior', ['trickle', 'headers_trickle'])
def test_absolute_range_deadline_bounds_continuous_trickle(tmp_path, behavior):
    archive = fixture_zip(tmp_path)
    body = archive.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    token = tmp_path / 'token'
    token.write_text('TEST_TOKEN', encoding='utf-8')
    output = tmp_path / 'result.zip'
    downloader = module('download_qwen_submission_http')
    with range_server(body, digest, lambda start: behavior) as (url, seen):
        started = time.monotonic()
        with pytest.raises(ValueError, match='HTTP_RANGE_DEADLINE'):
            downloader.download(url, token, digest, len(body), output, workers=1,
                                range_bytes=128, timeout=0.25)
        assert time.monotonic() - started < 2
    report = json.loads(output.with_suffix('.zip.status.json').read_text())
    assert report['state'] == 'FAILED'
    if behavior == 'trickle':
        assert report['received_bytes'] > 0
    assert not output.exists()
    assert not output.with_suffix('.zip.download.lock').exists()


def test_first_failure_interrupts_other_active_response(tmp_path):
    archive = fixture_zip(tmp_path)
    body = archive.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    token = tmp_path / 'token'
    token.write_text('TEST_TOKEN', encoding='utf-8')
    output = tmp_path / 'result.zip'
    with range_server(body, digest, lambda start: 'trickle' if start == 0 else 'wrong') as (url, seen):
        started = time.monotonic()
        with pytest.raises(ValueError, match='HTTP_RANGE_IDENTITY_MISMATCH'):
            module('download_qwen_submission_http').download(
                url, token, digest, len(body), output, workers=2, range_bytes=128, timeout=10)
        assert time.monotonic() - started < 2
    assert not output.exists()


@pytest.mark.parametrize('tamper_partial', [False, True])
def test_resume_rehashes_completed_chunks_and_downloads_only_missing(tmp_path, tamper_partial):
    archive = fixture_zip(tmp_path)
    body = archive.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    token = tmp_path / 'token'
    token.write_text('TEST_TOKEN', encoding='utf-8')
    output = tmp_path / 'result.zip'
    downloader = module('download_qwen_submission_http')
    dropping = [True]
    with range_server(body, digest, lambda start: 'drop' if dropping[0] and start == 128 else 'ok') as (url, seen):
        with pytest.raises(ValueError, match='HTTP_RANGE_TRUNCATED'):
            downloader.download(url, token, digest, len(body), output, workers=1, range_bytes=128, timeout=3)
        ledger = [json.loads(line) for line in output.with_suffix('.zip.chunks.jsonl').read_text().splitlines()]
        assert any(entry.get('start') == '0' for entry in ledger)
        dropping[0] = False
        seen.clear()
        if tamper_partial:
            with output.with_suffix('.zip.partial').open('r+b') as handle:
                handle.write(b'changed')
            with pytest.raises(ValueError, match='RESUME_CHUNK_HASH_MISMATCH'):
                downloader.download(url, token, digest, len(body), output, workers=1,
                                    range_bytes=128, timeout=3, resume=True)
            assert seen == []
            assert not output.exists()
        else:
            # A hard-kill can leave an incomplete journal record; it is safely
            # removed after recorded chunks are rehashed and then redownloaded.
            with output.with_suffix('.zip.chunks.jsonl').open('ab') as handle:
                handle.write(b'{"start": "128", "bytes":')
            result = downloader.download(url, token, digest, len(body), output, workers=2,
                                         range_bytes=128, timeout=3, resume=True)
            assert result['state'] == 'READY'
            assert 0 not in seen
            assert output.read_bytes() == body


def test_non_aligned_segment_boundaries_preserve_exact_zip(tmp_path):
    archive = fixture_zip(tmp_path)
    body = archive.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    token = tmp_path / 'token'
    token.write_text('TEST_TOKEN', encoding='utf-8')
    output = tmp_path / 'segmented.zip'
    with range_server(body, digest, lambda start: 'ok') as (url, seen):
        segments = [dict(artifact_start=start, bytes=length, source_start=start,
                         source_bytes=len(body), url=url, authenticated=True, expected_etag=digest,
                         range_bytes=step) for start, length, step in [(0, 77, 40), (77, len(body)-77, 128)]]
        result = module('download_qwen_submission_http').download(
            url, token, digest, len(body), output, workers=2, range_bytes=128,
            timeout=3, source_segments=segments)
    assert result['state'] == 'READY'
    assert output.read_bytes() == body
    assert 77 in seen


def test_public_mirror_redirect_cannot_forward_private_token():
    import urllib.request
    downloader = module('download_qwen_submission_http')
    handler = downloader.PublicRedirect(['hf.co'])
    request = urllib.request.Request('https://huggingface.co/public', headers={'Authorization': 'Bearer private'})
    with pytest.raises(ValueError, match='PRIVATE_TOKEN_IN_PUBLIC_MIRROR_REQUEST'):
        handler.redirect_request(request, None, 302, 'redirect', {}, 'https://cdn.hf.co/file')
    request = urllib.request.Request('https://huggingface.co/public')
    with pytest.raises(ValueError, match='UNTRUSTED_PUBLIC_MIRROR_REDIRECT'):
        handler.redirect_request(request, None, 302, 'redirect', {}, 'https://hf.co.attacker.invalid/file')


def test_distinct_public_source_offsets_and_auth_preserve_exact_archive(tmp_path, monkeypatch):
    """A mirror starts at byte zero while its ZIP segment starts at byte 77."""
    import io
    from email.message import Message
    import urllib.request
    downloader = module('download_qwen_submission_http')
    archive = fixture_zip(tmp_path)
    body = archive.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    token = tmp_path / 'token'
    token.write_text('TEST_TOKEN', encoding='utf-8')
    original_url = 'http://127.0.0.1:1/artifact'
    mirror_url = 'https://huggingface.co/public'
    begin, end = 77, 333
    mirror_body = body[begin:end]
    observed = []

    class Response(io.BytesIO):
        status = 206

    class Opener:
        def open(self, request, timeout):
            start, stop = map(int, request.get_header('Range')[6:].split('-'))
            public = request.full_url == mirror_url
            source = mirror_body if public else body
            expected_auth = None if public else 'Bearer TEST_TOKEN'
            assert request.get_header('Authorization') == expected_auth
            assert request.get_header('Accept-encoding') == 'identity'
            observed.append((public, start, stop))
            result = Response(source[start:stop + 1])
            result.headers = Message()
            result.headers['Content-Range'] = f'bytes {start}-{stop}/{len(source)}'
            result.headers['Content-Length'] = str(stop - start + 1)
            result.headers['Content-Encoding'] = 'identity'
            return result

    monkeypatch.setattr(downloader.urllib.request, 'build_opener', lambda *args: Opener())
    segments = [
        dict(artifact_start=0, bytes=begin, source_start=0, source_bytes=len(body),
             url=original_url, authenticated=True, range_bytes=40),
        dict(artifact_start=begin, bytes=end - begin, source_start=0, source_bytes=len(mirror_body),
             url=mirror_url, authenticated=False, redirect_hosts=['hf.co'], range_bytes=91),
        dict(artifact_start=end, bytes=len(body) - end, source_start=end, source_bytes=len(body),
             url=original_url, authenticated=True, range_bytes=128),
    ]
    output = tmp_path / 'combined.zip'
    result = downloader.download(original_url, token, digest, len(body), output, workers=3,
                                 timeout=3, source_segments=segments)
    assert result['state'] == 'READY'
    assert output.read_bytes() == body
    assert sorted((start, stop) for public, start, stop in observed if public) == [
        (0, 90), (91, 181), (182, 255)]
    assert any(not public and start == end for public, start, stop in observed)

    request = urllib.request.Request(mirror_url, headers={'Range': 'bytes=0-90', 'Accept-Encoding': 'identity'})
    redirected = downloader.PublicRedirect(['hf.co']).redirect_request(
        request, None, 302, 'redirect', {}, 'https://cdn.hf.co/file?signed=yes')
    assert redirected.get_header('Range') == 'bytes=0-90'
    assert redirected.get_header('Accept-encoding') == 'identity'
    assert not redirected.has_header('Authorization')


def retry_fixture(tmp_path, monkeypatch, behavior):
    """Mock transport only; publication still runs the actual ZIP verifier."""
    import io
    from email.message import Message
    downloader = module('download_qwen_submission_http')
    body = fixture_zip(tmp_path).read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    token = tmp_path / 'retry_token'
    token.write_text('TEST_TOKEN', encoding='utf-8')
    requests = []

    class Response(io.BytesIO):
        status = 206

        def read1(self, size):
            return super().read1(size)

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            answer = behavior(len(requests), body)
            if isinstance(answer, BaseException):
                raise answer
            result = Response(answer)
            result.headers = Message()
            result.headers['Content-Range'] = f'bytes 0-{len(body) - 1}/{len(body)}'
            result.headers['Content-Length'] = str(len(body))
            result.headers['Content-Encoding'] = 'identity'
            return result

    monkeypatch.setattr(downloader.urllib.request, 'build_opener', lambda *args: Opener())
    args = ('http://127.0.0.1:1/artifact', token, digest, len(body), tmp_path / 'retry.zip')
    return downloader, args, requests


@pytest.mark.parametrize('mode', ['502', 'drop', 'timeout'])
def test_only_transient_transport_failures_get_bounded_retry(tmp_path, monkeypatch, mode):
    import urllib.error
    def behavior(attempt, body):
        if attempt == 1:
            if mode == '502':
                return urllib.error.HTTPError('http://127.0.0.1:1/artifact', 502, 'upstream', {}, None)
            if mode == 'drop':
                return body[:3]
            return TimeoutError('network read timed out')
        return body
    downloader, args, requests = retry_fixture(tmp_path, monkeypatch, behavior)
    result = downloader.download(*args, workers=1, range_bytes=65536, timeout=3,
                                 max_range_attempts=3, max_retry_calls=2)
    assert result['state'] == 'READY'
    assert result['retry_calls'] == 1
    assert len(requests) == 2


def test_retry_budget_is_durable_across_resume(tmp_path, monkeypatch):
    downloader, args, requests = retry_fixture(tmp_path, monkeypatch, lambda attempt, body: TimeoutError('transient'))
    with pytest.raises(TimeoutError):
        downloader.download(*args, workers=1, range_bytes=65536, timeout=3,
                            max_range_attempts=3, max_retry_calls=1)
    assert len(requests) == 2
    ledger = [json.loads(line) for line in args[-1].with_suffix('.zip.chunks.jsonl').read_text().splitlines()]
    assert sum(entry.get('kind') == 'retry' for entry in ledger) == 1
    before = len(requests)
    with pytest.raises(ValueError, match='RETRY_BUDGET_EXHAUSTED'):
        downloader.download(*args, workers=1, range_bytes=65536, timeout=3,
                            max_range_attempts=3, max_retry_calls=1, resume=True)
    assert len(requests) == before


@pytest.mark.parametrize('status', [401, 403, 429])
def test_auth_and_rate_limit_failures_are_not_retried(tmp_path, monkeypatch, status):
    import urllib.error
    downloader, args, requests = retry_fixture(tmp_path, monkeypatch, lambda attempt, body:
        urllib.error.HTTPError('http://127.0.0.1:1/artifact', status, 'unavailable', {}, None))
    with pytest.raises(urllib.error.HTTPError):
        downloader.download(*args, workers=1, range_bytes=65536, timeout=3,
                            max_range_attempts=3, max_retry_calls=2)
    assert len(requests) == 1
    assert not args[-1].exists()
    report = json.loads(args[-1].with_suffix('.zip.status.json').read_text())
    assert report['retry_calls'] == 0


def test_corrupt_file_bytes_do_not_trigger_transport_retry(tmp_path, monkeypatch):
    downloader, args, requests = retry_fixture(tmp_path, monkeypatch,
        lambda attempt, body: b'X' + body[1:])
    with pytest.raises(ValueError, match='AUTHORITATIVE_ARCHIVE_HASH_MISMATCH'):
        downloader.download(*args, workers=1, range_bytes=65536, timeout=3,
                            max_range_attempts=3, max_retry_calls=2)
    assert len(requests) == 1
    assert not args[-1].exists()


def test_invalid_range_identity_is_not_retried(tmp_path):
    body = fixture_zip(tmp_path).read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    token = tmp_path / 'range_token'
    token.write_text('TEST_TOKEN', encoding='utf-8')
    with range_server(body, digest, lambda start: 'wrong') as (url, seen):
        with pytest.raises(ValueError, match='HTTP_RANGE_IDENTITY_MISMATCH'):
            module('download_qwen_submission_http').download(
                url, token, digest, len(body), tmp_path / 'invalid.zip', workers=1,
                range_bytes=65536, timeout=3, max_range_attempts=3, max_retry_calls=2)
        assert seen == [0]


def test_local_disk_failure_does_not_retry_network_transfer(tmp_path, monkeypatch):
    downloader, args, requests = retry_fixture(tmp_path, monkeypatch, lambda attempt, body: body)
    original_fsync = downloader.os.fsync
    failed = []
    def fail_after_transport(fd):
        # All startup syncs occur before the first request. Fail the first
        # actual local durability operation after a complete body was received.
        if requests and not failed:
            failed.append(True)
            raise OSError('simulated disk durability failure')
        return original_fsync(fd)
    monkeypatch.setattr(downloader.os, 'fsync', fail_after_transport)
    with pytest.raises(OSError, match='simulated disk durability failure'):
        downloader.download(*args, workers=1, range_bytes=65536, timeout=3,
                            max_range_attempts=3, max_retry_calls=2)
    assert len(requests) == 1
    assert not args[-1].exists()
