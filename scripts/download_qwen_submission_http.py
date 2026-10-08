"""Operator-only parallel HTTP range download; never part of the submission.

The private token is read from a file. Artifact size and SHA256 must come from
an authoritative independent receipt. No retries or resume are performed.
"""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

RANGE_BYTES = 32 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ValueError('HTTP_REDIRECT_FORBIDDEN')


def _verify_archive(path):
    spec = importlib.util.spec_from_file_location(
        '_guardian_submission_zip_verifier', Path(__file__).with_name('download_qwen_submission.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_archive(path)


def download(url, token_file, expected_sha256, expected_size, output, *,
             workers=8, range_bytes=RANGE_BYTES, timeout=60):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('INVALID_ARTIFACT_URL')
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('INVALID_EXPECTED_SHA256')
    if type(expected_size) is not int or not 0 < expected_size < 40_000_000_000:
        raise ValueError('INVALID_EXPECTED_SIZE')
    if not 1 <= workers <= 8 or not 1 <= range_bytes <= RANGE_BYTES or not 0 < timeout <= 120:
        raise ValueError('INVALID_DOWNLOAD_LIMITS')
    token = Path(token_file).read_text(encoding='utf-8').strip()
    if not token or len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('INVALID_TOKEN_FILE')
    output = Path(output)
    partial = output.with_suffix(output.suffix + '.partial')
    status = output.with_suffix(output.suffix + '.status.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    if any(p.exists() for p in (output, partial, status)):
        raise ValueError('DOWNLOAD_PATH_ALREADY_EXISTS')
    started = time.monotonic()
    lock = threading.Lock()
    completed_bytes = 0
    stopped = threading.Event()

    def save(state, **extra):
        with lock:
            size = completed_bytes
        body = dict(state=state, pid=os.getpid(), bytes=size, expected_bytes=expected_size,
                    elapsed_seconds=time.monotonic() - started, **extra)
        temporary = status.with_suffix(status.suffix + '.new')
        temporary.write_text(json.dumps(body, indent=2), encoding='utf-8')
        os.replace(temporary, status)

    # Reserve both paths exclusively; an old or concurrently running download
    # must not be mistaken for this transfer.
    with status.open('x', encoding='utf-8') as handle:
        json.dump(dict(state='STARTING', pid=os.getpid()), handle)
    try:
        with partial.open('xb') as target:
            save('ALLOCATING_LOCAL_FILE')
            target.truncate(expected_size)

            def fetch(start):
                nonlocal completed_bytes
                if stopped.is_set():
                    return
                end = min(start + range_bytes, expected_size) - 1
                length = end - start + 1
                request = urllib.request.Request(url, headers={
                    'Authorization': 'Bearer ' + token,
                    'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity'})
                # Per-task opener: no shared mutable urllib state and no proxy.
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                with opener.open(request, timeout=timeout) as response:
                    if response.status != 206:
                        raise ValueError('HTTP_RANGE_STATUS_NOT_206')
                    ranges = response.headers.get_all('Content-Range', [])
                    lengths = response.headers.get_all('Content-Length', [])
                    if ranges != [f'bytes {start}-{end}/{expected_size}'] or lengths != [str(length)]:
                        raise ValueError('HTTP_RANGE_IDENTITY_MISMATCH')
                    encodings = response.headers.get_all('Content-Encoding', [])
                    if encodings not in ([], ['identity']) or response.headers.get_all('Transfer-Encoding', []):
                        raise ValueError('HTTP_ENCODING_FORBIDDEN')
                    etags = response.headers.get_all('ETag', [])
                    if etags and etags not in ([expected_sha256], ['"' + expected_sha256 + '"']):
                        raise ValueError('HTTP_ARTIFACT_ETAG_MISMATCH')
                    data = response.read(length)
                    if len(data) != length:
                        raise ValueError('HTTP_RANGE_TRUNCATED')
                if stopped.is_set():
                    return
                with lock:
                    target.seek(start)
                    if target.write(data) != length:
                        raise OSError('PARTIAL_FILE_WRITE')
                    completed_bytes += length

            save('DOWNLOADING')
            with ThreadPoolExecutor(max_workers=workers) as executor:
                pending = {executor.submit(fetch, start) for start in range(0, expected_size, range_bytes)}
                try:
                    last = time.monotonic()
                    while pending:
                        done, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                        for future in done:
                            future.result()
                        if time.monotonic() - last >= 10:
                            save('DOWNLOADING')
                            last = time.monotonic()
                except BaseException:
                    stopped.set()
                    for future in pending:
                        future.cancel()
                    raise
            if completed_bytes != expected_size:
                raise ValueError('INCOMPLETE_RANGE_COVERAGE')
            target.flush()
            os.fsync(target.fileno())
        save('VERIFYING_LOCAL_ARCHIVE')
        digest = hashlib.sha256()
        with partial.open('rb') as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
        if partial.stat().st_size != expected_size or digest.hexdigest() != expected_sha256:
            raise ValueError('AUTHORITATIVE_ARCHIVE_HASH_MISMATCH')
        manifest = _verify_archive(partial)
        # Publish atomically without overwriting a concurrently created output.
        if os.name == 'nt':
            partial.rename(output)
        else:
            os.link(partial, output)
            partial.unlink()
        save('READY', output=str(output.resolve()), zip_sha256=expected_sha256,
             model_sha256=manifest['model_sha256'], artifact_commit=manifest['commit'])
        return json.loads(status.read_text(encoding='utf-8'))
    except BaseException as error:
        stopped.set()
        # Never include request headers, token or untrusted response bodies.
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        save('FAILED', error=detail)
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--token-file', type=Path, required=True)
    ap.add_argument('--expected-sha256', required=True)
    ap.add_argument('--expected-size', type=int, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--range-bytes', type=int, default=RANGE_BYTES)
    ap.add_argument('--timeout', type=float, default=60)
    args = ap.parse_args()
    print(json.dumps(download(args.url, args.token_file, args.expected_sha256,
                              args.expected_size, args.output, workers=args.workers,
                              range_bytes=args.range_bytes, timeout=args.timeout), indent=2))


if __name__ == '__main__':
    main()
