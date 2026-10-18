"""Pinned public payloads, no ambient HF token or remote code execution."""
import concurrent.futures
import hashlib
import json
import time
import urllib.request
from pathlib import Path

BASE = Path('/workspace/guardian-lab-20261018/v3-20261019')
ITEMS = [('datasets', 'Team-ACE/ToolACE', '6bda777c88d21e5a204703c1ee45597a8fa4f734', BASE/'toolace-payload'),
         ('models', 'Qwen/Qwen3-8B', 'b968826d9c46dd6066d109eabc6255188de91218', BASE/'qwen3-8b')]

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Guardian-v3'}), timeout=60)

def fetch(job):
    url, target, item = job
    if target.exists(): raise ValueError('REFUSE_OVERWRITE:'+str(target))
    error = None
    for attempt in range(3):
        try:
            sha = hashlib.sha256(); git = hashlib.sha1()
            git.update(('blob '+str(item['size'])+'\0').encode())
            with get(url) as response, target.with_suffix(target.suffix+'.partial').open('wb') as output:
                while block := response.read(4*1024*1024):
                    output.write(block); sha.update(block); git.update(block)
            temp = target.with_suffix(target.suffix+'.partial')
            assert temp.stat().st_size == item['size'], 'SIZE_MISMATCH'
            if item.get('lfs'): assert sha.hexdigest() == item['lfs']['oid'], 'LFS_MISMATCH'
            else: assert git.hexdigest() == item['oid'], 'GIT_OBJECT_MISMATCH'
            temp.rename(target)
            result = dict(path=item['path'], bytes=item['size'], sha256=sha.hexdigest(), verified=True)
            print(json.dumps(result), flush=True)
            return result
        except Exception as exc:
            error = str(exc)[:300]
            if attempt < 2: time.sleep(2)
    raise RuntimeError(error)

def main():
    started=time.time()
    for kind, repo, revision, folder in ITEMS:
        folder.mkdir(exist_ok=False)
        with get(f'https://huggingface.co/api/{kind}/{repo}/tree/{revision}?expand=true') as response:
            tree=json.load(response)
        (folder/'TREE.json').write_text(json.dumps(tree,indent=2))
        (folder/'START.json').write_text(json.dumps(dict(repo=repo,revision=revision,started=started)))
        jobs=[]
        for item in tree:
            name=item['path']
            if item['type']!='file' or name=='.gitattributes': continue
            target=folder/name; target.parent.mkdir(parents=True,exist_ok=True)
            prefix='datasets/' if kind=='datasets' else ''
            jobs.append((f'https://huggingface.co/{prefix}{repo}/resolve/{revision}/{name}',target,item))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: records=list(pool.map(fetch,jobs))
        (folder/'VERIFIED.json').write_text(json.dumps(dict(repo=repo,revision=revision,verified=True,files=records,seconds=time.time()-started),indent=2))

if __name__=='__main__': main()
