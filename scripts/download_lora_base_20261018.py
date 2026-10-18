"""Download and hash-verify the explicitly pinned public LoRA base; own lab only."""
import argparse,hashlib,json,os,time
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    m=json.loads(a.manifest.read_bytes())
    assert m['repository']=='Qwen/Qwen3-4B-Instruct-2507' and m['revision']=='cdbee75f17c01a7cc42f958dc650907174af0554'
    os.environ.update(HF_XET_HIGH_PERFORMANCE='1',HF_XET_CHUNK_CACHE_SIZE_BYTES='0',HF_HUB_DISABLE_TELEMETRY='1',HF_HOME=str(a.out.parent/'hf-cache'))
    from huggingface_hub import snapshot_download
    start=time.monotonic();print(json.dumps(dict(event='download_start',bytes=m['total_bytes'])),flush=True)
    snapshot_download(m['repository'],revision=m['revision'],local_dir=a.out,allow_patterns=[x['path'] for x in m['files']],token=False,max_workers=6)
    for e in m['files']:
        q=a.out/e['path'];assert q.stat().st_size==e['bytes'],e['path']
        h=hashlib.sha256() if e['algorithm']=='sha256' else hashlib.sha1()
        if e['algorithm']=='git-sha1':h.update(('blob '+str(e['bytes'])+'\0').encode())
        with q.open('rb') as f:
            for b in iter(lambda:f.read(8<<20),b''):h.update(b)
        assert h.hexdigest()==e['digest'],e['path']
        print(json.dumps(dict(event='verified',path=e['path'])),flush=True)
    m.update(verified=True,seconds=time.monotonic()-start)
    (a.out/'VERIFIED.json').write_text(json.dumps(m,indent=2)+'\n')
    print(json.dumps(dict(event='download_done',seconds=m['seconds'])),flush=True)
if __name__=='__main__':main()
