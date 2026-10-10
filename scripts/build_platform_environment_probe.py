"""Build a tiny diagnostic-only ZIP, without touching the competition ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile


def build(output):
    root = Path(__file__).resolve().parents[1]
    payload = {
        'scripts/predict.py': (root/'submission/platform_environment_probe.py').read_bytes(),
        'probe_build_backend.py': (root/'submission/probe_build_backend.py').read_bytes(),
        'pyproject.toml': b'[build-system]\nrequires = []\nbuild-backend = "probe_build_backend"\nbackend-path = ["."]\n',
        'DIAGNOSTIC_ONLY_NOT_FOR_SCORING.txt': (
            b'Diagnostic environment probe, not a competition solution. No model, input reads or predictions.\n'
            b'Exit code 2 after GUARDIAN_ENV_PROBE done is intentional. Keep and share the platform log.\n'),
        'README.md': b'# Guardian platform environment probe\n\nUpload only for diagnosis, never submit for scoring.\n',
    }
    manifest = dict(purpose='DIAGNOSTIC_ONLY_NOT_FOR_SCORING', expected_exit_code=2,
        files={name: dict(bytes=len(value), sha256=hashlib.sha256(value).hexdigest()) for name,value in payload.items()})
    payload['MANIFEST.json'] = (json.dumps(manifest, indent=2, sort_keys=True)+'\n').encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as raw:
        with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name,value in sorted(payload.items()):
                info = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
                info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16
                info.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(info,value)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())==set(payload)
        for name,value in payload.items():
            assert archive.read(name)==value
    receipt=dict(output=str(output), bytes=output.stat().st_size,
        sha256=hashlib.sha256(output.read_bytes()).hexdigest(), purpose=manifest['purpose'])
    with output.with_suffix('.verification.json').open('x',encoding='utf-8') as target:
        json.dump(receipt,target,indent=2)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().output)))
