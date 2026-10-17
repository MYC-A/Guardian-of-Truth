"""Build a verified CODE/PATCH ZIP from committed git objects, never a contest/model archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', required=True)
    ap.add_argument('--commit', default='HEAD')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--test-log', type=Path)
    ap.add_argument('--audit', type=Path)
    a = ap.parse_args(argv)
    base = git('rev-parse', '--verify', a.base + '^{commit}').decode().strip()
    commit = git('rev-parse', '--verify', a.commit + '^{commit}').decode().strip()
    git('merge-base', '--is-ancestor', base, commit)
    changes = git('diff', '--name-status', base, commit).decode().splitlines()
    paths = []
    for change in changes:
        status, name = change.split('\t')
        if status not in ('A', 'M') or ':' in name or '..' in Path(name).parts or name.startswith('/'):
            raise ValueError('UNSUPPORTED_PACKAGE_CHANGE: ' + change)
        if not name.startswith(('.github/', 'docs/', 'scripts/', 'src/', 'submission/', 'tests/')):
            raise ValueError('UNEXPECTED_PACKAGE_PATH: ' + name)
        paths.append(name)
    if not paths:
        raise ValueError('EMPTY_PACKAGE')
    files = {'blind_review.patch': git('diff', '--binary', '--full-index', base, commit)}
    targets = {}
    for name in paths:
        data = git('show', commit + ':' + name)
        files['payload/' + name] = data
        targets[name] = sha(data.replace(b'\r\n', b'\n'))
    files['README_BLIND_REVIEW.md'] = git('show', commit + ':docs/judge_20261013/README_BLIND_REVIEW.md')
    files['apply_blind_review_patch.py'] = b'''from pathlib import Path
import runpy
import sys
package = Path(__file__).resolve().parent
script = package / 'payload/scripts/apply_blind_review_package.py'
sys.argv = [str(script), '--package', str(package), *sys.argv[1:]]
runpy.run_path(str(script), run_name='__main__')
'''
    if a.test_log:
        files['verification/tests.log'] = a.test_log.read_bytes()
    if a.audit:
        data = a.audit.read_bytes()
        text = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        files['verification/audit.json'] = (json.dumps(json.loads(text), indent=2) + '\n').encode()
    manifest = dict(schema='guardian-blind-review-code-package-v1', base_sha=base, source_commit=commit,
                    source_branch='fix/blind-review-package-20261017', patch='blind_review.patch',
                    model_id='cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit',
                    model_revision='00fcea2d3bcf5389b518d4fc082e5590e0ba4844',
                    status=['IMPLEMENTED', 'CPU_VERIFIED', 'GPU_UNTESTED'],
                    contest_archive=False, targets=targets,
                    files=[dict(path=n, size=len(d), sha256=sha(d)) for n, d in sorted(files.items())])
    files['PACKAGE_MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    out = a.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + '.partial')
    if out.exists() or tmp.exists():
        raise FileExistsError(out if out.exists() else tmp)
    with tmp.open('xb') as stream, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 17, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data, compresslevel=9)
        z.comment = b'Guardian blind review CODE package; GPU_UNTESTED'
    with zipfile.ZipFile(tmp) as z:
        if z.testzip() is not None or set(z.namelist()) != set(files):
            raise ValueError('ZIP_INTEGRITY')
        for name, data in files.items():
            if sha(z.read(name)) != sha(data):
                raise ValueError('ZIP_MEMBER_INTEGRITY: ' + name)
    if out.exists():
        raise FileExistsError(out)
    os.replace(tmp, out)
    digest = sha(out.read_bytes())
    with Path(str(out) + '.sha256').open('x', encoding='utf-8') as sidecar:
        sidecar.write(digest + '  ' + out.name + '\n')
    print(json.dumps(dict(path=str(out), bytes=out.stat().st_size, sha256=digest, base_sha=base,
                          source_commit=commit, files=len(files), targets=len(paths)), indent=2))


if __name__ == '__main__':
    main()
