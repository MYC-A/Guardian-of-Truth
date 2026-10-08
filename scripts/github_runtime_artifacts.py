"""Inspect CPU build runs and fetch a successful exact-commit runtime artifact.

Uses the operator's existing Git credential in memory. Credentials are only
sent to api.github.com, never to the artifact's signed storage redirect.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def credential():
    result = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                            text=True, capture_output=True, timeout=15)
    if result.returncode:
        raise RuntimeError('GITHUB_CREDENTIAL_UNAVAILABLE')
    data = dict(s.split('=', 1) for s in result.stdout.splitlines() if '=' in s)
    if not data.get('password'):
        raise RuntimeError('GITHUB_CREDENTIAL_UNAVAILABLE')
    return data['password']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default='MYC-A/Guardian-of-Truth')
    ap.add_argument('--sha', required=True)
    ap.add_argument('--run', type=int)
    ap.add_argument('--directory', type=Path)
    a = ap.parse_args()
    token = credential()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def api(path):
        url = 'https://api.github.com/repos/' + a.repo + '/' + path
        req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
                                                   'Accept': 'application/vnd.github+json',
                                                   'User-Agent': 'Guardian-runtime-builder'})
        with opener.open(req, timeout=30) as response:
            return json.load(response)
    if not a.run:
        runs = api('actions/runs?' + urllib.parse.urlencode(dict(head_sha=a.sha, per_page=20)))['workflow_runs']
        print(json.dumps([{k: r.get(k) for k in ('id', 'name', 'head_sha', 'status', 'conclusion', 'html_url', 'created_at')}
                          for r in runs], indent=2))
        return
    run = api(f'actions/runs/{a.run}')
    if run['head_sha'] != a.sha or run['conclusion'] != 'success' or run['status'] != 'completed':
        raise ValueError('SUCCESSFUL_EXACT_COMMIT_RUN_REQUIRED')
    artifacts = api(f'actions/runs/{a.run}/artifacts')['artifacts']
    artifacts = [x for x in artifacts if x['name'] == 'guardian-qwen-a100-runtime-' + a.sha and not x['expired']]
    if len(artifacts) != 1 or not a.directory:
        raise ValueError('ONE_RUNTIME_ARTIFACT_AND_LOCAL_DIRECTORY_REQUIRED')
    item = artifacts[0]
    url = 'https://api.github.com/repos/' + a.repo + f'/actions/artifacts/{item["id"]}/zip'
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
                                               'User-Agent': 'Guardian-runtime-builder'})
    try:
        response = opener.open(req, timeout=30)
        location = None
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 303, 307, 308):
            raise RuntimeError('GITHUB_ARTIFACT_REQUEST_FAILED') from None
        location = error.headers.get('Location')
        error.close()
        parsed = urllib.parse.urlsplit(location or '')
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise ValueError('INVALID_ARTIFACT_REDIRECT')
        # A fresh request carries no credential into the signed public URL.
        response = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(location, timeout=60)
    a.directory.mkdir(parents=True, exist_ok=True)
    output = a.directory / (item['name'] + '.zip')
    partial = output.with_suffix('.zip.partial')
    if output.exists() or partial.exists():
        response.close()
        raise ValueError('ARTIFACT_DOWNLOAD_PATH_ALREADY_EXISTS')
    h = hashlib.sha256()
    count = 0
    with response, partial.open('xb') as target:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
            h.update(chunk)
            count += len(chunk)
        target.flush()
        os.fsync(target.fileno())
    expected = item.get('digest')
    if expected and expected != 'sha256:' + h.hexdigest():
        raise ValueError('GITHUB_ARTIFACT_DIGEST_MISMATCH')
    if count != item['size_in_bytes']:
        raise ValueError('GITHUB_ARTIFACT_SIZE_MISMATCH')
    os.replace(partial, output)
    receipt = dict(run_id=a.run, head_sha=a.sha, artifact_id=item['id'], name=item['name'],
                   bytes=count, sha256=h.hexdigest(), path=str(output.resolve()))
    output.with_suffix('.zip.receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
