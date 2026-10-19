"""Bounded resumable HTTP fallback for the public pinned 4B base; verify all hashes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import urllib.request


def digest(path,row):
    h=hashlib.sha256() if row['algorithm']=='sha256' else hashlib.sha1()
    if row['algorithm']=='git-sha1':h.update(('blob '+str(row['bytes'])+'\0').encode())
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8<<20),b''):h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    m=json.loads(a.manifest.read_bytes());assert (m['repository'],m['revision'])==('Qwen/Qwen3-4B-Instruct-2507','cdbee75f17c01a7cc42f958dc650907174af0554')
    a.out.mkdir(parents=True,exist_ok=True);root=a.out.resolve();started=time.monotonic()
    def one(row):
        path=(root/row['path']).resolve();assert path.is_relative_to(root)
        if path.is_file() and path.stat().st_size==row['bytes'] and digest(path,row)==row['digest']:
            print(json.dumps(dict(event='reused',path=row['path'])),flush=True);return
        path.parent.mkdir(parents=True,exist_ok=True);part=path.with_suffix(path.suffix+'.http-part');errors=0;last=0
        if row['bytes']>128<<20:
            offset=part.stat().st_size if part.exists() else 0;block=32<<20
            ranges=[(start,min(row['bytes'],start+block)-1) for start in range(offset,row['bytes'],block)]
            def fetch(bounds):
                start,end=bounds;chunk=part.with_name(part.name+'.range-'+str(start))
                if chunk.is_file() and chunk.stat().st_size==end-start+1:return chunk
                for attempt in range(4):
                    try:
                        url='https://huggingface.co/'+m['repository']+'/resolve/'+m['revision']+'/'+row['path']+'?download=true&guardian_offset='+str(start)
                        request=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
                        with urllib.request.urlopen(request,timeout=30) as response:
                            assert response.status==206 and response.headers.get('Content-Range')==f'bytes {start}-{end}/{row["bytes"]}','BAD_PARALLEL_RANGE'
                            with chunk.open('wb') as out:
                                for data in iter(lambda:response.read(4<<20),b''):out.write(data)
                        assert chunk.stat().st_size==end-start+1,'SHORT_PARALLEL_RANGE'
                        return chunk
                    except Exception:
                        if attempt==3:raise
                        time.sleep(2)
            with ThreadPoolExecutor(max_workers=4) as pool:
                pending={i:pool.submit(fetch,ranges[i]) for i in range(min(4,len(ranges)))}
                with part.open('ab') as out:
                    for i,bounds in enumerate(ranges):
                        chunk=pending.pop(i).result()
                        assert out.tell()==bounds[0]
                        with chunk.open('rb') as source:shutil.copyfileobj(source,out,4<<20)
                        out.flush();os.fsync(out.fileno());chunk.unlink()
                        if i+4<len(ranges):pending[i+4]=pool.submit(fetch,ranges[i+4])
                        print(json.dumps(dict(event='progress',path=row['path'],bytes=out.tell(),total=row['bytes'])),flush=True)
        while (part.stat().st_size if part.exists() else 0)<row['bytes']:
            offset=part.stat().st_size if part.exists() else 0;end=min(row['bytes'],offset+(64<<20))-1
            url='https://huggingface.co/'+m['repository']+'/resolve/'+m['revision']+'/'+row['path']+'?download=true&guardian_offset='+str(offset)
            try:
                request=urllib.request.Request(url,headers={'Range':f'bytes={offset}-{end}'})
                with urllib.request.urlopen(request,timeout=30) as response:
                    cr=response.headers.get('Content-Range','');match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',cr)
                    if response.status==206:
                        assert match and int(match[1])==offset and int(match[3])==row['bytes'] and int(match[2])<=end,'BAD_CONTENT_RANGE'
                        remaining=int(match[2])-offset+1
                    elif response.status==200 and offset==0:remaining=row['bytes']
                    else:raise ValueError('RANGE_NOT_HONORED')
                    with part.open('ab') as out:
                        while remaining:
                            block=response.read(min(4<<20,remaining))
                            if not block:raise EOFError('SHORT_HTTP_BODY')
                            out.write(block);remaining-=len(block)
                        out.flush();os.fsync(out.fileno())
                if time.monotonic()-last>20:
                    print(json.dumps(dict(event='progress',path=row['path'],bytes=part.stat().st_size,total=row['bytes'])),flush=True);last=time.monotonic()
            except Exception as error:
                errors+=1;print(json.dumps(dict(event='retry',path=row['path'],error=type(error).__name__,attempt=errors)),flush=True)
                if errors>=4:raise
                time.sleep(2)
        assert part.stat().st_size==row['bytes'] and digest(part,row)==row['digest'],'PINNED_FILE_HASH_MISMATCH'
        part.replace(path);print(json.dumps(dict(event='verified',path=row['path'],bytes=row['bytes'])),flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(one,m['files']))
    m.update(verified=True,seconds=time.monotonic()-started,transport='bounded_range_http')
    (root/'VERIFIED.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(event='download_done',seconds=m['seconds'])),flush=True)


if __name__=='__main__':main()
