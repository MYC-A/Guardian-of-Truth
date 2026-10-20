"""Independent offbox replay of primary context, actual token inputs and vetoes."""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import tarfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v8_quote_contract import admit_review
from guardian_truth.judge.prompting import system_block
from scripts.v7_prepare import reasoning_text


def digest(value):return hashlib.sha256(value).hexdigest()
def wire(value):return digest(json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode())


def metric(rows,labels):
    tp=sum(r['label']==1 and y==1 for r,y in zip(rows,labels));fp=sum(r['label']==0 and y==1 for r,y in zip(rows,labels))
    fn=sum(r['label']==1 and not y for r,y in zip(rows,labels));tn=len(rows)-tp-fp-fn
    return dict(tp=tp,fp=fp,fn=fn,tn=tn,precision=tp/(tp+fp) if tp+fp else 0,
        recall=tp/(tp+fn) if tp+fn else 0,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)


def replay_arm(inputs,records,tok,audit,binding=None):
    if [r['id'] for r in inputs]!=[r['id'] for r in records] or [r['position'] for r in inputs]!=[r['position'] for r in records]:raise ValueError('VERIFIER_ORDER_OR_COVERAGE')
    keep={};expected=[]
    for offset in range(0,len(inputs),64):
        batch=inputs[offset:offset+64];scoring=[]
        valid=[r for r in batch if not r['oversized']]
        if valid:expected.append((192,wire([dict(prompt_token_ids=r['ids']) for r in valid]),len(valid)))
        for r,value in zip(batch,records[offset:offset+64]):
            if r['input_sha256']!=value['input_sha256']:raise ValueError('VERIFIER_SOURCE_HASH')
            if r['oversized']:
                admitted=False
                if value['admitted'] or value['status']!='OVERSIZED':raise ValueError('OVERSIZED_ADMISSION')
            else:
                admitted,status,support=admit_review(value['review'],r['source_policy'],value['status']=='TRUNCATED')
                if admitted!=value['admitted'] or status!=value['status'] or support!=value['source_support']:raise ValueError('QUOTE_ADMISSION_REPLAY')
            if admitted:
                text=tok.decode(r['ids'],skip_special_tokens=False)+value['review'].strip()+'\nVerdict:'
                ids=tok.encode(text,add_special_tokens=False).ids
                if ids[:len(r['ids'])]!=r['ids'] or len(ids)>=49152:raise ValueError('FINAL_INPUT_BOUNDARY')
                if digest(json.dumps(ids,separators=(',',':')).encode())!=value['score_input_sha256']:raise ValueError('FINAL_TOKEN_HASH')
                if not value['exact'] or value['score'] is None or not math.isfinite(value['score']):raise ValueError('MISSING_EXACT_FINAL')
                scoring.append(dict(prompt_token_ids=ids))
            elif value['exact'] or value['score'] is not None:raise ValueError('UNKNOWN_HAS_DECISIVE_SCORE')
            keep[r['position']]=not admitted or value['score']>0
        if scoring:expected.append((1,wire(scoring),len(scoring)))
    # A probe may precede quality; all actual quality calls must then match.
    cursor=0
    while cursor<len(audit) and audit[cursor]['max_tokens']==1 and audit[cursor]['prompts']==1:cursor+=1
    actual=[(r['max_tokens'],r['inputs_sha256'],r['prompts']) for r in audit[cursor:]]
    if expected!=actual or any(r['prompts']!=r['outputs'] for r in audit):raise ValueError('ACTUAL_GENERATION_INPUT_RECEIPTS')
    if binding is not None:
        if len(binding)!=1:raise ValueError('ADAPTER_PROOF_COUNT')
        p=binding[0]
        if not p['complete'] or p['expected_modules']!=100 or p['covered_modules']!=100 or p['errors'] or not p['checks']:
            raise ValueError('ADAPTER_COVERAGE')
        if any(not c['a_equal'] or not c['b_equal'] for c in p['checks']):raise ValueError('ADAPTER_GPU_TENSORS')
    return keep


def run(a):
    from tokenizers import Tokenizer
    tok=Tokenizer.from_file(str(a.tokenizer));csv.field_size_limit(2**31-1)
    if digest(a.tokenizer.read_bytes())!='5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42':raise ValueError('PINNED_TOKENIZER_DRIFT')
    with tarfile.open(a.run) as t:
        def raw(n):return t.extractfile('evaluation-v12/'+n).read()
        def data(n,lines=False):return [json.loads(x) for x in raw(n).splitlines()] if lines else json.loads(raw(n))
        done=data('DONE.json');onbox=data('RESULTS.json')
        if not done['complete'] or digest(raw('RESULTS.json'))!=done['results_sha256']:raise ValueError('INCOMPLETE_TRANSFER')
        pin=data('LABEL_SOURCE_PIN_BEFORE_JOIN.json')
        if digest(raw('labels_for_offbox.jsonl'))!=pin['sha256']:raise ValueError('GOLD_SOURCE_DRIFT')
        rows=data('labels_for_offbox.jsonl',True);pred=list(csv.DictReader(io.StringIO(raw('predictions.csv').decode())))
        if len(rows)!=1893 or [r['id'] for r in rows]!=[r['id'] for r in pred]:raise ValueError('GOLD_JOIN')
        decisions=data('work/decisions.jsonl',True);hard={i for i,r in enumerate(decisions) if r['hard']}
        before=[int(r['label']) for r in pred];inputs=data('verifier_inputs.jsonl',True);frozen=data('CONTROL_FROZEN.json')
        if digest(raw('predictions.csv'))!=frozen['predictions_sha256'] or digest(raw('verifier_inputs.jsonl'))!=frozen['verifier_inputs_sha256']:raise ValueError('CONTROL_FREEZE')
        if [r['position'] for r in inputs]!=[i for i,y in enumerate(before) if y]:raise ValueError('CANDIDATE_POOL')
        spools=[m for m in t.getmembers() if m.name.startswith('evaluation-v12/work/primary-inputs-') and m.name.endswith('.jsonl')]
        if len(spools)!=1:raise ValueError('PRIMARY_SPOOL')
        rawspool=t.extractfile(spools[0]).read();spool={r['key']:r for r in [json.loads(x) for x in rawspool.splitlines()]}
        if digest(rawspool)!=frozen['primary_spool_sha256'] or len(spool)!=1893:raise ValueError('PRIMARY_FREEZE')
        source=list(csv.DictReader(io.StringIO(raw('inputs.csv').decode())))
        for i,row in enumerate(source):
            s=spool[i];text=s['text'];ids=tok.encode(text,add_special_tokens=False).ids
            if digest(text.encode())!=s['model_input_sha256'] or digest(json.dumps(ids).encode())!=s['input_token_sha256']:
                raise ValueError('ACTUAL_PRIMARY_TOKEN_HASH')
            if digest(json.dumps([row['prompt'],row['response']],ensure_ascii=False).encode())!=s['row_sha256']:raise ValueError('PRIMARY_ROW_BINDING')
        for r in inputs:
            text=reasoning_text(spool[r['position']]['text']);ids=tok.encode(text,add_special_tokens=False).ids
            policy=system_block(spool[r['position']]['text'].split('<transcript>\n',1)[1].split('\n</transcript>',1)[0])
            if ids!=r['ids'] or digest(text.encode())!=r['input_sha256'] or policy!=r['source_policy']:raise ValueError('SOURCE_VERIFIER_TOKEN_BINDING')
            if r['oversized']!=(len(ids)>48700):raise ValueError('OVERSIZE_FLAG')
        # Raw overall/final values independently reconstruct the exact MAX quota.
        from scripts import judge_submission as primary
        from guardian_truth.judge.decision import decide
        import tempfile
        with tempfile.TemporaryDirectory(prefix='guardian-v12-audit-') as temp:
            scorepath=Path(temp)/'scores.jsonl';scorepath.write_bytes(raw('work/scores.jsonl'))
            overall,missing,inexact,events=primary.read_scores(scorepath,exact_only=True)
            final=primary.read_review_scores(scorepath,isolate_duplicates=True)
        if len(overall)!=1893 or len(final)!=1893 or missing or inexact or 'done' not in events:raise ValueError('EXACT_CONTROL_COVERAGE')
        if decide(1893,hard,{i:max(overall[i],final[i]) for i in range(1893)},.4)!=before:raise ValueError('BASELINE_MAX_REPLAY')
        result=dict(complete=True,rows=1893,candidates=len(inputs),baseline=metric(rows,before),arms={},domains={},
            archive_sha256=digest(a.run.read_bytes()),tokenizer_sha256=digest(a.tokenizer.read_bytes()),
            actual_primary_and_final_tokens_reconstructed_offbox=True,gpu_adapter_tensor_proof_replayed=True,
            raw_logits_available_offbox=False,exact_log_odds_from_checked_producer_contract=True,
            independent_validation=False,private_improvement_measured=False,production_promoted=False)
        filtered={}
        for arm in ('base','new'):
            receipt=data(arm+'/DONE.json');records=data(arm+'/scores.jsonl',True)
            if digest(raw(arm+'/scores.jsonl'))!=receipt['scores_sha256']:raise ValueError('ARM_FREEZE')
            audit=data(arm+'/generation_audit.jsonl',True)
            if any(r['adapter_applied']!=(arm=='new') for r in audit):raise ValueError('ADAPTER_ARM_DRIFT')
            keep=replay_arm(inputs,records,tok,audit,data(arm+'/ADAPTER_BINDING.json') if arm=='new' else None)
            after=[int(bool(y) and (i in hard or keep[i])) if y else 0 for i,y in enumerate(before)];filtered[arm]=after
            result['arms'][arm]=dict(metrics=metric(rows,after),
                removed_fp=sum(x and not y and not r['label'] for r,x,y in zip(rows,before,after)),
                lost_tp=sum(x and not y and r['label'] for r,x,y in zip(rows,before,after)),
                admitted=sum(r['admitted'] for r in records))
            if result['arms'][arm]!=onbox['arms'][arm]:raise ValueError('ONBOX_ARM_DISAGREEMENT')
        if result['baseline']!=onbox['baseline']:raise ValueError('ONBOX_BASELINE_DISAGREEMENT')
        for domain in sorted({r['domain'] for r in rows}):
            idx=[i for i,r in enumerate(rows) if r['domain']==domain];subset=[rows[i] for i in idx]
            result['domains'][domain]=dict(rows=len(idx),baseline=metric(subset,[before[i] for i in idx]),
                arms={k:metric(subset,[v[i] for i in idx]) for k,v in filtered.items()})
    a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(complete=True,out=str(a.out))))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('run','tokenizer','out'):p.add_argument('--'+k,type=Path,required=True)
    run(p.parse_args())
