"""Full legacy B2 on host vLLM; positional rows and durable binary checkpoints."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile
import time
import math

from scripts import qwen35_system_adapter as adapter
from submission.predict_vllm import read_input, digest, completion_cap

PROFILE='Qwen3.5-35B-A3B-FP8-B2-system-vllm-v1'

def log(event,**values):
    print('GUARDIAN_QWEN35_B2 '+json.dumps(dict(event=event,**values),sort_keys=True),flush=True)

def publish(path,rows,labels,previous_hash=None):
    """Initial publication is exclusive; checkpoints replace only our last output."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    os.close(fd);temporary=Path(name)
    try:
        ids=[r['id'] for r in rows]
        if path.suffix.lower() in ('.parquet','.pq'):
            import pandas as pd
            pd.DataFrame(dict(id=ids,label=labels)).astype({'label':'int64'}).to_parquet(temporary,index=False)
            actual=pd.read_parquet(temporary)
            if actual['id'].tolist()!=ids or actual['label'].tolist()!=labels:raise ValueError('OUTPUT_ALIGNMENT')
        else:
            with temporary.open('w',encoding='utf-8',newline='') as f:
                w=csv.writer(f,lineterminator='\n');w.writerow(['id','label']);w.writerows(zip(ids,labels))
            with temporary.open(encoding='utf-8',newline='') as f:actual=list(csv.DictReader(f))
            if [r['id'] for r in actual]!=ids or [int(r['label']) for r in actual]!=labels:raise ValueError('OUTPUT_ALIGNMENT')
        with temporary.open('r+b') as f:os.fsync(f.fileno())
        os.chmod(temporary,0o644)
        if previous_hash is None:
            os.link(temporary,path)
        else:
            if path.is_symlink() or digest(path)!=previous_hash:raise ValueError('OUTPUT_CHANGED_BY_ANOTHER_WRITER')
            os.replace(temporary,path)
        return digest(path)
    finally:temporary.unlink(missing_ok=True)

def environment():
    versions={}
    for package in ('vllm','torch','transformers','tokenizers','huggingface-hub','regex','pandas','pyarrow'):
        try:versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:versions[package]='MISSING'
    return dict(executable=os.sys.executable,packages=versions,
                python=os.sys.version.split()[0],system_runtime=True)

def run(root,input_path,output,*,work_dir=None,duration=1740,workers=16,slots=32,
        client=None,layers=None,server_class=None,predictor=None):
    root=Path(root).resolve();input_path=Path(input_path).resolve();output=Path(output).absolute()
    if input_path==output or output.exists() or output.is_symlink():raise ValueError('OUTPUT_EXISTS_OR_OVERLAPS_INPUT')
    if (not math.isfinite(duration) or not 0<duration<=1740
            or type(workers) is not int or not 1<=workers<=32
            or type(slots) is not int or not 1<=slots<=64):raise ValueError('INVALID_RUNTIME_LIMITS')
    start=time.monotonic();deadline=start+duration
    original=digest(input_path);rows=read_input(input_path)
    if digest(input_path)!=original:raise ValueError('INPUT_CHANGED_DURING_READ')
    work=Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix='guardian-qwen35-b2-'))
    if work_dir:work.mkdir(parents=True,exist_ok=False)
    work=work.resolve()
    if work.is_relative_to(root):raise ValueError('WORK_MUST_BE_OUTSIDE_ARCHIVE')
    (work/'rows').mkdir();labels=[0]*len(rows);traces=[None]*len(rows)
    output_hash=publish(output,rows,labels)
    protocol=dict(profile=PROFILE,model=adapter.MODEL,rows=len(rows),input_sha256=original,
        workers=workers,slots=slots,duration=duration,context=32768,output=str(output),
        row_identity='POSITION',model_calls_use_only_prompt_response=True,
        pipeline='FULL_B2_LEGACY_UNCHANGED',default_label=0,checkpoint_before_model_start=True,
        model_and_gpu_timing_tested=False,environment=environment())
    adapter.write_json(work/'protocol.json',protocol)
    log('input',rows=len(rows),duplicate_ids=len(rows)-len({r['id'] for r in rows}),
        work=str(work),workers=workers,slots=slots,initial_output_written=True)
    log('environment',**protocol['environment'])
    active=None;pool=None;pending={};next_row=0;completed=0;last_save=time.monotonic()
    def process(model_client,model_layers):
        nonlocal pool,next_row,completed,last_save,output_hash
        from guardian_truth.submission.cli import predict_one
        execute=predictor or predict_one
        pool=ThreadPoolExecutor(max_workers=workers)
        while next_row<len(rows) or pending:
            while next_row<len(rows) and len(pending)<workers and time.monotonic()<deadline-15:
                i=next_row;model_row=dict(rows[i],id=f'row{i:07d}')
                pending[pool.submit(execute,model_row,model_client,model_layers,
                    model=adapter.MODEL,provider='local-vllm')]=i
                next_row+=1
            if not pending or time.monotonic()>=deadline:break
            done,_=wait(pending,timeout=min(1,max(0,deadline-time.monotonic())),return_when=FIRST_COMPLETED)
            for future in done:
                i=pending.pop(future)
                try:trace=future.result()
                except Exception as error:trace=dict(binary=0,owner='DEFAULT_ZERO',error=type(error).__name__)
                label=trace.get('binary')
                if type(label) is not int or label not in (0,1):
                    trace=dict(trace,binary=0,owner='DEFAULT_ZERO',fallback_reason='INVALID_ROW_LABEL')
                traces[i]=dict(trace,row_index=i)
                labels[i]=traces[i]['binary'];completed+=1
                adapter.write_json(work/'rows'/f'row-{i:07d}.json',traces[i])
                log('row',row_index=i,completed=completed,total=len(rows),label=labels[i],
                    owner=trace.get('owner'),seconds=round(time.monotonic()-start,1))
            if done and (completed%16==0 or time.monotonic()-last_save>=20):
                output_hash=publish(output,rows,labels,output_hash);last_save=time.monotonic()
                log('checkpoint',completed=completed,positives=sum(labels),output_sha256=output_hash)
    try:
        if rows:
            if client is not None:
                active=client;process(client,layers)
            else:
                os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_XET='1',
                    HF_HOME=str(work/'hf'),VLLM_CACHE_ROOT=str(work/'vllm'),
                    TRITON_CACHE_DIR=str(work/'triton'),TORCHINDUCTOR_CACHE_DIR=str(work/'inductor'),
                    VLLM_NO_USAGE_STATS='1',DO_NOT_TRACK='1')
                server_type=server_class or adapter.OwnedVllmServer
                with server_type(os.sys.executable,root/'model'/adapter.REVISION,work,32768,slots,
                        deadline=deadline,asset_manifest=root/'MODEL_MANIFEST.json',startup_timeout=600) as server:
                    log('server_ready',seconds=round(time.monotonic()-start,1))
                    active=adapter.VllmClient(server.port,32768,work/'calls',api_key=server.api_key,
                        backend_manifest=server.manifest,timeout=180,deadline=deadline,max_calls=completion_cap(rows))
                    from guardian_truth.v6fix.pipeline import Layers
                    model_layers=Layers(active,adapter.MODEL,budget=20000,attempts=(0,1),
                        frules_max_tokens=700,tolerate_component_errors=True)
                    process(active,model_layers)
    except Exception as error:
        protocol['inference_error']=dict(error=type(error).__name__,detail=str(error)[:300])
        adapter.write_json(work/'INFERENCE_FAILURE.json',protocol['inference_error'])
        log('inference_failure',**protocol['inference_error'])
    finally:
        for future in pending:future.cancel()
        if pool is not None:pool.shutdown(wait=False,cancel_futures=True)
        for i,t in enumerate(traces):
            if t is None:
                traces[i]=dict(row_index=i,binary=0,owner='DEFAULT_ZERO',
                    fallback_reason='NOT_STARTED_OR_NOT_COMPLETED',completed=False)
                adapter.write_json(work/'rows'/f'row-{i:07d}.json',traces[i])
        if digest(input_path)!=original:raise ValueError('INPUT_CHANGED_DURING_RUN')
        output_hash=publish(output,rows,labels,output_hash)
        counts=dict(Counter(t.get('owner','UNKNOWN') for t in traces))
        protocol.update(status='COMPLETE',completed=completed,unprocessed=len(rows)-completed,
            positives=sum(labels),owner_counts=counts,default_zero_rows=counts.get('DEFAULT_ZERO',0),
            output_sha256=output_hash,seconds=time.monotonic()-start,
            completion_http=getattr(active,'completion_http',0),preflight_http=getattr(active,'preflight_http',0))
        adapter.write_json(work/'DONE.json',protocol)
        adapter.write_json(output.with_name(output.name+'.run-manifest.json'),protocol)
        log('complete',**{k:protocol[k] for k in ('rows','completed','unprocessed','positives','owner_counts',
            'default_zero_rows','output_sha256','seconds','completion_http','preflight_http')})
    return protocol

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--work-dir',type=Path);p.add_argument('--workers',type=int,default=16)
    p.add_argument('--slots',type=int,default=32);p.add_argument('--duration',type=float,default=1740)
    a=p.parse_args(argv)
    return run(Path(__file__).resolve().parents[1],a.input,a.output,work_dir=a.work_dir,
        duration=a.duration,workers=a.workers,slots=a.slots)

if __name__=='__main__':main()
