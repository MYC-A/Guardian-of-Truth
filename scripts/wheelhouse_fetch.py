"""Fetch every wheel of a pip --report into a persistent wheelhouse with parallel HTTP/1.1 ranges.

Integrity: each range must answer 206 with the exact Content-Range and length;
each finished file must match the sha256 recorded in the pip report. TLS
certificate and hostname validation are always on; with --connect-ip the TCP
connection goes to a chosen CDN address but SNI/Host/cert remain the original
hostname (no /etc/hosts change, no TLS bypass). Resumable: finished chunks are
recorded beside the .part file.

    python3 wheelhouse_fetch.py --report dep_report.json --out wheelhouse --workers 16 \
        --connect-ip files.pythonhosted.org=151.101.128.223,151.101.0.223
"""
import argparse
import hashlib
import http.client
import itertools
import json
import os
from pathlib import Path
import queue
import re
import socket
import ssl
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

CHUNK = 8 * 1024 * 1024
CONTEXT = ssl.create_default_context()


class Pinned(http.client.HTTPSConnection):
    def __init__(self, host, ip=None, timeout=60):
        super().__init__(host, 443, timeout=timeout, context=CONTEXT)
        self.ip = ip

    def connect(self):
        sock = socket.create_connection((self.ip or self.host, 443), self.timeout)
        self.sock = CONTEXT.wrap_socket(sock, server_hostname=self.host)  # SNI + cert check on hostname


class Pool:
    def __init__(self, pins):
        self.pins = {h: itertools.cycle(ips) for h, ips in pins.items()}
        self.local = threading.local()
        self.lock = threading.Lock()

    def conn(self, host):
        cache = getattr(self.local, 'c', None)
        if cache is None:
            cache = self.local.c = {}
        if host not in cache:
            with self.lock:
                ip = next(self.pins[host]) if host in self.pins else None
            cache[host] = Pinned(host, ip)
        return cache[host]

    def drop(self, host):
        cache = getattr(self.local, 'c', {})
        c = cache.pop(host, None)
        if c is not None:
            c.close()


def request(pool, url, headers, method='GET'):
    parts = urlsplit(url)
    for attempt in range(6):
        conn = pool.conn(parts.netloc)
        try:
            conn.request(method, parts.path + ('?' + parts.query if parts.query else ''),
                         headers=dict(headers, Host=parts.netloc, Connection='keep-alive',
                                      **{'User-Agent': 'guardian-wheelhouse/1', 'Accept-Encoding': 'identity'}))
            response = conn.getresponse()
            if response.status != 206:
                pool.drop(parts.netloc)  # never read a possibly full-size non-range body
                return response, b''
            length = int(response.getheader('Content-Length') or -1)
            if length > CHUNK:
                pool.drop(parts.netloc)
                return response, b''
            body = response.read()
            return response, body
        except ssl.SSLCertVerificationError:
            raise
        except (OSError, http.client.HTTPException):
            pool.drop(parts.netloc)
            time.sleep(min(2 ** attempt, 20))
    raise RuntimeError('REQUEST_FAILED ' + url)


def size_of(pool, url):
    response, _ = request(pool, url, {'Range': 'bytes=0-0'})
    if response.status != 206:
        raise RuntimeError(f'NO_RANGE_SUPPORT {response.status} {url}')
    match = re.fullmatch(r'bytes 0-0/(\d+)', response.getheader('Content-Range') or '')
    if not match:
        raise RuntimeError('BAD_CONTENT_RANGE ' + url)
    return int(match.group(1))


def file_sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--connect-ip', action='append', default=[], help='host=ip1,ip2')
    parser.add_argument('--progress', default=None)
    options = parser.parse_args()
    pins = {}
    for item in options.connect_ip:
        host, ips = item.split('=', 1)
        pins[host] = [ip for ip in ips.split(',') if ip]
    pool = Pool(pins)
    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'FETCH_SUMMARY.json').unlink(missing_ok=True)
    try:
        run(options, pool, out)
    except (Exception, KeyboardInterrupt) as error:
        (out / 'FETCH_SUMMARY.json').write_text(json.dumps(dict(status='FAILED', fatal=f'{type(error).__name__}: {error}')))
        raise


def run(options, pool, out):
    report = json.loads(Path(options.report).read_text())
    files = []
    for item in report['install']:
        info = item['download_info']
        sha = ((info.get('archive_info') or {}).get('hashes') or {}).get('sha256')
        name = unquote(urlsplit(info['url']).path.rsplit('/', 1)[1])
        if not sha or not re.fullmatch(r'[0-9a-f]{64}', sha) or not name.endswith('.whl') \
                or name != Path(name).name or '/' in name or '\\' in name:
            raise ValueError('REPORT_ENTRY_NOT_SHA256_WHEEL ' + name)
        files.append(dict(url=info['url'], sha256=sha, name=name))
    todo = []
    for f in files:
        final = out / f['name']
        if final.exists():
            if file_sha(final) == f['sha256']:
                f['status'] = 'CACHED'
                continue
            final.unlink()
        f['size'] = size_of(pool, f['url'])
        part = out / (f['name'] + '.part')
        done_path = out / (f['name'] + '.chunks.json')
        try:
            meta = json.loads(done_path.read_text()) if done_path.exists() and part.exists() else {}
        except ValueError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        ok = meta.get('chunk') == CHUNK and meta.get('sha256') == f['sha256'] and meta.get('size') == f['size']
        done = set(meta.get('done', [])) if ok else set()
        if not part.exists() or part.stat().st_size != f['size']:
            with part.open('wb') as stream:
                stream.truncate(f['size'])
            done = set()
        f.update(part=part, done_path=done_path, done=done, lock=threading.Lock(),
                 chunks=[(s, min(s + CHUNK, f['size']) - 1) for s in range(0, f['size'], CHUNK)])
        f['remaining'] = sum(1 for c in f['chunks'] if c[0] not in done)
        todo.append(f)
    total = sum(f['size'] for f in todo)
    print(json.dumps(dict(files=len(files), to_fetch=len(todo), bytes=total)), flush=True)
    jobs = queue.Queue()
    # Largest files first; chunks of one file are independent jobs.
    for f in sorted(todo, key=lambda f: -f['size']):
        if f['remaining'] == 0:
            jobs.put((f, None))
        for chunk in f['chunks']:
            if chunk[0] not in f['done']:
                jobs.put((f, chunk))
    fetched = [0]
    errors = []
    counter = threading.Lock()

    def finish(f):
        if file_sha(f['part']) != f['sha256']:
            f['part'].unlink()
            f['done_path'].unlink(missing_ok=True)
            raise RuntimeError('SHA256_MISMATCH ' + f['name'])
        os.replace(f['part'], out / f['name'])
        f['done_path'].unlink(missing_ok=True)
        f['status'] = 'FETCHED'

    def worker():
        while True:
            try:
                f, chunk = jobs.get_nowait()
            except queue.Empty:
                return
            try:
                if chunk is not None:
                    start, end = chunk
                    for attempt in range(5):
                        response, body = request(pool, f['url'], {'Range': f'bytes={start}-{end}'})
                        expected = f'bytes {start}-{end}/{f["size"]}'
                        if response.status == 206 and response.getheader('Content-Range') == expected \
                                and len(body) == end - start + 1:
                            break
                        pool.drop(urlsplit(f['url']).netloc)
                        time.sleep(2 ** attempt)
                    else:
                        raise RuntimeError(f'RANGE_INVALID {f["name"]} {start}-{end}')
                    fd = os.open(f['part'], os.O_WRONLY)
                    try:
                        if os.pwrite(fd, body, start) != len(body):
                            raise OSError('SHORT_WRITE')
                    finally:
                        os.close(fd)
                    with counter:
                        fetched[0] += len(body)
                with f['lock']:
                    if chunk is not None:
                        f['done'].add(chunk[0])
                        f['remaining'] -= 1
                        tmp = f['done_path'].with_suffix('.tmp')
                        tmp.write_text(json.dumps(dict(chunk=CHUNK, size=f['size'], sha256=f['sha256'],
                                                       done=sorted(f['done']))))
                        os.replace(tmp, f['done_path'])
                    last = f['remaining'] == 0 and f.get('status') is None
                    if last:
                        f['status'] = 'VERIFYING'
                if last:
                    finish(f)
            except Exception as error:
                errors.append(f'{type(error).__name__}: {error}')
            finally:
                jobs.task_done()

    started = time.monotonic()
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(options.workers)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(10)
        rate = fetched[0] / max(time.monotonic() - started, 1e-6)
        line = dict(fetched=fetched[0], total=total, rate_Bps=round(rate), errors=len(errors),
                    elapsed=round(time.monotonic() - started))
        print(json.dumps(line), flush=True)
        if options.progress:
            Path(options.progress).write_text(json.dumps(line))
    bad = [f['name'] for f in files if f.get('status') not in ('CACHED', 'FETCHED')]
    summary = dict(status='COMPLETE' if not bad and not errors else 'FAILED', files=len(files),
                   fetched_bytes=fetched[0], seconds=round(time.monotonic() - started, 1),
                   errors=errors[:50], incomplete=bad,
                   wheels=[dict(name=f['name'], sha256=f['sha256']) for f in files])
    (out / 'FETCH_SUMMARY.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in ('status', 'files', 'fetched_bytes', 'seconds', 'incomplete')}))
    sys.exit(0 if summary['status'] == 'COMPLETE' else 1)


if __name__ == '__main__':
    main()
