"""Turn a `uv pip compile --generate-hashes` lock into a pip-report-shaped file list.

For each pinned name==version, PyPI JSON gives the distribution files; we keep the
single wheel that (a) has a sha256 listed in the lock and (b) has the best tag
supported by the target interpreter (pip's own packaging.tags). No sdists.
"""
import json
import re
import sys
import urllib.request

from pip._vendor.packaging import tags
from pip._vendor.packaging.utils import parse_wheel_filename

lock, out = sys.argv[1], sys.argv[2]
text = open(lock).read().replace('\\\n', ' ')
pins = []
for line in text.splitlines():
    line = line.strip()
    m = re.match(r'^([A-Za-z0-9_.\-\[\]]+)==([^\s;]+)', line)
    if not m:
        continue
    name = re.sub(r'\[.*\]', '', m.group(1))
    hashes = set(re.findall(r'--hash=sha256:([0-9a-f]{64})', line))
    pins.append((name, m.group(2), hashes))
supported = {t: i for i, t in enumerate(tags.sys_tags())}
install, missing = [], []
for name, version, hashes in pins:
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=60) as r:
        data = json.load(r)
    best = None
    for f in data['urls']:
        if f['packagetype'] != 'bdist_wheel' or f['digests']['sha256'] not in hashes:
            continue
        _, _, _, wtags = parse_wheel_filename(f['filename'])
        rank = min((supported[t] for t in wtags if t in supported), default=None)
        if rank is not None and (best is None or rank < best[0]):
            best = (rank, f)
    if best is None:
        missing.append(f'{name}=={version}')
        continue
    f = best[1]
    install.append(dict(metadata=dict(name=name, version=version),
                        download_info=dict(url=f['url'], archive_info=dict(hashes=dict(sha256=f['digests']['sha256']))),
                        size=f['size']))
json.dump(dict(install=install, missing=missing), open(out, 'w'), indent=1)
print(json.dumps(dict(pins=len(pins), wheels=len(install), missing=missing,
                      total_bytes=sum(i['size'] for i in install))))
