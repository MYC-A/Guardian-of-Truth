"""Download the pinned u2_dense encoder once (needs network; not part of the submission run).

    python scripts/fetch_judge_encoder.py --output models/encoder

Writes ENCODER_SOURCE.json (repository, revision, size + SHA256 of every file) next to the weights; the ZIP
builder records the same data in JUDGE_MANIFEST.json.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from guardian_truth.judge.dense_encoder import (FETCH_PATTERNS, PINNED_REPOSITORY, PINNED_REVISION,  # noqa: E402
                                                REQUIRED_FILES)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args(argv)
    from huggingface_hub import snapshot_download
    snapshot_download(PINNED_REPOSITORY, revision=PINNED_REVISION, local_dir=str(a.output),
                      allow_patterns=list(FETCH_PATTERNS))
    missing = [name for name in REQUIRED_FILES if not (a.output / name).is_file()]
    if missing:
        raise SystemExit('ENCODER_FILES_MISSING: ' + ', '.join(missing))
    files = []
    for path in sorted(p for p in a.output.rglob('*') if p.is_file() and not any(
            part.startswith('.') for part in p.relative_to(a.output).parts) and p.name != 'ENCODER_SOURCE.json'):
        data = path.read_bytes()
        files.append(dict(path=path.relative_to(a.output).as_posix(), size=len(data),
                          sha256=hashlib.sha256(data).hexdigest()))
    source = dict(repository=PINNED_REPOSITORY, revision=PINNED_REVISION, files=files)
    (a.output / 'ENCODER_SOURCE.json').write_text(json.dumps(source, indent=2), encoding='utf-8')
    print(json.dumps(dict(output=str(a.output), files=len(files), revision=PINNED_REVISION)))


if __name__ == '__main__':
    main()
