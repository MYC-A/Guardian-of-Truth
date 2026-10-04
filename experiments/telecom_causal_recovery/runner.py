"""Prepare, single-pass run and offline replay of the isolated experiment."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'src'))
from experiments.telecom_causal_recovery.packets import variants,packet,catalog,execute_plan,extract,CASE
from experiments.telecom_causal_recovery.review import body,admit
from experiments.telecom_causal_recovery.transport import Client,read,save,bound
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import digest

INPUT=ROOT/'experiments/telecom_causal_recovery/fixtures/original_input.json'


def file_sha(path):return hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def hashes():
    files=list((ROOT/'experiments/telecom_causal_recovery').glob('*.py'))
    files+=list((ROOT/'experiments/research_v5').glob('*.py'))
    files+=[ROOT/'experiments/research_v3/pilot.py']+list((ROOT/'src').rglob('*.py'))
    return {str(p.relative_to(ROOT)).replace('\\','/'):file_sha(p) for p in sorted(files)}


def jobs():
    row=read(INPUT)
    if set(row)!={'id','prompt','response'} or row['id']!=CASE:raise ValueError('INPUT_SCHEMA_INVALID')
    copies=variants(row)
    return [(name,variant,arm,packet(copies[variant]['row'],arm)) for name,variant,arm in
            [('A','original','A'),('B','original','B'),('C','original','C'),
             ('control_read','read_only','B'),('control_future','future_contract','B'),('control_payment','bill_overdue','B')]]


def tokenizer(path,expected):
    from tokenizers import Tokenizer
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('TOKENIZER_CHANGED')
    return Tokenizer.from_file(str(path))


def prepare(out,tokenfile):
    if (out/'protocol.json').exists():raise ValueError('PREPARATION_EXISTS')
    pre=read(out/'provider_preflight.json')
    if pre['status']!='READY':raise ValueError('PREFLIGHT_NOT_READY')
    tok=tokenizer(tokenfile,pre['tokenizer_sha256'])
    row=read(INPUT);g,_,norms=extract(row)
    save(out/'original_normative_sources.json',norms)
    save(out/'counterfactual_diffs.json',{k:{'kind':v['kind'],'changes':v['changes']} for k,v in variants(row).items()})
    records=[]
    context_limit=pre['metadata']['max_context_length']
    for name,variant,arm,p in jobs():
        b=body(p);reservation=bound(b,tok)
        if reservation>context_limit:raise ValueError('PREPARED_CONTEXT_EXCEEDED')
        save(out/'packets'/(name+'.json'),p)
        save(out/'prepared_requests'/(name+'.json'),b)
        records.append(dict(name=name,variant=variant,arm=arm,packet_sha256=digest(p),request_sha256=digest(b),
                            reservation_tokens=reservation,source_sha256=p['source_sha256']))
    auto=catalog(row)
    save(out/'packets/AUTO_catalog.json',auto)
    auto_body=body(auto,plan=True)
    if bound(auto_body,tok)>context_limit:raise ValueError('AUTO_PLAN_CONTEXT_EXCEEDED')
    save(out/'prepared_requests/AUTO_plan.json',auto_body)
    p=dict(version='telecom-targeted-causal-recovery-v1',base_commit='ba2484218ff6597b3ff426762d22e582ff0ee13b',
        branch='research/telecom-causal-recovery-20261004',code_hashes=hashes(),input_sha256=file_sha(INPUT),
        original_source_sha256=g.store.source_sha256,requests=records,
        auto_plan_request_sha256=digest(auto_body),auto_plan_reservation=bound(auto_body,tok),
        model='ministral-14b-2512',temperature=0,max_tokens=1400,timeout=120,context_limit=context_limit,limits={'http':10,'tokens':60000},
        retries=0,fallback=False,tokenizer_sha256=pre['tokenizer_sha256'],tokenizer_file=str(tokenfile),
        reservation='2x full serialized body public tokenization + output cap + 1024 template slack; missing/malformed usage retains reservation and breaks further HTTP.',
        inference_reads_gold=False,retrieval='ORACLE_RETRIEVAL_ASSISTED except separately gated AUTO',
        scoring='Separate post-hoc causal audit; shape/ID admission is not entailment. BUDGET_STOP has no semantic decision.',
        controls='SYNTHETIC_COUNTERFACTUAL, not official labels; compare specific scope/expiry/payment causes.',
        automatic='Only after independently audited A cause recovery and remaining budget. One <=8-op plan, source-store execution, one final review; no oracle sources/other replies. All adaptive code/templates frozen here.')
    p['protocol_sha256']=digest(p);save(out/'protocol.json',p)
    print(json.dumps(dict(prepared=len(records),reservations=[(r['name'],r['reservation_tokens']) for r in records],
                          auto_plan_reservation=p['auto_plan_reservation'],inference_http=0)),flush=True)


def decode_record(record,failure,p,plan=False):
    result=dict(failure=failure,decision=None,reply=None,fully_admitted=False,code_proof=False)
    if record is None:return result
    result['provider_model']=record.get('provider_response',{}).get('model')
    if record['status']!='OK':result['failure']=record['status'];return result
    choices=record.get('provider_response',{}).get('choices')
    if not isinstance(choices,list) or len(choices)!=1:
        result['failure']='PROVIDER_CHOICES_INVALID';return result
    c=choices[0]
    if not isinstance(c,dict):result['failure']='PROVIDER_CHOICES_INVALID';return result
    if not isinstance(c.get('message'),dict):result['failure']='PROVIDER_MESSAGE_INVALID';return result
    reply,valid=decode_json(c['message'].get('content'))
    result['reply']=reply
    if c.get('finish_reason')!='stop' or not valid:
        result['failure']='UNFINISHED_OR_INVALID_REPLY';return result
    try:
        checked=admit(reply,p,plan)
        result.update(fully_admitted=True,decision=checked.get('decision'),admitted_reply=checked)
    except Exception as exc:
        result['failure']='ADMISSION:'+type(exc).__name__+':'+str(exc)
    return result


def verify(out,tokenfile):
    protocol=read(out/'protocol.json')
    if protocol['protocol_sha256']!=digest({k:v for k,v in protocol.items() if k!='protocol_sha256'}):raise ValueError('PROTOCOL_CHANGED')
    if protocol['code_hashes']!=hashes() or protocol['input_sha256']!=file_sha(INPUT):raise ValueError('SOURCE_CHANGED')
    return protocol,tokenizer(tokenfile or Path(protocol['tokenizer_file']),protocol['tokenizer_sha256'])


def run(out,live,tokenfile,auto=False):
    protocol,tok=verify(out,tokenfile)
    lock=out/'.run.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.close(fd)
    try:
        client=Client(out,protocol,tok,live)
        if not auto:
            results=[]
            for (name,variant,arm,p),seal in zip(jobs(),protocol['requests'],strict=True):
                b=body(p)
                if digest(b)!=seal['request_sha256'] or digest(p)!=seal['packet_sha256'] or bound(b,tok)!=seal['reservation_tokens']:
                    raise ValueError('REQUEST_CHANGED')
                if read(out/'packets'/(name+'.json'))!=p or read(out/'prepared_requests'/(name+'.json'))!=b:
                    raise ValueError('PREPARED_ARTIFACT_CHANGED')
                record,failure=client.ask(name,b)
                results.append(dict(name=name,variant=variant,arm=arm,request_sha256=digest(b),**decode_record(record,failure,p)))
                save(out/'predictions.json',results)
        else:
            gate=read(out/'auto_gate.json')
            predictions=read(out/'predictions.json')
            a=next(r for r in predictions if r['name']=='A')
            if gate.get('A_cause_correct') is not True or gate.get('A_request_sha256')!=a['request_sha256'] or not a['fully_admitted']:
                raise ValueError('AUTO_POSITIVE_GATE_NOT_MET')
            row=read(INPUT);p=catalog(row);b=body(p,plan=True)
            if digest(b)!=protocol['auto_plan_request_sha256'] or bound(b,tok)!=protocol['auto_plan_reservation']:
                raise ValueError('AUTO_PLAN_CHANGED')
            record,failure=client.ask('AUTO_plan',b)
            selected=decode_record(record,failure,p,plan=True)
            results=[dict(name='AUTO_plan',request_sha256=digest(b),**selected)]
            if selected['fully_admitted']:
                retrieved=execute_plan(row,selected['admitted_reply'])
                final=body(retrieved)
                save(out/'packets/AUTO_final.json',retrieved)
                save(out/'prepared_requests/AUTO_final.json',final)
                record,failure=client.ask('AUTO_final',final)
                results.append(dict(name='AUTO_final',request_sha256=digest(final),**decode_record(record,failure,retrieved)))
            save(out/'automatic_predictions.json',results)
        save(out/('auto_completion.json' if auto else 'completion.json'),dict(mode='LIVE' if live else 'OFFLINE_REPLAY',
            attempts=len(client.ledger),known_tokens=sum(v['known_tokens'] for v in client.ledger.values()),
            charged_tokens=sum(v['charged_tokens'] for v in client.ledger.values()),new_http=client.new_http,
            unknown_usages=sum(v['unknown_usage'] for v in client.ledger.values()),statuses=Counter(v['status'] for v in client.ledger.values())))
    finally:
        lock.unlink()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','run','replay','auto','auto_replay'])
    p.add_argument('--out',type=Path,required=True);p.add_argument('--tokenizer-file',type=Path)
    a=p.parse_args()
    if a.phase=='prepare':prepare(a.out,a.tokenizer_file)
    else:run(a.out,a.phase in ('run','auto'),a.tokenizer_file,a.phase in ('auto','auto_replay'))
