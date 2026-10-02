"""Content-addressed raw sources once; immutable reference indexes per trace."""
import json
from pathlib import Path

from .store import digest


def persist_snapshot(snapshot, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    raw_sha = digest(snapshot['raw'])
    if raw_sha != snapshot['source_sha256']:
        raise ValueError('source archive fingerprint mismatch')
    index = {k: v for k, v in snapshot.items() if k != 'raw'}
    index['raw_ref'] = raw_sha + '.raw.json'
    index_sha = digest(index)
    for name, value in ((raw_sha + '.raw.json', snapshot['raw']), (index_sha + '.index.json', index)):
        content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        file = directory / name
        try:
            with file.open('xb') as stream:
                stream.write(content)
        except FileExistsError:
            if file.read_bytes() != content:
                raise ValueError('immutable archive collision')
    return {'source_sha256': raw_sha, 'index_sha256': index_sha,
            'raw_file': raw_sha + '.raw.json', 'index_file': index_sha + '.index.json'}
