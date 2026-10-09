"""Freeze official pinned Linux CPython3.12 wheel bytes for packaging review.

Operator-only: no package installation, model invocation, or runtime behavior
change. The registry distinguishes public vendor examples from private sources.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import urllib.parse
import urllib.request
import zipfile

from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--requirements', type=Path, default=ROOT / 'submission/requirements-runtime.txt')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('VENDOR_REGISTRY_ALREADY_EXISTS')
    requirements = args.requirements.read_bytes()
    pins = []
    for line in requirements.decode('utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([\w-]+)==([\w.]+)', line)
        if not match:
            raise ValueError('EXACT_RUNTIME_DEPENDENCY_PIN_REQUIRED')
        pins.append(match.groups())
    platforms = ['manylinux_2_' + str(n) + '_x86_64' for n in range(39, 4, -1)]
    platforms += ['manylinux2014_x86_64', 'manylinux2010_x86_64', 'manylinux1_x86_64', 'linux_x86_64']
    tags = list(cpython_tags((3, 12), abis=['cp312'], platforms=platforms))
    tags += list(compatible_tags((3, 12), interpreter='cp312', platforms=platforms))
    priorities = {tag: index for index, tag in enumerate(tags)}

    def freeze(pin):
        name, version = pin
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        metadata_url = 'https://pypi.org/pypi/' + name + '/' + version + '/json'
        with opener.open(metadata_url, timeout=30) as response:
            metadata = json.load(response)
        candidates = []
        for item in metadata['urls']:
            if item['packagetype'] != 'bdist_wheel' or item.get('yanked'):
                continue
            _, _, _, wheel_tags = parse_wheel_filename(item['filename'])
            rank = min((priorities[t] for t in wheel_tags if t in priorities), default=None)
            if rank is not None:
                candidates.append((rank, item['filename'], item))
        if not candidates:
            raise ValueError('NO_COMPATIBLE_PINNED_LINUX_CP312_WHEEL: ' + name)
        item = min(candidates)[2]
        url = urllib.parse.urlsplit(item['url'])
        if url.scheme != 'https' or url.hostname != 'files.pythonhosted.org' or url.query:
            raise ValueError('OFFICIAL_PUBLIC_WHEEL_HOST_REQUIRED')
        if item['size'] > 200_000_000:
            raise ValueError('VENDOR_WHEEL_SIZE_BOUND_EXCEEDED')
        with opener.open(item['url'], timeout=60) as response:
            wheel = response.read(200_000_001)
        if len(wheel) != item['size'] or hashlib.sha256(wheel).hexdigest() != item['digests']['sha256']:
            raise ValueError('OFFICIAL_VENDOR_WHEEL_HASH_OR_SIZE_MISMATCH')
        files = {}
        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or ':' in entry.filename:
                    raise ValueError('UNSAFE_VENDOR_WHEEL_MEMBER')
                if path.name == 'RECORD' and any(p.endswith('.dist-info') for p in path.parts):
                    continue  # pip regenerates this ledger during installation.
                data = archive.read(entry)
                files['runtime/site-packages/' + entry.filename] = dict(
                    bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), distribution=name, version=version)
        info = dict(name=name, version=version, wheel=item['filename'], wheel_bytes=len(wheel),
                    wheel_sha256=item['digests']['sha256'], metadata_url=metadata_url, public_wheel_url=item['url'])
        return info, files

    distributions, files = [], {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        for info, owned in executor.map(freeze, pins):
            if set(files) & set(owned):
                raise ValueError('VENDOR_FILE_OWNERSHIP_COLLISION')
            distributions.append(info)
            files.update(owned)
    registry = dict(version='guardian-official-vendor-wheel-registry-1', target='Linux x86_64 CPython3.12 glibc2.39',
                    requirements_sha256=hashlib.sha256(requirements).hexdigest(),
                    coverage='ALL_PINNED_DISTRIBUTIONS', distributions=distributions, files=files,
                    note='Public vendor provenance, not a semantic policy proof or a secret-detection guarantee.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        output.write(json.dumps(registry, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(registry=str(args.output.resolve()), distributions=len(distributions), files=len(files),
                          sha256=hashlib.sha256(args.output.read_bytes()).hexdigest())))


if __name__ == '__main__':
    main()
