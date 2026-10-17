"""Verify and apply a pinned code package, without overwriting local work.

python PACKAGE/payload/scripts/apply_blind_review_package.py --package PACKAGE --repo WORKTREE --check
Omit --check to apply after all integrity, compilation, base and git-apply checks pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative_file(root, name):
    target = (root / name).resolve()
    if not target.is_relative_to(root) or ':' in name or '\\' in name:
        raise ValueError('UNSAFE_PACKAGE_PATH: ' + name)
    return target


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package', type=Path, required=True)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args(argv)
    package, repo = a.package.resolve(), a.repo.resolve()
    manifest = json.loads((package / 'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path = relative_file(package, item['path'])
        data = path.read_bytes()
        if len(data) != item['size'] or digest(data) != item['sha256']:
            raise SystemExit('PACKAGE_INTEGRITY: ' + item['path'])
        if path.suffix == '.py':
            compile(data, str(path), 'exec')
    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
    head = git('rev-parse', 'HEAD').stdout.decode().strip()
    if head != manifest['base_sha']:
        raise SystemExit('BASE_MISMATCH: expected %s, got %s; use a separate worktree at the pinned base'
                         % (manifest['base_sha'], head))
    already = all(relative_file(repo, p).is_file()
                  and digest(relative_file(repo, p).read_bytes().replace(b'\r\n', b'\n')) == h
                  for p, h in manifest['targets'].items())
    if already:
        print('ALREADY_APPLIED', manifest['source_commit'])
        return 0
    dirty = git('status', '--porcelain').stdout
    if dirty.strip():
        raise SystemExit('DIRTY_WORKTREE: keep existing work and apply in a clean separate worktree')
    patch = relative_file(package, manifest['patch'])
    git('apply', '--check', '--binary', str(patch))
    if a.check:
        print('CHECK_OK', manifest['base_sha'], len(manifest['targets']), 'targets')
        return 0
    git('apply', '--binary', str(patch))
    for name, expected in manifest['targets'].items():
        actual = relative_file(repo, name).read_bytes().replace(b'\r\n', b'\n')
        if digest(actual) != expected:
            raise SystemExit('TARGET_VERIFY_FAILED: ' + name)
    print('APPLIED_AND_VERIFIED', manifest['source_commit'], len(manifest['targets']), 'targets')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
