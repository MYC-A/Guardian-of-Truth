"""Operator-only parallel HTTP range download; never part of the submission.

The private token is read from a file. Artifact size and SHA256 must come from
an authoritative independent receipt. Retries are opt-in and durably bounded. Explicit resume
uses a durable, independently rehashed chunk ledger; old partials without one
cannot be adopted.
"""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

RANGE_BYTES = 1024 * 1024
MAX_RANGE_BYTES = 32 * 1024 * 1024
LEDGER_VERSION = 'http-ranges-3'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ValueError('HTTP_REDIRECT_FORBIDDEN')


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    """Public mirror redirects cannot carry the private artifact credential."""
    def __init__(self, hosts):
        self.hosts = tuple(hosts)
    def redirect_request(self, request, fp, code, message, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or parsed.username or parsed.password
                or not any(host == h or host.endswith('.' + h) for h in self.hosts)):
            raise ValueError('UNTRUSTED_PUBLIC_MIRROR_REDIRECT')
        if request.has_header('Authorization'):
            raise ValueError('PRIVATE_TOKEN_IN_PUBLIC_MIRROR_REQUEST')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def transfer_plan(url, expected_size, expected_sha256, range_bytes, source_segments=None):
    segments = source_segments or [dict(artifact_start=0, bytes=expected_size, source_start=0,
                                       source_bytes=expected_size, url=url, authenticated=True,
                                       expected_etag=expected_sha256)]
    chunks = {}
    cursor = 0
    for segment in segments:
        if (any(type(segment.get(k)) is not int for k in ('artifact_start', 'bytes', 'source_start', 'source_bytes'))
                or segment['artifact_start'] != cursor or segment['bytes'] < 1
                or segment['source_start'] < 0 or segment['source_start'] + segment['bytes'] > segment['source_bytes']
                or type(segment.get('authenticated')) is not bool):
            raise ValueError('INVALID_OR_INCOMPLETE_TRANSFER_SEGMENTS')
        parsed = urllib.parse.urlsplit(segment['url'])
        if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
            raise ValueError('INVALID_SEGMENT_URL')
        if segment['authenticated']:
            if segment['url'] != url or segment.get('redirect_hosts'):
                raise ValueError('PRIVATE_TOKEN_SEGMENT_MUST_USE_ORIGINAL_ENDPOINT')
        elif parsed.scheme != 'https':
            raise ValueError('PUBLIC_MIRROR_REQUIRES_HTTPS')
        step = segment.get('range_bytes', range_bytes)
        if type(step) is not int or not 1 <= step <= MAX_RANGE_BYTES:
            raise ValueError('INVALID_SEGMENT_RANGE_SIZE')
        for offset in range(0, segment['bytes'], step):
            chunks[cursor + offset] = dict(length=min(step, segment['bytes'] - offset),
                                          source_start=segment['source_start'] + offset, segment=segment)
        cursor += segment['bytes']
    if cursor != expected_size:
        raise ValueError('INVALID_OR_INCOMPLETE_TRANSFER_SEGMENTS')
    return segments, chunks


def _verify_archive(path):
    spec = importlib.util.spec_from_file_location(
        '_guardian_submission_zip_verifier', Path(__file__).with_name('download_qwen_submission.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_archive(path)


def _atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.new')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _sparse(target):
    if os.name != 'nt':
        return 'POSIX_TRUNCATE'
    import ctypes
    from ctypes import wintypes
    import msvcrt
    control = ctypes.WinDLL('kernel32', use_last_error=True).DeviceIoControl
    control.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    control.restype = wintypes.BOOL
    returned = wintypes.DWORD()
    ok = control(msvcrt.get_osfhandle(target.fileno()), 0x900C4, None, 0, None, 0,
                 ctypes.byref(returned), None)  # FSCTL_SET_SPARSE
    return 'WINDOWS_SPARSE' if ok else 'WINDOWS_ALLOCATION_FALLBACK'


def _resize(target, size):
    # CPython's Windows truncate uses CRT _chsize_s, which can manually write
    # gigabytes of zeroes even after FSCTL_SET_SPARSE. Set the native file end
    # directly; on a fresh sparse NTFS file, the unfilled regions remain holes.
    if os.name != 'nt':
        target.truncate(size)
        return
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    move = kernel.SetFilePointerEx
    move.argtypes = [wintypes.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
    move.restype = wintypes.BOOL
    end = kernel.SetEndOfFile
    end.argtypes = [wintypes.HANDLE]
    end.restype = wintypes.BOOL
    target.flush()
    native = msvcrt.get_osfhandle(target.fileno())
    if not move(native, size, None, 0) or not end(native):
        raise ctypes.WinError(ctypes.get_last_error())
    target.seek(0)


def download(url, token_file, expected_sha256, expected_size, output, *,
             workers=8, range_bytes=RANGE_BYTES, timeout=60, resume=False, source_segments=None,
             max_range_attempts=1, max_retry_calls=0):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('INVALID_ARTIFACT_URL')
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('INVALID_EXPECTED_SHA256')
    if type(expected_size) is not int or not 0 < expected_size < 40_000_000_000:
        raise ValueError('INVALID_EXPECTED_SIZE')
    if not 1 <= workers <= 8 or not 1 <= range_bytes <= MAX_RANGE_BYTES or not 0 < timeout <= 120:
        raise ValueError('INVALID_DOWNLOAD_LIMITS')
    if not 1 <= max_range_attempts <= 3 or not 0 <= max_retry_calls <= 256:
        raise ValueError('INVALID_RETRY_LIMITS')
    segments, chunks = transfer_plan(url, expected_size, expected_sha256, range_bytes, source_segments)
    token = Path(token_file).read_text(encoding='utf-8').strip()
    if not token or len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('INVALID_TOKEN_FILE')
    output = Path(output)
    partial = output.with_suffix(output.suffix + '.partial')
    status = output.with_suffix(output.suffix + '.status.json')
    ledger_path = output.with_suffix(output.suffix + '.chunks.jsonl')
    ownership = output.with_suffix(output.suffix + '.download.lock')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or (not resume and any(p.exists() for p in (partial, status, ledger_path))):
        raise ValueError('DOWNLOAD_PATH_ALREADY_EXISTS')
    identity = dict(version=LEDGER_VERSION, url_sha256=hashlib.sha256(url.encode()).hexdigest(),
                    output=str(output.resolve()), expected_bytes=expected_size,
                    expected_sha256=expected_sha256, range_bytes=range_bytes,
                    sources_sha256=hashlib.sha256(json.dumps(segments, sort_keys=True).encode()).hexdigest())
    if resume:
        if not partial.exists() or not ledger_path.exists():
            raise ValueError('RESUME_REQUIRES_PARTIAL_AND_LEDGER')
        raw_ledger = ledger_path.read_bytes()
        lines = raw_ledger.splitlines(keepends=True)
        if not lines or not lines[0].endswith(b'\n'):
            raise ValueError('RESUME_IDENTITY_MISMATCH')
        header = json.loads(lines[0])
        ledger = dict(identity=header.get('identity'), chunks={}, retries={})
        durable_length = len(lines[0])
        for line in lines[1:]:
            if not line.endswith(b'\n'):
                break  # A crash before durable record completion: redownload.
            entry = json.loads(line)
            key = entry.pop('start')
            if entry.get('kind') == 'retry':
                if key not in {str(x) for x in chunks} or entry.get('error') not in ('TimeoutError', 'ConnectionError', 'OSError', 'URLError', 'HTTP_RANGE_TRUNCATED', 'HTTP_RANGE_DEADLINE', 'HTTP_502', 'HTTP_503', 'HTTP_504'):
                    raise ValueError('RESUME_RETRY_RECORD_INVALID')
                ledger['retries'][key] = ledger['retries'].get(key, 0) + 1
                durable_length += len(line)
                continue
            if key in ledger['chunks']:
                raise ValueError('RESUME_DUPLICATE_CHUNK_RECORD')
            ledger['chunks'][key] = entry
            durable_length += len(line)
        if ledger.get('identity') != identity or partial.stat().st_size != expected_size:
            raise ValueError('RESUME_IDENTITY_MISMATCH')
    else:
        ledger = dict(identity=identity, chunks={}, retries={})
    # Exclusive ownership is released on orderly failure. After a hard kill the
    # operator must check the recorded PID before removing a stale lock.
    with ownership.open('x', encoding='utf-8') as handle:
        json.dump(dict(pid=os.getpid(), identity=identity), handle)
    started = time.monotonic()
    lock = threading.Lock()
    completed_bytes = 0
    received_bytes = 0
    stopped = threading.Event()
    network_lock = threading.Lock()
    active_sockets = set()
    active_responses = set()

    def save(state, **extra):
        with lock:
            size, received = completed_bytes, received_bytes
            server_expected = sum(part['length'] for part in chunks.values() if part['segment']['authenticated'])
            server_completed = sum(metadata['bytes'] for start, metadata in ledger['chunks'].items()
                                   if chunks[int(start)]['segment']['authenticated'])
        body = dict(state=state, pid=os.getpid(), bytes=size, expected_bytes=expected_size,
                    received_bytes=received,
                    server_bytes=server_completed, expected_server_bytes=server_expected,
                    server_sources_complete=server_completed == server_expected,
                    retry_calls=sum(ledger['retries'].values()), max_retry_calls=max_retry_calls,
                    elapsed_seconds=time.monotonic() - started, **extra)
        _atomic_json(status, body)

    def shutdown(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def abort_network():
        with network_lock:
            sockets, responses = list(active_sockets), list(active_responses)
        for sock in sockets:
            shutdown(sock)
        for response in responses:
            response.close()

    # Reserve both paths exclusively; an old or concurrently running download
    # must not be mistaken for this transfer.
    try:
        save('STARTING')
        with partial.open('r+b' if resume else 'x+b') as target:
            if not resume:
                allocation = _sparse(target)
                save('ALLOCATING_LOCAL_FILE', allocation=allocation)
                _resize(target, expected_size)
                target.flush()
                os.fsync(target.fileno())
                with ledger_path.open('x', encoding='utf-8', newline='\n') as handle:
                    handle.write(json.dumps(dict(identity=identity)) + '\n')
                    handle.flush()
                    os.fsync(handle.fileno())
            else:
                save('VERIFYING_RESUME_CHUNKS')
                for key, metadata in ledger['chunks'].items():
                    start = int(key)
                    length = chunks.get(start, {}).get('length')
                    if (str(start) != key or length is None
                            or metadata.get('bytes') != length):
                        raise ValueError('RESUME_CHUNK_METADATA_INVALID')
                    target.seek(start)
                    data = target.read(length)
                    if len(data) != length or hashlib.sha256(data).hexdigest() != metadata.get('sha256'):
                        raise ValueError('RESUME_CHUNK_HASH_MISMATCH')
                    completed_bytes += length
                # Remove an incomplete final record only after every recorded
                # chunk has passed independent verification.
                with ledger_path.open('r+b') as handle:
                    handle.truncate(durable_length)
                    handle.flush()
                    os.fsync(handle.fileno())

            def fetch(start):
                nonlocal completed_bytes, received_bytes
                if stopped.is_set():
                    return
                part = chunks[start]
                segment = part['segment']
                length = part['length']
                source_start = part['source_start']
                source_end = source_start + length - 1
                deadline = time.monotonic() + timeout
                timers, owned_sockets = [], []

                def track(sock):
                    with network_lock:
                        active_sockets.add(sock)
                    owned_sockets.append(sock)
                    timer = threading.Timer(max(0, deadline - time.monotonic()), shutdown, args=(sock,))
                    timer.daemon = True
                    timers.append(timer)
                    timer.start()
                    if stopped.is_set():
                        shutdown(sock)

                class Connection(http.client.HTTPConnection):
                    def connect(self):
                        super().connect()
                        track(self.sock)

                class SecureConnection(http.client.HTTPSConnection):
                    def connect(self):
                        super().connect()
                        track(self.sock)

                class HTTP(urllib.request.HTTPHandler):
                    def http_open(self, request):
                        return self.do_open(Connection, request)

                class HTTPS(urllib.request.HTTPSHandler):
                    def https_open(self, request):
                        return self.do_open(SecureConnection, request, context=self._context)
                headers = {'Range': f'bytes={source_start}-{source_end}', 'Accept-Encoding': 'identity'}
                if segment['authenticated']:
                    headers['Authorization'] = 'Bearer ' + token
                mirror_url = segment['url']
                if segment.get('range_query'):
                    mirror_url += ('&' if '?' in mirror_url else '?') + f'guardian_range={source_start}-{source_end}'
                request = urllib.request.Request(mirror_url, headers=headers)
                # Per-task opener: no shared mutable urllib state and no proxy.
                redirects = (PublicRedirect(segment.get('redirect_hosts', [])) if not segment['authenticated'] else NoRedirect())
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), redirects, HTTP(), HTTPS())
                response = None
                network_complete = False
                try:
                    response = opener.open(request, timeout=min(30, timeout))
                    with network_lock:
                        active_responses.add(response)
                    if response.status != 206:
                        raise ValueError('HTTP_RANGE_STATUS_NOT_206')
                    ranges = response.headers.get_all('Content-Range', [])
                    lengths = response.headers.get_all('Content-Length', [])
                    if ranges != [f'bytes {source_start}-{source_end}/{segment["source_bytes"]}'] or lengths != [str(length)]:
                        raise ValueError('HTTP_RANGE_IDENTITY_MISMATCH')
                    encodings = response.headers.get_all('Content-Encoding', [])
                    if encodings not in ([], ['identity']) or response.headers.get_all('Transfer-Encoding', []):
                        raise ValueError('HTTP_ENCODING_FORBIDDEN')
                    etags = response.headers.get_all('ETag', [])
                    etag = segment.get('expected_etag')
                    if etag and etags and etags not in ([etag], ['"' + etag + '"']):
                        raise ValueError('HTTP_ARTIFACT_ETAG_MISMATCH')
                    data = bytearray()
                    while len(data) < length:
                        if stopped.is_set():
                            return
                        if time.monotonic() >= deadline:
                            raise ValueError('HTTP_RANGE_DEADLINE')
                        chunk = response.read1(min(65536, length - len(data)))
                        if not chunk:
                            raise ValueError('HTTP_RANGE_TRUNCATED')
                        data.extend(chunk)
                        with lock:
                            received_bytes += len(chunk)
                    if time.monotonic() >= deadline:
                        raise ValueError('HTTP_RANGE_DEADLINE')
                    if stopped.is_set():
                        return
                    network_complete = True
                    with lock:
                        target.seek(start)
                        if target.write(data) != length:
                            raise OSError('PARTIAL_FILE_WRITE')
                        target.flush()
                        os.fsync(target.fileno())
                        metadata = dict(bytes=length, sha256=hashlib.sha256(data).hexdigest())
                        with ledger_path.open('a', encoding='utf-8', newline='\n') as handle:
                            handle.write(json.dumps(dict(start=str(start), **metadata)) + '\n')
                            handle.flush()
                            os.fsync(handle.fileno())
                        ledger['chunks'][str(start)] = metadata
                        completed_bytes += length
                except Exception as error:
                    if time.monotonic() >= deadline:
                        overdue = ValueError('HTTP_RANGE_DEADLINE')
                        overdue.range_network_failure = not network_complete
                        raise overdue from None
                    if not network_complete:
                        error.range_network_failure = True
                    raise
                finally:
                    for timer in timers:
                        timer.cancel()
                    if response is not None:
                        with network_lock:
                            active_responses.discard(response)
                        response.close()
                    with network_lock:
                        for sock in owned_sockets:
                            active_sockets.discard(sock)
                    for sock in owned_sockets:
                        sock.close()

            def bounded_fetch(start):
                prior = ledger['retries'].get(str(start), 0)
                if prior and (prior >= max_range_attempts - 1
                              or sum(ledger['retries'].values()) >= max_retry_calls):
                    raise ValueError('DURABLE_RANGE_RETRY_BUDGET_EXHAUSTED')
                while True:
                    try:
                        return fetch(start)
                    except Exception as error:
                        if not getattr(error, 'range_network_failure', False):
                            retry_type = None
                        elif isinstance(error, ValueError) and str(error) in ('HTTP_RANGE_TRUNCATED', 'HTTP_RANGE_DEADLINE'):
                            retry_type = str(error)
                        elif isinstance(error, urllib.error.HTTPError):
                            retry_type = 'HTTP_' + str(error.code) if error.code in (502, 503, 504) else None
                        elif isinstance(error, (TimeoutError, ConnectionError, OSError)):
                            retry_type = type(error).__name__
                            if retry_type not in ('TimeoutError', 'ConnectionError', 'OSError', 'URLError'):
                                retry_type = 'OSError'
                        else:
                            retry_type = None
                        with lock:
                            prior = ledger['retries'].get(str(start), 0)
                            if (not retry_type or stopped.is_set() or prior >= max_range_attempts - 1
                                    or sum(ledger['retries'].values()) >= max_retry_calls):
                                raise
                            with ledger_path.open('a', encoding='utf-8', newline='\n') as handle:
                                handle.write(json.dumps(dict(kind='retry', start=str(start), error=retry_type)) + '\n')
                                handle.flush()
                                os.fsync(handle.fileno())
                            ledger['retries'][str(start)] = prior + 1
                        stopped.wait(0.5)

            save('DOWNLOADING')
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Collect the server-only assets first. Public model bytes can
                # continue downloading independently once these are complete.
                ordered = sorted(chunks, key=lambda start: (not chunks[start]['segment']['authenticated'], start))
                pending = {executor.submit(bounded_fetch, start) for start in ordered
                           if str(start) not in ledger['chunks']}
                try:
                    last = time.monotonic()
                    while pending:
                        done, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                        for future in done:
                            future.result()
                        if time.monotonic() - last >= 10:
                            save('DOWNLOADING')
                            last = time.monotonic()
                except BaseException:
                    stopped.set()
                    abort_network()
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
    finally:
        ownership.unlink(missing_ok=True)


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
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--source-segments', type=Path, help='Frozen byte mapping to verified public mirrors; final archive SHA remains mandatory')
    ap.add_argument('--max-range-attempts', type=int, default=1)
    ap.add_argument('--max-retry-calls', type=int, default=0)
    args = ap.parse_args()
    print(json.dumps(download(args.url, args.token_file, args.expected_sha256,
                              args.expected_size, args.output, workers=args.workers,
                              range_bytes=args.range_bytes, timeout=args.timeout,
                              resume=args.resume,
                              max_range_attempts=args.max_range_attempts, max_retry_calls=args.max_retry_calls,
                              source_segments=json.loads(args.source_segments.read_text(encoding='utf-8')) if args.source_segments else None), indent=2))


if __name__ == '__main__':
    main()
