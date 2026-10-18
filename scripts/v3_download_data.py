"""Acquire immutable source payloads on the GPU host; no generated labels."""
import argparse
import concurrent.futures
import hashlib
import json
import time
import urllib.request
from pathlib import Path


def download(item):
    url, path, expected = item
    assert not path.exists(), path
    part = path.with_suffix(path.suffix + '.partial')
    error = None
    for attempt in range(3):
        try:
            digest = hashlib.sha256()
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Guardian-v3'}), timeout=60) as r, part.open('wb') as f:
                while block := r.read(4 * 1024 * 1024):
                    f.write(block); digest.update(block)
            value = digest.hexdigest()
            if expected: assert expected == value, ('UPSTREAM_HASH_MISMATCH', path.name)
            part.rename(path)
            return dict(url=url, file=path.name, bytes=path.stat().st_size, sha256=value,
                        upstream_sha256=expected, complete=True)
        except Exception as e:
            error = dict(error_type=type(e).__name__, error=str(e)[:300])
            if attempt != 2: time.sleep(2)
    return dict(url=url, file=path.name, complete=False, **error)


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--root', type=Path, required=True)
    a = p.parse_args(); folder = a.root / 'payloads'; folder.mkdir(exist_ok=False)
    start = time.time(); (folder/'START.json').write_text(json.dumps(dict(started_unix=start)))
    inventory = json.loads((a.root/'source-inventory/sources_manifest.json').read_bytes())
    by = {s['repository']:s for s in inventory['sources']}; jobs=[]
    for repo, names in [('ParticleMedia/RAGTruth', ['dataset/response.jsonl','dataset/source_info.jsonl'])]:
        s=by[repo]
        for name in names:
            jobs.append((f'https://raw.githubusercontent.com/{repo}/{s["revision"]}/{name}',folder/name.rsplit('/',1)[-1],None))
    repo='ibm-research/ToolRM-train-data'; revision=by[repo]['revision']
    url=f'https://huggingface.co/api/datasets/{repo}/tree/{revision}/data/train?expand=true'
    with urllib.request.urlopen(url,timeout=30) as r: tree=json.load(r)
    (folder/'ToolRM-tree.json').write_text(json.dumps(tree,indent=2))
    for item in tree:
        if item['path'].endswith('.arrow'):
            jobs.append((f'https://huggingface.co/datasets/{repo}/resolve/{revision}/{item["path"]}',
                         folder/item['path'].rsplit('/',1)[-1],item['lfs']['oid']))
    records=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(download,jobs):
            records.append(result);print(json.dumps(result),flush=True)
            (folder/'DOWNLOADS.json').write_text(json.dumps(records,indent=2))
    done=dict(complete=all(r['complete'] for r in records),files=len(records),seconds=time.time()-start,
              downloaded_source_code_executed=False,training_started=False)
    (folder/'DONE.json').write_text(json.dumps(done,indent=2)); print(json.dumps(done),flush=True)
    if not done['complete']:raise SystemExit(1)


if __name__=='__main__':main()
