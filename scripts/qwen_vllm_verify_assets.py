"""Verify a pinned HF local_dir against upstream LFS/Git blobs, without loading a model."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import urllib.request

REPOSITORY = 'Qwen/Qwen3.8-27B-FP8'
REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'


def verify(model_dir, metadata, selected, workers=4):
    root = Path(model_dir).resolve()
    if metadata.get('sha') != REVISION or metadata.get('id') != REPOSITORY:
        raise ValueError('UPSTREAM_IDENTITY_MISMATCH')
    upstream = {entry['rfilename']: entry for entry in metadata['siblings']}
    if len(upstream) != len(metadata['siblings']) or len(selected) != len(set(selected)):
        raise ValueError('DUPLICATE_ASSET')
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError('INVALID_HASH_WORKERS')

    def check(name):
        pure = PurePosixPath(name)
        if pure.is_absolute() or '..' in pure.parts or '\\' in name:
            raise ValueError('UNSAFE_ASSET_PATH')
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('ASSET_ESCAPES_MODEL_DIR')
        source = upstream[name]
        size = path.stat().st_size
        if size != source['size']:
            raise ValueError('ASSET_SIZE_MISMATCH:' + name)
        digest = hashlib.sha256()
        blob = hashlib.sha1(f'blob {size}\0'.encode('ascii'))
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
                blob.update(chunk)
        actual = digest.hexdigest()
        # Any LFS-tracked asset (all weights, plus e.g. tokenizer.json) is proven by its
        # LFS content SHA256; its Git blobId hashes only the pointer file.
        if name.endswith('.safetensors') or source.get('lfs') is not None:
            expected = (source.get('lfs') or {}).get('sha256')
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError('MISSING_UPSTREAM_WEIGHT_SHA:' + name)
            if actual != expected:
                raise ValueError('WEIGHT_SHA_MISMATCH:' + name)
            proof = dict(method='UPSTREAM_LFS_SHA256', expected=expected)
        else:
            expected = source.get('blobId')
            if not isinstance(expected, str) or blob.hexdigest() != expected:
                raise ValueError('GIT_BLOB_MISMATCH:' + name)
            proof = dict(method='UPSTREAM_GIT_BLOB_SHA1', expected=expected)
        return dict(path=name, size=size, sha256=actual, upstream_verification=proof)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(check, sorted(selected)))
    index = json.loads((root / 'model.safetensors.index.json').read_text(encoding='utf-8'))
    weights = set(index['weight_map'].values())
    if weights != {r['path'] for r in records if r['path'].endswith('.safetensors')}:
        raise ValueError('INDEX_WEIGHT_SET_MISMATCH')
    return dict(repository=REPOSITORY, revision=REVISION, files=records,
                verification='All selected local bytes checked against pinned upstream identities',
                hash_workers=workers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--download-protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    protocol = json.loads(args.download_protocol.read_text(encoding='utf-8'))
    if protocol['repo'] != REPOSITORY or protocol['revision'] != REVISION:
        raise ValueError('DOWNLOAD_PROTOCOL_IDENTITY_MISMATCH')
    url = f'https://huggingface.co/api/models/{REPOSITORY}/revision/{REVISION}?blobs=true'
    with urllib.request.urlopen(url, timeout=30) as response:
        metadata = json.load(response)
    result = verify(args.model_dir, metadata, protocol['files'])
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(status='VERIFIED', files=len(result['files']),
                         bytes=sum(r['size'] for r in result['files']))))


if __name__ == '__main__':
    main()
