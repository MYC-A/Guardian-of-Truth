"""Operator-only public pinned snapshot download with full file verification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    manifest = json.loads(a.manifest.read_bytes())
    assert manifest['repository'] == 'Rakancorle1/PolicyGuard-4B'
    assert manifest['revision'] == 'f9060bd92c6f7d70170e1c5239131b10027cf375'
    os.environ.update(HF_XET_HIGH_PERFORMANCE='1', HF_XET_CHUNK_CACHE_SIZE_BYTES='0',
                      HF_HUB_DISABLE_TELEMETRY='1', HF_HOME=str(a.out.parent/'hf-cache'))
    from huggingface_hub import snapshot_download
    started = time.monotonic()
    print(json.dumps(dict(event='download_start', repository=manifest['repository'],
                         revision=manifest['revision'], bytes=manifest['total_bytes'])), flush=True)
    snapshot_download(manifest['repository'], revision=manifest['revision'], local_dir=a.out,
                      allow_patterns=[e['path'] for e in manifest['files']], token=False, max_workers=6)
    verified = []
    for entry in manifest['files']:
        path = a.out/entry['path']
        if path.stat().st_size != entry['bytes']:
            raise ValueError('SIZE_MISMATCH: '+entry['path'])
        h = hashlib.sha256() if entry['algorithm'] == 'sha256' else hashlib.sha1()
        if entry['algorithm'] == 'git-sha1':
            h.update(('blob '+str(entry['bytes'])+'\0').encode())
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8 << 20), b''):
                h.update(block)
        if h.hexdigest() != entry['digest']:
            raise ValueError('HASH_MISMATCH: '+entry['path'])
        verified.append(entry['path'])
        print(json.dumps(dict(event='verified', path=entry['path'], bytes=entry['bytes'])), flush=True)
    result = dict(repository=manifest['repository'], revision=manifest['revision'],
                  verified_files=verified, bytes=manifest['total_bytes'], elapsed=time.monotonic()-started)
    (a.out/'VERIFIED.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(event='download_done', **result)), flush=True)


if __name__ == '__main__':
    main()
