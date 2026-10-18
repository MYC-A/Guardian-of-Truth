"""Immutable indexed archive including tau debug paths and supervisor evidence."""
import argparse
import datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

LAB = Path('/workspace/guardian-lab-20261018')
BASE = LAB / 'v3-20261019'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stage', required=True)
    p.add_argument('--pins-only', action='store_true')
    a = p.parse_args()
    assert a.stage.replace('-', '').isalnum()
    folder = BASE / 'overnight-backups'
    folder.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')
    target = folder / (stamp + '-' + a.stage + '.tar.gz')
    files = set()
    for pattern in (() if a.pins_only else ('hours-*', 'tau4b-*', 'tau8b-*', 'tau35b-*', '*REVIEW*.json', 'OVERNIGHT_STATE.json')):
        for path in BASE.glob(pattern):
            files.update(x for x in path.rglob('*') if x.is_file()) if path.is_dir() else files.add(path)
    for name in ('source-inventory', 'supplementary-pins'):
        files.update(x for x in (BASE / name).rglob('*') if x.is_file())
    files.update((BASE / 'tau2-source').rglob('*.py'))
    for name in ('LICENSE', 'pyproject.toml'):
        files.add(BASE / 'tau2-source' / name)
    for model in (LAB / 'models/qwen3-4b-instruct', LAB / 'models/qwen36-awq', BASE / 'qwen3-8b'):
        for name in ('VERIFIED.json', 'LICENSE', '.weights.json'):
            if (model / name).is_file():
                files.add(model / name)
    for pattern in ('guardian-lab-v3*.log', 'guardian-lab-v3*.sh'):
        files.update(LAB.glob(pattern))
    files.update((LAB / 'code/scripts').glob('v3_*.py'))
    files.update((LAB / 'code/src/guardian_truth/judge').rglob('*.py'))
    files.add(LAB / 'code/scripts/judge_stage.py')
    files.update(Path('/etc/supervisor/conf.d').glob('guardian-lab-v3*.conf'))
    manifest = []
    with tarfile.open(str(target) + '.partial', 'w:gz', compresslevel=1) as archive:
        def add(name, data):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            manifest.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        for path in sorted(files):
            if not path.is_file():
                continue
            name = str(path.relative_to(LAB)) if path.is_relative_to(LAB) else 'supervisor/' + path.name
            add(name, path.read_bytes())
        revisions = {}
        for path in (LAB / 'code', BASE / 'tau2-source'):
            result = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], capture_output=True, text=True)
            revisions[str(path)] = dict(git_head=result.stdout.strip() or None,
                                       git_error=result.stderr.strip() if result.returncode else None)
        revisions['source_pins'] = [{k: row.get(k) for k in ('repository', 'revision', 'declared_license')}
                                   for row in json.loads((BASE / 'source-inventory/sources_manifest.json').read_bytes())['sources']]
        add('ARCHIVE_SOURCE_REVISIONS.json', json.dumps(revisions, indent=2).encode())
        index_data = json.dumps(dict(files=manifest, limitations=[
            'Live logs are byte snapshots, not final logs.',
            'Current code and per-run executed_source files are preserved where present.',
            'Missing historical executed source is not reconstructed as original.',
            'Native tau paths may contain Windows-invalid characters; read inside tar.'
        ]), indent=2).encode()
        info = tarfile.TarInfo('ARCHIVE_FILES.json')
        info.size = len(index_data)
        archive.addfile(info, io.BytesIO(index_data))
    Path(str(target) + '.partial').rename(target)
    digest = hashlib.sha256()
    with target.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    entry = dict(name=target.name, bytes=target.stat().st_size, sha256=digest.hexdigest())
    index = folder / 'INDEX.json'
    entries = json.loads(index.read_bytes()) if index.exists() else []
    assert all(item['name'] != entry['name'] for item in entries)
    entries.append(entry)
    temporary = folder / 'INDEX.json.tmp'
    temporary.write_text(json.dumps(entries, indent=2))
    temporary.replace(index)
    print(json.dumps(dict(entry, files=len(manifest))), flush=True)


if __name__ == '__main__':
    main()
