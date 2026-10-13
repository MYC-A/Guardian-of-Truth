"""Resumable pinned HF download; pack verified shards with bounded local storage."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
import uuid
import zipfile

CHUNK=16*1024*1024

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def save(path,value):
    p=Path(path);tmp=p.with_name(p.name+'.tmp')
    tmp.write_text(json.dumps(value,indent=2),encoding='utf-8');os.replace(tmp,p)

def info(name):
    i=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));i.create_system=3
    i.external_attr=(0o100644)<<16;i.compress_type=zipfile.ZIP_DEFLATED
    i._compresslevel=1
    return i

def prepare(inventory,stage,temporary,workers=8):
    inventory=Path(inventory);stage=Path(stage);temporary=Path(temporary)
    d=json.loads(inventory.read_text(encoding='utf-8'));revision=d['revision'];repo=d['repository']
    if len(revision)!=40 or any(x not in '0123456789abcdef' for x in revision):raise ValueError('PIN_REQUIRED')
    temporary.mkdir(parents=True,exist_ok=True);stage.parent.mkdir(parents=True,exist_ok=True)
    receipt=stage.with_name(stage.name+'.weights.json')
    state=json.loads(receipt.read_text()) if receipt.exists() else dict(repository=repo,revision=revision,files={})
    if (state['repository'],state['revision'])!=(repo,revision):raise ValueError('STAGE_IDENTITY_MISMATCH')
    mode='a' if stage.exists() else 'w'
    started=time.monotonic();downloaded=0;lock=threading.Lock();last=time.monotonic();last_bytes=0
    def emit(event,**kw):print(json.dumps(dict(event=event,**kw)),flush=True)
    def fetch(entry,path,off,length):
        nonlocal downloaded
        receipt=path.with_name(path.name+f'.chunk-{off}.json')
        if receipt.exists():
            rec=json.loads(receipt.read_text())
            with path.open('rb') as f:f.seek(off);b=f.read(length)
            if (rec.get('offset'),rec.get('length'),rec.get('sha256'))==(off,length,hashlib.sha256(b).hexdigest()) and len(b)==length:return
        for attempt in range(5):
            try:
                url=f"https://huggingface.co/{repo}/resolve/{revision}/{entry['name']}?download=true&range_nonce={uuid.uuid4().hex}"
                req=urllib.request.Request(url,headers={'Range':f'bytes={off}-{off+length-1}','Accept-Encoding':'identity'})
                with urllib.request.urlopen(req,timeout=90) as response:
                    if response.status!=206 or response.headers.get('Content-Range')!=f"bytes {off}-{off+length-1}/{entry['bytes']}":raise ValueError('RANGE_MISMATCH')
                    data=response.read(length+1)
                if len(data)!=length:raise ValueError('SHORT_RANGE')
                with path.open('r+b',buffering=0) as f:f.seek(off);f.write(data)
                save(receipt,dict(offset=off,length=length,sha256=hashlib.sha256(data).hexdigest()))
                with lock:downloaded+=length
                return
            except Exception as error:
                emit('download_retry',file=entry['name'],offset=off,attempt=attempt+1,error=type(error).__name__)
                if attempt==4:raise
                time.sleep(min(2**attempt,10))
    with zipfile.ZipFile(stage,mode,allowZip64=True) as z, ThreadPoolExecutor(workers) as pool:
        existing=set(z.namelist())
        if existing!=set(state['files']):raise ValueError('STAGE_RECEIPT_FILE_SET_MISMATCH')
        for entry in d['files']:
            name=entry['name'];target=f'model/{revision}/{name}'
            if Path(name).name!=name or entry['bytes'] is None:raise ValueError('UNSAFE_OR_UNSIZED_MODEL_FILE')
            if target in existing:
                emit('reuse_verified_member',file=name);continue
            path=temporary/(name+'.partial')
            if entry['bytes']>=CHUNK:
                if not path.exists():
                    with path.open('wb') as f:f.truncate(entry['bytes'])
                if path.stat().st_size!=entry['bytes']:raise ValueError('PARTIAL_SIZE_MISMATCH')
                futures=[pool.submit(fetch,entry,path,off,min(CHUNK,entry['bytes']-off)) for off in range(0,entry['bytes'],CHUNK)]
                for future in as_completed(futures):
                    future.result();now=time.monotonic()
                    if now-last>=15:
                        emit('download_progress',file=name,downloaded_bytes=downloaded,recent_MBps=round((downloaded-last_bytes)/(now-last)/1e6,2),seconds=round(now-started,1))
                        last,last_bytes=now,downloaded
            else:
                url=f'https://huggingface.co/{repo}/resolve/{revision}/{name}'
                with urllib.request.urlopen(url,timeout=60) as r:path.write_bytes(r.read(entry['bytes']+1))
            h=digest(path)
            if path.stat().st_size!=entry['bytes'] or entry.get('sha256') and entry['sha256']!=h:raise ValueError('MODEL_FILE_MISMATCH:'+name)
            emit('pack_verified_file',file=name,bytes=entry['bytes'])
            with path.open('rb') as source,z.open(info(target),'w',force_zip64=True) as dest:
                for b in iter(lambda:source.read(8*1024*1024),b''):dest.write(b)
            state['files'][target]=dict(bytes=entry['bytes'],sha256=h,mode=0o644)
            # Persist central directory before deleting the sole uncompressed copy.
            z.close();save(receipt,state)
            path.unlink()
            for chunk_receipt in temporary.glob(path.name+'.chunk-*.json'):chunk_receipt.unlink()
            z=zipfile.ZipFile(stage,'a',allowZip64=True)
            existing.add(target)
        z.close()
    state.update(all_model_files_verified=True,seconds=time.monotonic()-started)
    save(receipt,state);emit('weights_ready',stage=str(stage),bytes=stage.stat().st_size,files=len(state['files']))
    return state

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory',required=True);p.add_argument('--stage',required=True)
    p.add_argument('--temporary',required=True);p.add_argument('--workers',type=int,default=8)
    a=p.parse_args();prepare(a.inventory,a.stage,a.temporary,a.workers)
