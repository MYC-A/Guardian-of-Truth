"""Verify frozen candidate inputs, fresh outputs and metrics from exported archives."""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import sys
import tarfile
import tempfile
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v8_replay_report import member,sha
from scripts.v8_quote_contract import admit_review
from scripts.v11_candidate_fresh import analyse
from scripts.v5_valid46_pipeline import metrics
from scripts.v7_evaluate import keep_accusation


def blob(archive,name):
    with tarfile.open(archive) as t:return t.extractfile(name).read()


def run(a):
    start=member(a.fresh,'evaluation-v11/START.json');done=member(a.fresh,'evaluation-v11/DONE.json')
    result=member(a.fresh,'evaluation-v11/RESULTS.json')
    if not done['complete'] or done['passes']!=3 or done['rows_per_pass']!=208:raise ValueError('INCOMPLETE_FRESH_CHECK')
    if hashlib.sha256(blob(a.fresh,'evaluation-v11/RESULTS.json')).hexdigest()!=done['results_sha256']:raise ValueError('RESULT_HASH')
    raw_inputs=blob(a.fresh,'evaluation-v11/inputs.jsonl')
    if hashlib.sha256(raw_inputs).hexdigest()!=start['input_sha256']:raise ValueError('FROZEN_INPUT_HASH')
    inputs=[json.loads(x) for x in raw_inputs.splitlines()];byid={r['id']:r for r in inputs}
    original={r['id']:r for r in member(a.original,'prepared-v1/eval_tokens.jsonl',True)}
    if len(inputs)!=208 or len(byid)!=208 or any(set(r)!={'id','ids','tokens','text_sha256','source_policy'} or r!=original[r['id']] for r in inputs):raise ValueError('ORIGINAL_PREFIX_OR_POLICY_DRIFT')
    pred_bytes=blob(a.baseline,'evaluation-v10/predictions.csv')
    if hashlib.sha256(pred_bytes).hexdigest()!=start['v10_predictions_sha256']:raise ValueError('BASELINE_CANDIDATE_DRIFT')
    pred=list(csv.DictReader(io.StringIO(pred_bytes.decode('utf-8'))))
    if [r['id'] for r in inputs]!=['compli_dev::'+r['id'] for r in pred if int(r['label'])]:raise ValueError('CANDIDATE_ID_ORDER')
    binding=member(a.fresh,'evaluation-v11/ADAPTER_BINDING.json')
    if len(binding)!=1 or not binding[0]['complete'] or binding[0]['covered_modules']!=100:raise ValueError('FULL_BINDING')
    passes=[member(a.fresh,f'evaluation-v11/pass-{i}.jsonl',True) for i in range(3)]
    for number,values in enumerate(passes):
        if len(values)!=208 or [r['id'] for r in values]!=list(byid):raise ValueError('PASS_COVERAGE_OR_ORDER')
        for r in values:
            if r['repeat']!=number:raise ValueError('REPEAT_IDENTITY')
            source=byid[r['id']]
            if r['input_sha256']!=source['text_sha256']:raise ValueError('FRESH_SOURCE_HASH')
            admitted,status,support=admit_review(r['review'],source['source_policy'],r['status']=='TRUNCATED')
            if (admitted,status,support)!=(r['admitted'],r['status'],r['source_support']):raise ValueError('SOURCE_ADMISSION_REPLAY')
            if admitted and (not r['exact'] or not math.isfinite(r['score'])):raise ValueError('INEXACT_ADMITTED_FINAL')
    with tempfile.TemporaryDirectory(prefix='guardian-fresh-offbox-') as temp:
        root=Path(temp);source=root/'source';source.mkdir()
        (source/'EVAL_INDEX.json').write_bytes(blob(a.data,'prepared-v1/EVAL_INDEX.json'))
        for dest,raw in (
            ('v10-full-profile-batch64-20261020/evaluation-v10/work/decisions.jsonl',blob(a.baseline,'evaluation-v10/work/decisions.jsonl')),
            ('v8-json-quote-replay-20261020/evaluation-v8/new/scores.jsonl',blob(a.verifier,'evaluation-v8/new/scores.jsonl'))):
            path=root/dest;path.parent.mkdir(parents=True);path.write_bytes(raw)
        recalculated=analyse(SimpleNamespace(lab=root),source,pred,passes)
    if any(result[k]!=v for k,v in recalculated.items()):raise ValueError('OFFBOX_METRIC_DISAGREEMENT')
    audit=member(a.fresh,'evaluation-v11/generation_audit.jsonl',True)
    if any(not r['adapter_applied'] or r['outputs']!=r['prompts'] for r in audit):raise ValueError('LORA_CALL_COVERAGE')
    review_prompts=sum(r['prompts'] for r in audit if r['max_tokens']==192)
    if review_prompts!=624:raise ValueError('FRESH_REVIEW_CALL_COUNT')
    stability=[]
    for values in passes[1:]:
        delta=[r['score']-first['score'] for first,r in zip(passes[0],values)
            if first['admitted'] and r['admitted'] and first['score_input_sha256']==r['score_input_sha256']]
        stability.append(dict(changed_reviews=sum(x['review']!=y['review'] for x,y in zip(passes[0],values)),
            changed_admission=sum(x['admitted']!=y['admitted'] for x,y in zip(passes[0],values)),
            identical_final_inputs=len(delta),sd_differences_over_sqrt2=statistics.stdev(delta)/(2**.5) if len(delta)>1 else None))
    report=dict(complete=True,archives_sha256={k:sha(getattr(a,k)) for k in ('fresh','baseline','verifier','data','original')},
        original_inputs_verified=True,source_admission_replayed=True,gpu_source_modules=100,
        fresh_review_prompts=review_prompts,model_outputs_cache=False,result=result,repeat_diagnostics=stability,
        full_baseline_seconds=member(a.baseline,'evaluation-v10/DONE.json')['seconds'],
        time_caveat='Separate stages with warm compiler cache; not a packaged cold-start 30-minute run')
    metadata=[r for r in member(a.data,'prepared-v1/EVAL_INDEX.json')['rows'] if 'dev520' in r['cohorts']]
    predmap={r['id']:int(r['label']) for r in pred}
    hard={r['id'] for r in member(a.baseline,'evaluation-v10/work/decisions.jsonl',True) if r['hard']}
    domains={}
    for domain in sorted({r['domain'] for r in metadata}):
        subset=[r for r in metadata if r['domain']==domain];gold={r['id']:r['label'] for r in subset}
        before=[predmap[r['original_id']] for r in subset];item=dict(before=metrics(subset,gold,before),passes=[])
        for values in passes:
            mapped={r['id']:r for r in values}
            after=[int(bool(y) and (r['original_id'] in hard or keep_accusation(mapped[r['id']]))) if y else 0 for r,y in zip(subset,before)]
            item['passes'].append(dict(metrics=metrics(subset,gold,after),
                removed_fp=sum(x and not y and gold[r['id']]==0 for r,x,y in zip(subset,before,after)),
                lost_tp=sum(x and not y and gold[r['id']]==1 for r,x,y in zip(subset,before,after))))
        domains[domain]=item
    report['domains']=domains
    a.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(complete=True,out=str(a.out),sha256=sha(a.out))))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('fresh','baseline','verifier','data','original','out'):p.add_argument('--'+key,type=Path,required=True)
    run(p.parse_args())
