"""Serve one completed public-code/weight artifact with authenticated ranges.

Operator-only tool. No directory listing, arbitrary paths or upload methods.
Token file and the transient RAM archive are never included in the submission.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re


def make_handler(archive, receipt, token):
    archive, receipt = Path(archive), Path(receipt)
    if len(token) < 24:
        raise ValueError('ARTIFACT_TOKEN_TOO_SHORT')
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args):
            pass  # Headers and credentials must never enter a log.
        def do_HEAD(self):
            self.respond(head=True)
        def do_GET(self):
            self.respond(head=False)
        def respond(self, head):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.send_error(401)
                return
            if self.path not in ('/artifact', '/metadata'):
                self.send_error(404)
                return
            try:
                meta = json.loads(receipt.read_text(encoding='utf-8'))
                if meta['state'] != 'READY_ON_SERVER' or Path(meta['path']).resolve() != archive.resolve():
                    raise ValueError('NOT_READY')
                size = archive.stat().st_size
                digest = meta['sha256']
                if size != meta['bytes'] or not 0 < size < 40_000_000_000 or not re.fullmatch(r'[0-9a-f]{64}', digest):
                    raise ValueError('INVALID_READY_RECEIPT')
            except (OSError, ValueError, KeyError):
                self.send_error(503)
                return
            if self.path == '/metadata':
                body = json.dumps(dict(bytes=size, sha256=digest)).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                if not head:
                    self.wfile.write(body)
                return
            start, end, status = 0, size - 1, 200
            if 'Range' in self.headers:
                match = re.fullmatch(r'bytes=(\d+)-(\d+)', self.headers['Range'])
                if not match:
                    self.send_error(416)
                    return
                start, end = map(int, match.groups())
                if not 0 <= start <= end < size:
                    self.send_error(416)
                    return
                status = 206
            self.send_response(status)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Encoding', 'identity')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('ETag', '"' + digest + '"')
            self.send_header('Content-Length', str(end - start + 1))
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if head:
                return
            try:
                with archive.open('rb') as source:
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        data = source.read(min(1024 * 1024, remaining))
                        if not data:
                            self.close_connection = True
                            return
                        self.wfile.write(data)
                        remaining -= len(data)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', type=Path, required=True)
    ap.add_argument('--receipt', type=Path, required=True)
    ap.add_argument('--token-file', type=Path, required=True)
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--port', type=int, required=True)
    a = ap.parse_args()
    handler = make_handler(a.archive, a.receipt, a.token_file.read_text(encoding='utf-8').strip())
    with ThreadingHTTPServer((a.host, a.port), handler) as server:
        server.daemon_threads = True
        server.serve_forever()


if __name__ == '__main__':
    main()
