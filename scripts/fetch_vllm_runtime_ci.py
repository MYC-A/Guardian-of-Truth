"""Operator-only bounded CI waiter and authenticated runtime artifact fetch."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=int, required=True)
    p.add_argument('--sha', required=True)
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--duration', type=int, default=7200)
    args = p.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('github_operator', Path(__file__).with_name('github_runtime_artifacts.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token = module.credential()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + args.duration

    def status(value):
        (args.directory / 'CI_FETCH_STATUS.json').write_text(json.dumps(value, indent=2), encoding='utf-8')

    def api(path):
        request = urllib.request.Request('https://api.github.com/repos/MYC-A/Guardian-of-Truth/' + path,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'User-Agent': 'Guardian-vllm-runtime-fetch'})
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    try:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('CI_FETCH_DEADLINE')
            run = api(f'actions/runs/{args.run}')
            if run['head_sha'] != args.sha:
                raise ValueError('EXACT_CI_SOURCE_REQUIRED')
            status(dict(phase='WAITING_CI', run=args.run, sha=args.sha, status=run['status'], conclusion=run['conclusion']))
            if run['status'] == 'completed':
                if run['conclusion'] != 'success':
                    raise RuntimeError('CI_NOT_SUCCESSFUL:' + str(run['conclusion']))
                break
            time.sleep(min(90, max(0, deadline-time.monotonic())))
        artifacts = api(f'actions/runs/{args.run}/artifacts')['artifacts']
        candidates = [x for x in artifacts if x['name'] == 'guardian-vllm-fp8-runtime-' + args.sha and not x['expired']]
        if len(candidates) != 1:
            raise ValueError('ONE_EXACT_RUNTIME_ARTIFACT_REQUIRED')
        artifact = candidates[0]
        request = urllib.request.Request('https://api.github.com/repos/MYC-A/Guardian-of-Truth/'
            + f'actions/artifacts/{artifact["id"]}/zip', headers={'Authorization': 'Bearer ' + token,
                                                               'User-Agent': 'Guardian-runtime-fetch'})
        try:
            response = opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                raise
            location = error.headers.get('Location')
            error.close()
            parsed = urllib.parse.urlsplit(location or '')
            if parsed.scheme != 'https' or parsed.username or parsed.password:
                raise ValueError('INVALID_ARTIFACT_REDIRECT')
            # Fresh request never forwards the GitHub credential to storage.
            response = urllib.request.urlopen(location, timeout=45)
        outer = args.directory / 'ci-artifact.zip'
        partial = args.directory / 'ci-artifact.zip.partial'
        if outer.exists() or partial.exists():
            response.close()
            raise FileExistsError('ARTIFACT_DESTINATION_EXISTS')
        value, count = hashlib.sha256(), 0
        status(dict(phase='DOWNLOADING_RUNTIME', run=args.run, sha=args.sha, expected_bytes=artifact['size_in_bytes']))
        with response, partial.open('xb') as out:
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('ARTIFACT_DOWNLOAD_DEADLINE')
                block = response.read(1 << 20)
                if not block:
                    break
                count += len(block)
                if count > artifact['size_in_bytes']:
                    raise ValueError('EXTRA_ARTIFACT_BYTES')
                value.update(block); out.write(block)
        if count != artifact['size_in_bytes']:
            raise ValueError('TRUNCATED_ARTIFACT')
        if artifact.get('digest') and artifact['digest'] != 'sha256:' + value.hexdigest():
            raise ValueError('ARTIFACT_SHA_MISMATCH')
        partial.rename(outer)
        with zipfile.ZipFile(outer) as bundle:
            names = bundle.namelist()
            if len(names) != len(set(names)) or any(n.startswith('/') or '..' in Path(n).parts or '\\' in n for n in names):
                raise ValueError('UNSAFE_ARTIFACT_ARCHIVE')
            receipt = json.loads(bundle.read('runtime-export.json'))
            runtime = args.directory / 'guardian-vllm-runtime.zip'
            if runtime.exists():
                raise FileExistsError(runtime)
            value = hashlib.sha256(); count = 0
            with bundle.open('guardian-vllm-runtime.zip') as source, runtime.with_suffix('.zip.partial').open('xb') as out:
                while block := source.read(8 << 20):
                    value.update(block); count += len(block); out.write(block)
            if count != receipt['bytes'] or value.hexdigest() != receipt['sha256']:
                raise ValueError('RUNTIME_TRANSPORT_SHA_MISMATCH')
            runtime.with_suffix('.zip.partial').rename(runtime)
            for name in ('runtime-export.json', 'RUNTIME_MANIFEST.json', 'cpu-smoke.json', 'requirements-frozen.txt', 'tests.log', 'NOT_FOR_UPLOAD.txt'):
                if name in names:
                    with (args.directory / name).open('xb') as out:
                        out.write(bundle.read(name))
        status(dict(phase='COMPLETE', run=args.run, sha=args.sha, runtime=str(runtime), bytes=count,
                    scope='Verified partial runtime transport; no weights or GPU deployment claim'))
    except BaseException as error:
        status(dict(phase='FAILED', run=args.run, sha=args.sha, error=type(error).__name__, detail=str(error)[:300]))
        raise


if __name__ == '__main__':
    main()
