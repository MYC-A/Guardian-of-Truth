"""Offline stdlib-only metadata wheel for the diagnostic package."""
import base64
import csv
import hashlib
import io
from pathlib import Path
import zipfile

NAME = 'guardian_platform_environment_probe'
VERSION = '0.0.1'
DIST = NAME+'-'+VERSION+'.dist-info'


def metadata():
    return {DIST+'/METADATA': (
        'Metadata-Version: 2.1\nName: guardian-platform-environment-probe\n'
        'Version: 0.0.1\nRequires-Python: >=3.8\n'
        'Summary: Diagnostic only, not a prediction solution\n\n').encode(),
        DIST+'/WHEEL': b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n'}


def get_requires_for_build_wheel(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    for name, value in metadata().items():
        path = Path(metadata_directory)/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    return DIST


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    files = metadata()
    rows = io.StringIO(newline='')
    writer = csv.writer(rows, lineterminator='\n')
    for name, value in sorted(files.items()):
        encoded = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip('=')
        writer.writerow((name, 'sha256='+encoded, len(value)))
    writer.writerow((DIST+'/RECORD', '', ''))
    files[DIST+'/RECORD'] = rows.getvalue().encode()
    output = Path(wheel_directory)
    output.mkdir(parents=True, exist_ok=True)
    name = NAME+'-'+VERSION+'-py3-none-any.whl'
    with zipfile.ZipFile(output/name, 'w', compression=zipfile.ZIP_DEFLATED) as wheel:
        for relative, value in sorted(files.items()):
            wheel.writestr(relative, value)
    return name
