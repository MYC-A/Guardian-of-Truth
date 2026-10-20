"""Source-audited native TRAIN inventory and finite exact-score hard-case mining."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write,verify_frozen,verify_model
from scripts.v12_transfer import ADAPTER_SHA
from scripts.v6_verifier_data import verifier_text


def mining_text(text):
    # A constrained binary score needs a binary question, not a request to start
    # a rationale with "Rule:". This is a direct verifier mining score.
    return verifier_text(text)


def paired(rows):
    groups=defaultdict(list)
    for r in rows:groups[r['pair_id']].append(r)
    return [pair for pair in groups.values() if len(pair)==2 and {r['label'] for r in pair}=={0,1}]


def select(rows,scores):
    buckets=defaultdict(list)
    for pair in paired(rows):
        neg=next(r for r in pair if not r['label']);pos=next(r for r in pair if r['label'])
        tie=hashlib.sha256(('v13:'+neg['pair_id']).encode()).hexdigest()
        key=(neg['domain'],neg['family'])
        buckets[key].append((-scores[neg['id']],scores[pos['id']],tie,pair))
    for bucket in buckets.values():bucket.sort(key=lambda x:x[:3])
    chosen=[];families=Counter();templates=Counter()
    while len(chosen)<96:
        progress=False
        for key in sorted(buckets):
            if families[key]>=8:continue
            while buckets[key]:
                pair=buckets[key].pop(0)[-1];r=pair[0];template=(*key,r['template_id'])
                if templates[template]>=4:continue
                chosen.append(pair);families[key]+=1;templates[template]+=1;progress=True;break
            if len(chosen)==96:break
        if not progress:break
    return [r for pair in chosen for r in sorted(pair,key=lambda x:x['label'])]


def dump(path,rows):
    with path.open('w') as f:
        for r in rows:f.write(json.dumps(r)+'\n')


def prepare(a):
    from transformers import AutoTokenizer
    from scripts.v6_verifier_data import source_audit
    from scripts.v5_35b_prepare import encode
    a.out.mkdir(parents=True,exist_ok=False)
    frozen=a.lab/'v4-20261019/frozen-v2';verify_frozen(frozen)
    protected=read(frozen/'dev.jsonl')+read(frozen/'holdout.jsonl')
    forbidden_ids={r['id'] for r in protected};forbidden_components={r['split_component'] for r in protected}
    accepted=[];rejected=[]
    for r in read(frozen/'train.jsonl'):
        if r['source']!='tau2' or not r.get('proof',{}).get('native_target_execution'):continue
        if r['id'] in forbidden_ids or r['split_component'] in forbidden_components:raise ValueError('TRAIN_EVAL_COMPONENT_OVERLAP')
        try:
            mode=source_audit(r)
            if mode!='native_bounded_predicate_rechecked':raise ValueError('NOT_NATIVE')
            accepted.append(r)
        except Exception as e:rejected.append(dict(id=r['id'],error_type=type(e).__name__,reason=str(e)))
    pairs=paired(accepted);accepted=[r for pair in pairs for r in pair]
    tok=AutoTokenizer.from_pretrained(a.lab/'models/qwen36-awq',local_files_only=True)
    encoded=[];metadata=[];too_long=[]
    for pair in pairs:
        outputs=[]
        for r in pair:
            _,v=encode(tok,r);text=tok.decode(v['ids'],skip_special_tokens=False)
            if hashlib.sha256(text.encode()).hexdigest()!=v['text_sha256']:raise ValueError('SOURCE_ROUNDTRIP')
            prompt=mining_text(text);ids=tok.encode(prompt,add_special_tokens=False)
            outputs.append(dict(id=r['id'],ids=ids,tokens=len(ids),text_sha256=hashlib.sha256(prompt.encode()).hexdigest()))
        if any(r['tokens']>48700 for r in outputs):too_long.append(pair[0]['pair_id']);continue
        encoded.extend(outputs)
        metadata.extend([{k:r[k] for k in ('id','label','pair_id','domain','family','template_id','split_component')} for r in pair])
    dump(a.out/'inputs.jsonl',encoded);dump(a.out/'TRAIN_INDEX.jsonl',metadata)
    write(a.out/'SOURCE_AUDIT.json',dict(accepted=len(encoded),native_pairs=len(encoded)//2,rejected=rejected,
        oversized_pairs=too_long,human_reviewed=False,general_semantic_correctness_certified=False,
        no_quality_score_selection=True,source_frozen_sha256=sha(frozen/'FROZEN.json'),source_train_sha256=sha(frozen/'train.jsonl')))
    write(a.out/'PREPARED.json',dict(complete=True,rows=len(encoded),inputs_sha256=sha(a.out/'inputs.jsonl'),
        index_sha256=sha(a.out/'TRAIN_INDEX.jsonl'),max_tokens=max(r['tokens'] for r in encoded),
        tokens=sum(r['tokens'] for r in encoded),family_counts={str(k):v for k,v in Counter((r['domain'],r['family']) for r in metadata).items()},
        source_sha256=sha(Path(__file__)),protocol_sha256=sha(ROOT/'docs/judge_20261013/V13_NATIVE_MINING_PROTOCOL.md'),
        eval_used=False,training_started=False,purpose='TRAIN direct binary verifier; not post-review deployment score'))
    from scripts.v7_control import export
    export(a.out)


def mine(a):
    from vllm import LLM,SamplingParams
    from vllm.lora.request import LoRARequest
    from scripts.judge_stage import engine_kwargs,answer_ids,answer_score,probe
    from scripts.v5_valid46_pipeline import bound_llm,pipeline_config
    a.out.mkdir(parents=True,exist_ok=False);llm=None;started=time.monotonic()
    try:
        meta=json.loads((a.data/'PREPARED.json').read_bytes())
        if sha(a.data/'inputs.jsonl')!=meta['inputs_sha256']:raise ValueError('INPUT_DRIFT')
        adapter=a.lab/'v7-workflow-20261020/training-v2/layers16/adapter'
        if sha(adapter/'adapter_model.safetensors')!=ADAPTER_SHA:raise ValueError('ADAPTER_DRIFT')
        verify_model(a.lab/'models/qwen36-awq',a.lab/'v5-35b-20261019/BASE_MODEL_MANIFEST.json')
        cfg=pipeline_config(a.lab/'models/qwen36-awq');cfg.update(dtype='bfloat16',gpu_memory_utilization=.85)
        kwargs,_=engine_kwargs(str(a.lab/'models/qwen36-awq'),cfg)
        request=LoRARequest('v13-train-only',1,str(adapter))
        llm=bound_llm(LLM,request,a.out/'generation_audit.jsonl',binding_adapter=adapter,expected_source_modules=100)(**kwargs)
        tok=llm.get_tokenizer();yes,no=answer_ids(tok)
        params=SamplingParams(temperature=1,top_p=1,max_tokens=1,logprobs=20,seed=0,allowed_token_ids=sorted(yes|no))
        exact,info=probe(llm,tok,params,yes,no)
        if exact is not True:raise ValueError('EXACT_PROBE')
        write(a.out/'PROBE.json',dict(exact=exact,info=info));scores={};inputs=read(a.data/'inputs.jsonl')
        with (a.out/'scores.jsonl').open('w',buffering=1) as f:
            for offset in range(0,len(inputs),64):
                if time.time()>a.deadline-60:raise TimeoutError('MINING_DEADLINE')
                batch=inputs[offset:offset+64];outputs=llm.generate([dict(prompt_token_ids=r['ids']) for r in batch],params,use_tqdm=False)
                if len(outputs)!=len(batch):raise ValueError('SCORE_COVERAGE')
                for r,o in zip(batch,outputs):
                    score,exact=answer_score(o,yes,no)
                    if not exact or score is None or not math.isfinite(score) or list(o.prompt_token_ids)!=r['ids']:raise ValueError('INEXACT_OR_INPUT_DRIFT')
                    scores[r['id']]=score;f.write(json.dumps(dict(id=r['id'],score=score,exact=True))+'\n')
                write(a.out/'PROGRESS.json',dict(done=len(scores),total=len(inputs)))
        write(a.out/'SCORES_FROZEN.json',dict(sha256=sha(a.out/'scores.jsonl'),labels_read=False))
        if sha(a.data/'TRAIN_INDEX.jsonl')!=meta['index_sha256']:raise ValueError('TRAIN_INDEX_DRIFT')
        rows=read(a.data/'TRAIN_INDEX.jsonl');chosen=select(rows,scores)
        dump(a.out/'SELECTED_TRAIN_INDEX.jsonl',chosen)
        def counts(rr):
            return dict(rows=len(rr),fp=sum(not r['label'] and scores[r['id']]>0 for r in rr),
                fn=sum(r['label'] and scores[r['id']]<=0 for r in rr))
        result=dict(complete=True,all_train=counts(rows),selected=counts(chosen),pairs=len(chosen)//2,
            family_counts={str(k):v for k,v in Counter((r['domain'],r['family']) for r in chosen).items()},
            scores_sha256=sha(a.out/'scores.jsonl'),selection_sha256=sha(a.out/'SELECTED_TRAIN_INDEX.jsonl'),
            source_sha256=sha(Path(__file__)),training_started=False,eval_used=False,
            caveat='Direct binary verifier is a mining proxy, not deployed post-review verifier quality',seconds=time.monotonic()-started)
        write(a.out/'RESULTS.json',result);write(a.out/'DONE.json',dict(complete=True,results_sha256=sha(a.out/'RESULTS.json')))
    except Exception as e:
        write(a.out/'FAIL.json',dict(error=str(e),traceback=traceback.format_exc()));raise
    finally:
        if llm is not None:llm.llm_engine.engine_core.shutdown()
        from scripts.v7_control import export
        export(a.out)
    sys.stdout.flush();sys.stderr.flush();os._exit(0)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','mine'])
    for k in ('lab','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--data',type=Path);p.add_argument('--deadline',type=float);a=p.parse_args()
    prepare(a) if a.mode=='prepare' else mine(a)
