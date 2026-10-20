"""Paired rationale verifier evaluation. Invalid review preserves the accusation."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import BASE_REVISION,read,sha,write,verify_model
from scripts.v5_valid46_pipeline import bound_llm,metrics
from scripts.v6_verifier_data import OLD_ADAPTER_SHA
from guardian_truth.judge.decision import decide

def admit_review(text,policy,finish_reason):
    if finish_reason=='length':return False,'TRUNCATED'
    lines=[x.strip() for x in text.strip().splitlines() if x.strip()]
    if len(lines)!=2 or not lines[0].startswith('Rule: ') or not lines[1].startswith('Evidence: '):return False,'INVALID_FORMAT'
    quote=lines[0][6:].strip().strip('"\u201c\u201d')
    if len(quote)<15 or quote not in policy:return False,'UNSUPPORTED_QUOTE'
    if len(lines[1][10:].strip())<8 or re.search(r'\bUNKNOWN\b',lines[1],re.I):return False,'UNKNOWN'
    return True,'VALID_SOURCE_QUOTE_NOT_SEMANTIC_PROOF'

def keep_accusation(row):
    return not row['admitted'] or row['score']>0

def worker(a):
    prepared=json.loads((a.data/'PREPARED.json').read_bytes())
    protocol=json.loads((a.data/'EVAL_PROTOCOL.json').read_bytes())
    frozen_path=a.out.parent/'EVAL_CODE_FROZEN.json'
    if not frozen_path.exists():
        if a.arm!='base':raise ValueError('MISSING_INITIAL_EVALUATOR_FREEZE')
        write(frozen_path,dict(evaluator_sha256=sha(Path(__file__)),
            binding_sha256=sha(Path(__file__).with_name('v5_valid46_pipeline.py')),
            controller_sha256=json.loads((a.out.parent/'START.json').read_bytes())['source_sha256'],
            before_quality_workers=True,eval_protocol_sha256=sha(a.data/'EVAL_PROTOCOL.json')))
    frozen=json.loads(frozen_path.read_bytes())
    if sha(Path(__file__))!=frozen['evaluator_sha256'] or sha(Path(__file__).with_name('v5_valid46_pipeline.py'))!=frozen['binding_sha256']:
        raise ValueError('EVALUATOR_CHANGED_AFTER_FREEZE')
    if sha(a.data/'eval_tokens.jsonl')!=prepared['eval_tokens_sha256']:raise ValueError('EVAL_INPUT_DRIFT')
    selection=set(protocol['ids']);rows=[r for r in read(a.data/'eval_tokens.jsonl') if r['id'] in selection]
    if len(rows)!=len(selection) or any(set(r)!={'id','ids','tokens','text_sha256','source_policy'} for r in rows):raise ValueError('EVAL_SCHEMA_GOLD_LEAK')
    adapter=None;expected=50
    if a.arm!='base':
        source=a.lab/'v5-35b-20261019/train-recovered-v1' if a.arm=='old' else a.new
        meta=json.loads((source/'TRAINED.json').read_bytes());adapter=source/'adapter'
        if not meta['complete'] or meta['base_revision']!=BASE_REVISION or sha(adapter/'adapter_model.safetensors')!=meta['adapter_sha256']:raise ValueError('ADAPTER_DRIFT')
        if a.arm=='old' and meta['adapter_sha256']!=OLD_ADAPTER_SHA:raise ValueError('OLD_DRIFT')
        if a.arm=='new':
            if meta['source_adapter_sha256']!=OLD_ADAPTER_SHA or not meta['optimizer_updates']:raise ValueError('WARMSTART_DRIFT')
            expected=meta['source_modules']
    verify_model(a.lab/'models/qwen36-awq',a.lab/'v5-35b-20261019/BASE_MODEL_MANIFEST.json')
    from vllm import LLM,SamplingParams
    from vllm.lora.request import LoRARequest
    from scripts.judge_stage import answer_ids,answer_score,engine_kwargs,probe
    request=None if adapter is None else LoRARequest('v7-'+a.arm,1,str(adapter))
    cfg=json.loads((ROOT/'submission/JUDGE_OPEN_REVIEW40.json').read_bytes())
    cfg.update(max_model_len=49152,gpu_memory_utilization=.85,max_num_seqs=16,max_num_batched_tokens=8192,
        dtype='bfloat16',multimodal=True,enable_prefix_caching=True,engine_overrides=dict(enforce_eager=True,async_scheduling=False))
    kw,dropped=engine_kwargs(str(a.lab/'models/qwen36-awq'),cfg)
    llm=bound_llm(LLM,request,a.out/'generation_audit.jsonl',binding_adapter=adapter,expected_source_modules=expected)(**kw)
    tok=llm.get_tokenizer();yes,no=answer_ids(tok)
    if sorted(yes)!=prepared['answer_ids']['yes'] or sorted(no)!=prepared['answer_ids']['no']:raise ValueError('ANSWER_IDS')
    params=SamplingParams(temperature=1,top_p=1,max_tokens=1,logprobs=20,seed=0,allowed_token_ids=sorted(yes|no))
    exact,proof=probe(llm,tok,params,yes,no)
    if exact is not True:raise ValueError('EXACT_PROBE')
    reviewparams=SamplingParams(temperature=0,max_tokens=192,seed=0,stop=['\nVerdict:'])
    write(a.out/'PROBE.json',dict(exact=True,proof=proof,expected_source_modules=expected))
    started=time.monotonic();done=0
    def batch_score(batch,repeat):
        if time.time()>a.deadline:raise TimeoutError('ABSOLUTE_GPU_DEADLINE')
        timer=time.monotonic();outputs=llm.generate([dict(prompt_token_ids=r['ids']) for r in batch],reviewparams,use_tqdm=False)
        review_seconds=time.monotonic()-timer
        if len(outputs)!=len(batch):raise ValueError('REVIEW_COUNT')
        results=[];scoreinputs=[];admittedpositions=[]
        for row,output in zip(batch,outputs):
            if list(output.prompt_token_ids)!=row['ids'] or not output.outputs:raise ValueError('REVIEW_TOKEN_DRIFT')
            sample=output.outputs[0];review=sample.text
            admitted,status=admit_review(review,row['source_policy'],sample.finish_reason)
            record=dict(id=row['id'],arm=a.arm,repeat=repeat,admitted=admitted,status=status,review=review,
                score=None,exact=False,input_sha256=row['text_sha256'],generated_tokens=len(sample.token_ids))
            if admitted:
                prompt=tok.decode(row['ids'],skip_special_tokens=False)+review.strip()+'\nVerdict:'
                ids=tok.encode(prompt,add_special_tokens=False)
                if ids[:len(row['ids'])]!=row['ids'] or len(ids)>=49152:raise ValueError('FINAL_INPUT_PREFIX_OR_CAP')
                record['score_input_sha256']=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()
                scoreinputs.append(dict(prompt_token_ids=ids));admittedpositions.append(len(results))
            results.append(record)
        timer=time.monotonic()
        scored=llm.generate(scoreinputs,params,use_tqdm=False) if scoreinputs else []
        if len(scored)!=len(scoreinputs):raise ValueError('EXACT_COUNT')
        for i,output,inp in zip(admittedpositions,scored,scoreinputs):
            value,exact=answer_score(output,yes,no)
            if not exact or value is None or not math.isfinite(value) or list(output.prompt_token_ids)!=inp['prompt_token_ids']:raise ValueError('INEXACT_FINAL')
            results[i].update(score=value,exact=True)
        return results,dict(review_seconds=review_seconds,score_seconds=time.monotonic()-timer,review_calls=len(batch),exact_calls=len(scoreinputs))
    timing=[]
    with (a.out/'scores.jsonl').open('w',buffering=1) as f:
        for offset in range(0,len(rows),16):
            result,t=batch_score(rows[offset:offset+16],0);timing.append(t)
            for r in result:f.write(json.dumps(r)+'\n')
            done+=len(result);write(a.out/'PROGRESS.json',dict(rows_done=done,rows_total=len(rows),arm=a.arm,seconds=time.monotonic()-started))
    repeated=[r for r in rows if r['id'] in set(protocol['valid46_ids'])]
    if len(repeated)!=46:raise ValueError('VALID46_REPEAT_COUNT')
    with (a.out/'repeat_scores.jsonl').open('w',buffering=1) as f:
        for rep in (1,2):
            for offset in range(0,len(repeated),16):
                result,t=batch_score(repeated[offset:offset+16],rep);timing.append(t)
                for r in result:f.write(json.dumps(r)+'\n')
    write(a.out/'DONE.json',dict(complete=True,rows=done,arm=a.arm,input_sha256=prepared['eval_tokens_sha256'],
        eval_protocol_sha256=sha(a.data/'EVAL_PROTOCOL.json'),scores_sha256=sha(a.out/'scores.jsonl'),
        evaluator_sha256=sha(Path(__file__)),binding_sha256=sha(Path(__file__).with_name('v5_valid46_pipeline.py')),
        repeat_scores_sha256=sha(a.out/'repeat_scores.jsonl'),seconds=time.monotonic()-started,
        timing={k:sum(t[k] for t in timing) for k in timing[0]},valid46_measurements=3,
        adapter_sha256=sha(adapter/'adapter_model.safetensors') if adapter else None,source_modules=expected,
        unknown_preserves_accusation=True,all_admitted_scores_exact=True,apc=True,result_cache=False,
        scope='short source-quoted review plus exact score; not full best-ZIP integration',dropped_engine_kwargs=dropped))
    llm.llm_engine.engine_core.shutdown()
    sys.stdout.flush();sys.stderr.flush();os._exit(0)

def bootstrap(rows,gold,left,right):
    import numpy as np
    grouped=defaultdict(list)
    for i,r in enumerate(rows):
        group=r.get('group') or r.get('group_id') or r.get('conversation_id') or r['original_id'].split('::t')[0]
        grouped[group].append(i)
    keys=list(grouped);rng=np.random.default_rng(20261020);deltas=[]
    for _ in range(1000):
        indices=[i for k in rng.choice(len(keys),len(keys),replace=True) for i in grouped[keys[k]]]
        sampled=[rows[i] for i in indices];l=metrics(sampled,gold,[left[i] for i in indices]);r=metrics(sampled,gold,[right[i] for i in indices])
        deltas.append((r['f1']-l['f1'],r['fp']-l['fp'],r['tp']-l['tp']))
    return dict(groups=len(keys),resamples=1000,seed=20261020,
        difference_new_minus_base_95pct={k:list(map(float,np.quantile([d[i] for d in deltas],[.025,.975]))) for i,k in enumerate(('f1','fp','tp'))},
        independent_validation=False)

def analyse(data,out,lab):
    prepared=json.loads((data/'PREPARED.json').read_bytes());protocol=json.loads((data/'EVAL_PROTOCOL.json').read_bytes())
    if sha(data/'EVAL_INDEX.json')!=prepared['eval_index_sha256']:raise ValueError('GOLD_INDEX_DRIFT')
    index=[r for r in json.loads((data/'EVAL_INDEX.json').read_bytes())['rows'] if r['id'] in set(protocol['ids'])]
    gold={r['id']:r['label'] for r in index};arms={};result=dict(complete=True,cohorts={},stability={},
        status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',production_promoted=False,private_improvement_measured=False,
        threshold=0,threshold_search=False,quota_refill=False,independent_validation=False,
        input_sha256=prepared['eval_tokens_sha256'],eval_protocol_sha256=sha(data/'EVAL_PROTOCOL.json'))
    for arm in ('base','old','new'):
        folder=out/arm;receipt=json.loads((folder/'DONE.json').read_bytes())
        if not receipt['complete'] or receipt['rows']!=len(index) or sha(folder/'scores.jsonl')!=receipt['scores_sha256']:raise ValueError('ARM_COVERAGE')
        values=read(folder/'scores.jsonl');arms[arm]={r['id']:r for r in values}
        if len(values)!=len(index) or set(arms[arm])!=set(gold) or any(r['admitted'] and not r['exact'] for r in values):raise ValueError('ARM_IDS_OR_EXACT')
        if arm!='base':
            proof=json.loads((folder/'ADAPTER_BINDING.json').read_bytes())
            if len(proof)!=1 or not proof[0]['complete'] or proof[0]['covered_modules']!=receipt['source_modules']:raise ValueError('GPU_BINDING')
        repeats=read(folder/'repeat_scores.jsonl')
        if sha(folder/'repeat_scores.jsonl')!=receipt['repeat_scores_sha256'] or len(repeats)!=92:raise ValueError('REPEAT_DRIFT')
        deltas=[r['score']-arms[arm][r['id']]['score'] for r in repeats if r['admitted'] and arms[arm][r['id']]['admitted'] and r['score_input_sha256']==arms[arm][r['id']]['score_input_sha256']]
        result['stability'][arm]=dict(measurements=3,comparisons=92,identical_score_inputs=len(deltas),
            sd_identical_score_differences_over_sqrt2=statistics.stdev(deltas)/math.sqrt(2) if len(deltas)>1 else None,
            decision_flips=sum(keep_accusation(r)!=keep_accusation(arms[arm][r['id']]) for r in repeats),
            changed_review=sum(r['review']!=arms[arm][r['id']]['review'] for r in repeats),apc=True)
    baseline_dir=lab/'v5-35b-20261019/finish-v6/paired-native'
    receipt=json.loads((baseline_dir/'WORKER_DONE.json').read_bytes())
    if sha(baseline_dir/'scores.jsonl')!=receipt['scores_sha256']:raise ValueError('BASELINE_DRIFT')
    baseline={r['id']:r for r in read(baseline_dir/'scores.jsonl') if r['arm']=='base'}
    for cohort in ('real191','dev520','valid46'):
        rows=[r for r in index if cohort in r['cohorts']];hard={i for i,r in enumerate(rows) if r['hard']}
        original=decide(len(rows),hard,{i:baseline[r['id']]['score'] for i,r in enumerate(rows)},.4)
        result['cohorts'][cohort]=dict(rows=len(rows),baseline_scope='historical overall-only pool40; not best-ZIP MAX',
            original_overall_pool40=metrics(rows,gold,original),arms={})
        decisions={arm:[int(i in hard or keep_accusation(arms[arm][r['id']])) for i,r in enumerate(rows)] for arm in arms}
        for arm,labels in decisions.items():
            ref=decisions['base'];filtered=[int(y and z) for y,z in zip(labels,original)]
            result['cohorts'][cohort]['arms'][arm]=dict(verifier=metrics(rows,gold,labels),
                admitted=sum(arms[arm][r['id']]['admitted'] for r in rows),unknown=sum(not arms[arm][r['id']]['admitted'] for r in rows),
                removed_fp_vs_base=sum(z and not y and gold[r['id']]==0 for r,y,z in zip(rows,labels,ref)),
                lost_tp_vs_base=sum(z and not y and gold[r['id']]==1 for r,y,z in zip(rows,labels,ref)),
                added_fp_vs_base=sum(y and not z and gold[r['id']]==0 for r,y,z in zip(rows,labels,ref)),
                gained_tp_vs_base=sum(y and not z and gold[r['id']]==1 for r,y,z in zip(rows,labels,ref)),
                original_pool40_after_verifier=metrics(rows,gold,filtered),
                pool40_removed_fp=sum(z and not y and gold[r['id']]==0 for r,y,z in zip(rows,filtered,original)),
                pool40_lost_tp=sum(z and not y and gold[r['id']]==1 for r,y,z in zip(rows,filtered,original)))
        common=[r for r in rows if all(arms[arm][r['id']]['admitted'] for arm in arms)]
        result['cohorts'][cohort]['common_admitted_subset']=dict(rows=len(common),
            arms={arm:metrics(common,gold,[int(arms[arm][r['id']]['score']>0) for r in common]) for arm in arms},
            warning='post-generation diagnostic subset; not independent or the primary acceptance metric')
        result['cohorts'][cohort]['paired_group_bootstrap']=bootstrap(rows,gold,decisions['base'],decisions['new'])
    best=read(lab/'v5-35b-20261019/pipeline-valid46-v4/base/work/decisions.jsonl')
    hard={r['key'] for r in best if r['hard']};p70=decide(46,hard,{r['key']:r['ranked_by'] for r in best},.7)
    lookup={r['original_id']:r for r in index if 'valid46' in r['cohorts']};rows=[dict(id=lookup[r['id']]['id']) for r in best]
    result['best_pipeline_valid46_pool70']=dict(before=metrics(rows,gold,p70),arms={})
    for arm in arms:
        filtered=[int(z and (b['key'] in hard or keep_accusation(arms[arm][r['id']]))) for b,r,z in zip(best,rows,p70)]
        result['best_pipeline_valid46_pool70']['arms'][arm]=dict(metrics=metrics(rows,gold,filtered),
            removed_fp=sum(z and not y and gold[r['id']]==0 for r,y,z in zip(rows,filtered,p70)),
            lost_tp=sum(z and not y and gold[r['id']]==1 for r,y,z in zip(rows,filtered,p70)))
    tests={c:(result['cohorts'][c]['arms']['new']['verifier']['fp']<result['cohorts'][c]['arms']['base']['verifier']['fp']
        and result['cohorts'][c]['arms']['new']['lost_tp_vs_base']==0) for c in ('real191','dev520')}
    tests['valid46_no_new_tp_loss']=result['cohorts']['valid46']['arms']['new']['lost_tp_vs_base']==0
    # An equally harmful base verifier is not a safe deployment reference.
    for c in ('real191','dev520'):
        new=result['cohorts'][c]['arms']['new']
        tests[c+'_original_pool40_no_tp_loss']=new['pool40_lost_tp']==0
        tests[c+'_original_pool40_fewer_fp']=new['pool40_removed_fp']>0
    tests['best_pipeline_valid46_pool70_no_tp_loss']=result['best_pipeline_valid46_pool70']['arms']['new']['lost_tp']==0
    result['offline_gate']=dict(tests=tests,passed=all(tests.values()),promotion_approved=False)
    write(out/'RESULTS.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['worker'])
    for k in ('lab','data','new','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--arm',choices=['base','old','new'],required=True);p.add_argument('--deadline',type=float,required=True)
    worker(p.parse_args())
