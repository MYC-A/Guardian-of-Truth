"""Build the tiny input-shape probe ZIP (a few KB). Never submit for scoring."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile


def build(output):
    root = Path(__file__).resolve().parents[1]
    payload = {
        'scripts/predict.py': (root / 'submission/input_shape_probe.py').read_bytes(),
        'probe_build_backend.py': (root / 'submission/probe_build_backend.py').read_bytes(),
        'pyproject.toml': b'[build-system]\nrequires = []\nbuild-backend = "probe_build_backend"\nbackend-path = ["."]\n',
        'DIAGNOSTIC_ONLY_NOT_FOR_SCORING.txt': b'Input shape probe: counts rows/lengths only, no content, exit 2.\n',
        'README.md': b'# Guardian input shape probe\n\nUpload only for diagnosis, never submit for scoring.\n',
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as raw, zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        directory = zipfile.ZipInfo('scripts/', date_time=(1980, 1, 1, 0, 0, 0))
        directory.create_system = 3
        directory.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
        archive.writestr(directory, b'')
        for name, value in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, value)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for name, value in payload.items():
            assert archive.read(name) == value
    receipt = dict(output=str(output), bytes=output.stat().st_size,
                   sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    print(json.dumps(receipt, indent=2))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
