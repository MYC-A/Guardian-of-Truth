"""Bounded reproduction of the historical native Granite3.3 groundedness lane."""
import argparse
from collections import Counter
import hashlib
import json
from numbers import Integral
import os
from pathlib import Path
import re
import time

from guardian_truth.file_lock import process_lock
from experiments.full21.run_granite_guardian_flash import bound_pair
from experiments.guardian_local_a100.method_synthesis import metrics as base_metrics
from experiments.guardian_local_a100.run_local import ROOT, rows
from experiments.guardian_local_a100.score_local import classify_row, gold_for
from experiments.research_records import freeze_phase

MODEL = 'ibm-granite/granite-guardian-3.3-8b'
REVISION = 'b3421eda4ba6fc9f9a71121d7e62de08827469a4'
VERSION = 'granite-native-historical-contract-v1'
SCORE = re.compile(r'\s*(?:<think>\s*</think>\s*)?<score>\s*(yes|no)\s*</score>\s*(?:<\|end_of_text\|>\s*)?', re.I)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_digest(path):
    value=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def metrics(predictions,gold):
    result=base_metrics(predictions,gold)
    tp,fp,fn=(result[k] for k in ('TP','FP','FN'))
    result.update(precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None)
    return result


def verify_checkpoint(path):
    setup=json.loads((path.parent/'granite_download_setup.json').read_text(encoding='utf-8'))
    if setup.get('repo')!=MODEL or setup.get('resolved_revision')!=REVISION:
        raise ValueError('UNVERIFIED_CHECKPOINT_REVISION')
    expected=setup.get('expected_weights') or {}
    index=json.loads((path/'model.safetensors.index.json').read_text(encoding='utf-8'))
    names=set(index['weight_map'].values())
    if not names or names!=set(expected) or names!={p.name for p in path.glob('*.safetensors')}:
        raise ValueError('CHECKPOINT_SHARD_INVENTORY')
    hashes={}
    for name in sorted(names):
        value=file_digest(path/name)
        if value!=expected[name]['sha256'] or (path/name).stat().st_size!=expected[name]['size']:
            raise ValueError('CHECKPOINT_WEIGHT_HASH_MISMATCH')
        hashes[name]=value
    return hashes


def parse(text):
    match = SCORE.fullmatch(text) if isinstance(text,str) else None
    return int(match[1].lower() == 'yes') if match else None


def request(tokenizer, row):
    prompt, response = bound_pair(row['prompt'], row['response'], 12000)
    chat = tokenizer.apply_chat_template(
        [dict(role='assistant',content=response.text)],
        guardian_config={'criteria_id':'groundedness'},
        documents=[dict(doc_id='prompt_context',text=prompt.text)],
        think=False,tokenize=False,add_generation_prompt=True)
    return chat, dict(prompt=vars(prompt),response=vars(response),
                      complete_input=not prompt.truncated and not response.truncated)


def combine(a,b,kind):
    if kind=='OR':
        return 1 if a==1 or b==1 else 0 if a==0 and b==0 else None
    if kind=='AND':
        return 0 if a==0 or b==0 else 1 if a==1 and b==1 else None
    raise ValueError('UNKNOWN_COMBINATION')


def read_jsonl(path,ids,allow_missing=False):
    result={}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['id'] in result or r['id'] not in ids:
                raise ValueError('DUPLICATE_OR_FOREIGN_ID')
            result[r['id']]=r
    if not allow_missing and set(result)!=set(ids):
        raise ValueError('INCOMPLETE_ID_SET')
    return result


def score_predictions(predictions,qwen,archive,gold):
    if not set(predictions)==set(qwen)==set(archive)==set(gold):
        raise ValueError('UNMATCHED_SCORE_IDS')
    report=dict(rows=len(gold),granite_new=metrics(predictions,gold),
                granite_archived=metrics(archive,gold),qwen_b2=metrics(qwen,gold),combinations={})
    for source,pred in [('archive',archive),('fresh',predictions)]:
        for kind in ('OR','AND'):
            report['combinations'][source+'_'+kind]=metrics({k:combine(qwen[k],pred[k],kind) for k in gold},gold)
    report['fresh_vs_archive_flips']=[dict(id=k,label=gold[k],old=archive[k],new=predictions[k])
                                    for k in sorted(gold) if archive[k]!=predictions[k]]
    report['fresh_additions_to_qwen']=[dict(id=k,label=gold[k]) for k in sorted(gold)
                                      if qwen[k]==0 and predictions[k]==1]
    return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--model-path',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    import torch
    import transformers
    import pandas as pd
    from transformers import AutoModelForCausalLM, AutoTokenizer
    base=a.output
    base.mkdir(parents=True,exist_ok=True)
    data=[{k:r[k] for k in ('id','prompt','response')} for r in rows('valid46')]
    ids={r['id'] for r in data}
    if len(data)!=46 or len(ids)!=46:
        raise ValueError('INVALID_VALID46_INVENTORY')
    tokenizer=AutoTokenizer.from_pretrained(str(a.model_path),local_files_only=True,trust_remote_code=False)
    weights_hashes=verify_checkpoint(a.model_path)
    jobs=[]
    for row in data:
        chat,meta=request(tokenizer,row)
        token_ids=tokenizer(chat,add_special_tokens=False)['input_ids']
        jobs.append(dict(id=row['id'],chat=chat,bounds=meta,input_ids=token_ids,request_sha256=digest(chat.encode('utf-8')),
                         original_prompt_sha256=digest(row['prompt'].encode('utf-8')),
                         original_response_sha256=digest(row['response'].encode('utf-8'))))
    config=dict(version=VERSION,model=MODEL,revision=REVISION,torch=torch.__version__,
                transformers=transformers.__version__,dtype='checkpoint_native_BF16',
                criterion='groundedness',think=False,max_new_tokens=16,do_sample=False,
                max_context_chars=12000,prompt_chars=4800,response_chars=7200,
                max_calls=46,attn_implementation='sdpa',
                runner_sha256=digest(Path(__file__).read_bytes()),
                bounder_sha256=digest((ROOT/'experiments/full21/run_granite_guardian_flash.py').read_bytes()),
                runtime_sha256={n:digest(Path(__file__).with_name(n).read_bytes())
                                for n in ('run_local.py','score_local.py','method_synthesis.py')},
                freeze_helper_sha256=file_digest(ROOT/'experiments/research_records.py'),
                weights_sha256=weights_hashes,
                files={p.name:digest(p.read_bytes()) for p in sorted(a.model_path.iterdir())
                       if p.is_file() and p.suffix in ('.json','.jinja')},
                task='Native factual groundedness; diagnostic binary projection, not policy proof')
    path=base/'runs.jsonl'
    def append(path,row):
        with path.open('a',encoding='utf-8',newline='\n') as f:
            f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
    with process_lock(base/'run.lock'):
        freeze_phase(path,ROOT,config,jobs)
        done=read_jsonl(path,ids,allow_missing=True)
        ledger=base/'attempts.jsonl'
        attempts=[json.loads(l) for l in ledger.read_text(encoding='utf-8').splitlines()] if ledger.exists() else []
        started=[r['id'] for r in attempts if r['event']=='STARTED']
        if len(started)!=len(set(started)) or not set(started)<=ids:
            raise ValueError('ILLEGAL_ATTEMPT_LEDGER')
        # An interrupted STARTED call is not repeated or silently projected to0.
        for key in set(started)-set(done):
            r=dict(id=key,binary=None,status='INTERRUPTED_ATTEMPT_NOT_RETRIED')
            append(path,r);done[key]=r
        model=None
        if set(done)!=ids:
            model=AutoModelForCausalLM.from_pretrained(str(a.model_path),local_files_only=True,
                trust_remote_code=False,torch_dtype='auto',device_map='auto',attn_implementation='sdpa')
            model.eval()
            torch.cuda.reset_peak_memory_stats()
        context_limit=int(model.config.max_position_embeddings) if model is not None else None
        actual_dtype=str(model.dtype) if model is not None else None
        packets=base/'packets';packets.mkdir(exist_ok=True)
        for job in jobs:
            if job['id'] in done: continue
            result={k:v for k,v in job.items() if k not in ('chat','input_ids')}
            packet=packets/(job['request_sha256']+'.json')
            if not packet.exists():
                with packet.open('x',encoding='utf-8') as f: json.dump(job,f,ensure_ascii=False)
            result.update(input_tokens=len(job['input_ids']),context_limit=context_limit)
            if len(job['input_ids'])+16>context_limit:
                result.update(binary=None,status='CONTEXT_NOT_FIT')
            else:
                if len(started)>=46: raise RuntimeError('DURABLE_ATTEMPT_CAP')
                append(ledger,dict(id=job['id'],event='STARTED',request_sha256=job['request_sha256']))
                started.append(job['id']);t0=time.monotonic()
                try:
                    inputs=torch.tensor([job['input_ids']],device=model.device)
                    mask=torch.ones_like(inputs)
                    with torch.inference_mode():
                        generated=model.generate(inputs,attention_mask=mask,do_sample=False,max_new_tokens=16,
                                                  pad_token_id=tokenizer.eos_token_id)
                    output=generated[0,len(job['input_ids']):].tolist()
                    raw=tokenizer.decode(output,skip_special_tokens=False)
                    value=parse(raw)
                    result.update(binary=value,status='VALID' if value is not None else 'INVALID_NATIVE_SCORE',
                                  raw=raw,generated_token_ids=output,output_tokens=len(output),
                                  completion_budget_reached=len(output)==16,eos_seen=tokenizer.eos_token_id in output,
                                  seconds=time.monotonic()-t0)
                except Exception as exc:
                    result.update(binary=None,status='TECHNICAL_FAILURE',error=type(exc).__name__,detail=str(exc)[:200])
                append(ledger,dict(id=job['id'],event='FINISHED',status=result['status'],seconds=time.monotonic()-t0))
            append(path,result);done[job['id']]=result
            print(json.dumps(dict(done=len(done),expected=46,id=job['id'],status=result['status'])),flush=True)
        gold={k:v['label'] for k,v in gold_for('valid46').items()}
        qroot=ROOT/'outputs/guardian_local_a100/llamacpp/qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/runs/valid46/B2_rep1.jsonl'
        qrows=read_jsonl(qroot,ids)
        qwen={k:r.get('binary') if classify_row(r,'B2','binary') not in ('missing','no_solution') else None for k,r in qrows.items()}
        archive_path=ROOT/'outputs/searh_23/baseline_frozen/control_repro_percase.csv'
        archive_df=pd.read_csv(archive_path)
        if len(archive_df)!=46 or archive_df.id.nunique()!=46 or set(archive_df.id)!=ids:
            raise ValueError('INVALID_ARCHIVE_IDS')
        if any(int(r.gold)!=gold[r.id] for r in archive_df.itertuples()):
            raise ValueError('ARCHIVE_GOLD_MISMATCH')
        if any(not isinstance(r.granite_repro,Integral) or isinstance(r.granite_repro,bool) or r.granite_repro not in (0,1)
               for r in archive_df.itertuples()):
            raise ValueError('INVALID_ARCHIVE_BINARY')
        archive={r.id:int(r.granite_repro) for r in archive_df.itertuples()}
        report=score_predictions({k:r['binary'] for k,r in done.items()},qwen,archive,gold)
        report.update(status_counts=dict(Counter(r['status'] for r in done.values())),
                      actual_calls=len(started),input_tokens=sum(r.get('input_tokens',0) for r in done.values()),
                      output_tokens=sum(r.get('output_tokens',0) for r in done.values()),
                      inference_seconds=sum(r.get('seconds',0) for r in done.values()),
                      peak_allocated_bytes=torch.cuda.max_memory_allocated() if model is not None else None,
                      actual_dtype=actual_dtype,
                      complete_input_rows=sum(bool(r.get('bounds',{}).get('complete_input')) for r in done.values()),
                      fingerprints=dict(runs=digest(path.read_bytes()),qwen=digest(qroot.read_bytes()),
                                        archive=digest(archive_path.read_bytes()),gold=digest(json.dumps(gold,sort_keys=True).encode())),
                      limitation='Known valid46 development; fresh Granite + saved Qwen, no cause accuracy or hidden-test claim')
        report_path=base/'score.json'
        if not report_path.exists():
            with report_path.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
        print(json.dumps(report),flush=True)


if __name__=='__main__':main()
