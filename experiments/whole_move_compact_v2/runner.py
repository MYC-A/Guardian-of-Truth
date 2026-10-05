"""Bounded development follow-up; v1 is immutable, exact baseline cache reused."""
import argparse
import hashlib
import importlib.metadata
from pathlib import Path
import subprocess
import json

from experiments.whole_move_v1 import runner as parent
from experiments.hybrid_mechanisms.transport import Client, read, save, serialized, bound, preflight
from experiments.retrieval_bakeoff_v1.runner import decode as baseline_decode
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import digest
from . import reviewer
from .bridge import evaluate

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/whole_move_compact_v2'
MODEL=parent.MODEL


def code_hashes():
    result=parent.code_hashes()
    result.update({p.relative_to(ROOT).as_posix():parent.fingerprint(p)
                   for p in Path(__file__).parent.glob('*.py')})
    return result


def prepare():
    if (OUT/'protocol.json').exists():verify();print('ALREADY_FROZEN');return
    pp=parent.verify()
    old_jobs=read(parent.OUT/'jobs.json'); old_decisions=read(parent.OUT/'model/decisions.json')
    originals=[j for j in old_jobs if j['arm']=='BASELINE']
    cached={d['id']:d for d in old_decisions if d['arm']=='BASELINE'}
    if len(cached)!=len(originals):raise ValueError('BASELINE_INVENTORY_INCOMPLETE')
    # Read-only raw/ledger/wire verification; never call the parent's report
    # writer or overwrite any v1 outputs, even with identical bytes.
    parent_client=Client(parent.OUT/'model',pp,live=False)
    for j in originals:
        rec,failure=parent_client.ask(j['id']+'/BASELINE','mistral',j['request'])
        derived=baseline_decode(rec,failure,j['packet'])
        if not rec or rec.get('actual_model')!=MODEL:raise ValueError('BASELINE_MODEL_MISMATCH')
        if any(cached[j['id']].get(k)!=v for k,v in derived.items()):raise ValueError('BASELINE_RAW_REPLAY_DIFFERS')
    if parent_client.new_http:raise ValueError('BASELINE_REPLAY_MUST_NOT_INFER')
    jobs=[]; baseline=[]
    for j in originals:
        req=reviewer.body(j['packet'],'mistral',MODEL)
        req['max_tokens']=3600
        if bound(req)>262144:raise ValueError('CONTEXT_STOP_NO_TRUNCATION')
        jobs.append(dict(id=j['id'],cohort=j['cohort'],packet=j['packet'],request=req,
                         wire_sha256=hashlib.sha256(serialized(req)).hexdigest()))
        d=cached[j['id']]
        if d['wire_sha256']!=j['wire_sha256']:raise ValueError('BASELINE_REQUEST_CHANGED')
        baseline.append(dict(d,origin_protocol=pp['protocol_sha256']))
    save(OUT/'jobs.json',jobs);save(OUT/'baseline_cache.json',baseline)
    inputs={r['id']:r for r in read(parent.OUT/'inputs.json')}
    bridges=[dict(id=d['id'],cohort=d['cohort'],**evaluate(inputs[d['id']],d.get('reply'),interface='baseline'))
             for d in baseline]
    for d,b in zip(baseline,bridges):
        expected='ERROR' if b['mechanical']['mechanically_established_error'] else d['decision']
        if b['decision']!=expected:raise ValueError('BRIDGE_DIFFERS_FROM_MATCHED_OVERLAY')
    save(OUT/'baseline_bridge.json',bridges)
    save(OUT/'evaluation_only.json',read(parent.OUT/'evaluation_only.json'))
    save(OUT/'mechanical.json',read(parent.OUT/'mechanical_offline.json'))
    files={n:parent.fingerprint(OUT/n) for n in ('jobs.json','baseline_cache.json','baseline_bridge.json','evaluation_only.json','mechanical.json')}
    protocol=dict(version='whole-move-compact-v2',source_commit=subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(), code_hashes=code_hashes(),file_hashes=files,
        parent_protocol=pp['protocol_sha256'],
        parent_files={n:parent.fingerprint(parent.OUT/n) for n in ('protocol.json','jobs.json','model/decisions.json','model/ledger.json')},
        packages={n:importlib.metadata.version(n) for n in ('pydantic','numpy','pandas','pyarrow','bm25s')},
        providers={'mistral':dict(model=MODEL,context_limit=262144)},limits=dict(http=len(jobs),tokens=140000),
        planned_requests=len(jobs), max_tokens=3600,temperature=0,
        design='Development follow-up after observed v1 copy/truncation/semantic failures. Same ALL18 cases/FULLpackets, no subset selection. Exact baseline request hashes/cache reused, no new baseline HTTP.',
        contract='Code owns source text/native metadata citations; model emits source references and compact typed per-target norm hypotheses. This relaxes literal-copy admission, does not prove interpretation; independent cause audit required.',
        arms=['BASELINE_CACHE','BASELINE_PLUS_MECHANICAL','COMPACT','COMPACT_PLUS_MECHANICAL'],
        interpretation='Known6 original rows +12author-controlled fresh contrasts already observed in v1; not independentholdout, not all46modelF1.',
        unknown_binary_mapping=0,technical_binary_mapping=0,retries=0,production_promotion=False)
    protocol['protocol_sha256']=digest(protocol);save(OUT/'protocol.json',protocol)
    print(json.dumps(dict(status='FROZEN_FOLLOWUP_NO_NEW_HTTP',requests=len(jobs),protocol=protocol['protocol_sha256'])))


def verify():
    pp=parent.verify();p=read(OUT/'protocol.json')
    if digest({k:v for k,v in p.items() if k!='protocol_sha256'})!=p['protocol_sha256']:raise ValueError('PROTOCOL_CHANGED')
    if pp['protocol_sha256']!=p['parent_protocol']:raise ValueError('PARENT_PROTOCOL_CHANGED')
    if p['code_hashes']!=code_hashes():raise ValueError('CODE_CHANGED')
    if any(parent.fingerprint(OUT/n)!=h for n,h in p['file_hashes'].items()):raise ValueError('DATA_CHANGED')
    if any(parent.fingerprint(parent.OUT/n)!=h for n,h in p['parent_files'].items()):raise ValueError('PARENT_RESULTS_CHANGED')
    if any(importlib.metadata.version(n)!=v for n,v in p['packages'].items()):raise ValueError('PACKAGES_CHANGED')
    return p


def decode(record,failure,packet):
    if failure or not record or record.get('status')!='OK':return dict(decision=None,failure=failure or (record or {}).get('status','MISSING_RECORD'))
    data=record.get('provider_response');cs=data.get('choices') if isinstance(data,dict) else None
    if not isinstance(cs,list) or len(cs)!=1 or not isinstance(cs[0],dict) or not isinstance(cs[0].get('message'),dict):
        return dict(decision=None,failure='PROVIDER_SHAPE_INVALID')
    if cs[0].get('finish_reason')!='stop':return dict(decision=None,failure='INVALID_OR_UNFINISHED_JSON')
    value,ok=decode_json(cs[0]['message'].get('content'))
    if not ok:return dict(decision=None,failure='INVALID_JSON')
    try:
        reply=reviewer.admit(value,packet)
        return dict(decision=reply['decision'],admitted=reply,parsed=value,failure=None)
    except (ValueError,TypeError,KeyError) as exc:return dict(decision=None,parsed=value,failure=str(exc)[:240])


def run(live=False):
    p=verify();client=Client(OUT/'model',p,live=live)
    if live:
        pf=preflight('mistral',MODEL);save(OUT/'model/preflight.json',pf)
        if pf['status']!='READY':print(json.dumps(pf));return
    result=[];model_stop=False
    for index,j in enumerate(read(OUT/'jobs.json')):
        rec,failure=(None,'MODEL_IDENTITY_STOP_NO_RETRY') if model_stop else client.ask(j['id']+'/COMPACT','mistral',j['request'])
        d=decode(rec,failure,j['packet'])
        if rec and rec.get('actual_model')!=MODEL:d=dict(d,decision=None,failure='ACTUAL_MODEL_MISMATCH');model_stop=True
        result.append(dict(index=index,id=j['id'],cohort=j['cohort'],wire_sha256=j['wire_sha256'],
            request_sha256=(rec or {}).get('request_sha256'),usage=((rec or {}).get('provider_response') or {}).get('usage'),**d))
        save(OUT/'model/decisions.json',result);save(OUT/'model/budget.json',client.summary())
        print(json.dumps({k:result[-1].get(k) for k in ('index','cohort','decision','failure')}),flush=True)
    print(json.dumps(client.summary()))


def report():
    p=verify();jobs=read(OUT/'jobs.json');ds=read(OUT/'model/decisions.json')
    if len(ds)!=len(jobs) or len({d['id'] for d in ds})!=len(ds):raise ValueError('INCOMPLETE_OR_DUPLICATE_RESULTS')
    client=Client(OUT/'model',p,live=False)
    for d,j in zip(ds,jobs):
        if d['id']!=j['id'] or d['wire_sha256']!=j['wire_sha256']:raise ValueError('REQUEST_CHANGED')
        if d.get('request_sha256') is None:
            if d['decision'] is not None or d.get('usage') is not None or not d.get('failure'):raise ValueError('INVALID_SKIPPED_RESULT')
            continue
        rec,failure=client.ask(j['id']+'/COMPACT','mistral',j['request']);derived=decode(rec,failure,j['packet'])
        if rec and rec.get('actual_model')!=MODEL:derived=dict(derived,decision=None,failure='ACTUAL_MODEL_MISMATCH')
        if any(d.get(k)!=v for k,v in derived.items()):raise ValueError('RAW_REPLAY_DIFFERS')
    if client.new_http:raise ValueError('REPORT_MUST_NOT_INFER')
    gold={d['id']:d for d in read(OUT/'evaluation_only.json')}
    mech={d['id']:d for d in read(OUT/'mechanical.json')}
    baseline=read(OUT/'baseline_cache.json');summary=[]
    for cohort in ('valid_known','fresh_authored'):
      for arm in p['arms']:
        selected=[d for d in (baseline if arm.startswith('BASELINE') else ds) if d['cohort']==cohort]
        tp=fp=fn=tn=unk=tech=0;changed=[]
        for d in selected:
            decision=d['decision']
            if arm.endswith('PLUS_MECHANICAL') and mech[d['id']]['mechanically_established_error']:
                if decision!='ERROR':changed.append(d['id'])
                decision='ERROR'
            y=gold[d['id']]['label'];pred=decision=='ERROR'
            tp+=bool(y==1 and pred);fp+=bool(y==0 and pred);fn+=bool(y==1 and not pred);tn+=bool(y==0 and not pred)
            unk+=decision=='UNKNOWN';tech+=decision is None
        summary.append(dict(cohort=cohort,arm=arm,n=len(selected),tp=tp,fp=fp,fn=fn,tn=tn,
            f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,unknown=unk,technical=tech,
            underlying_technical=sum(d['decision'] is None for d in selected),underlying_unknown=sum(d['decision']=='UNKNOWN' for d in selected),
            mechanical_changed_cases=changed,baseline_new_http=0,
            admitted=sum(d['decision'] is not None for d in selected)))
    save(OUT/'model/summary.json',summary);print(json.dumps(summary,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','run','report']);ap.add_argument('--live',action='store_true');a=ap.parse_args()
    {'prepare':prepare,'run':lambda:run(a.live),'report':report}[a.stage]()
