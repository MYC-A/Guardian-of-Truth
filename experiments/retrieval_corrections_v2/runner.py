"""Frozen, bounded paired diagnostic: old/new packet selection, unchanged reviewer.

No synthetic gold, valid labels or reference spans enter reviewer requests.
Historical C1 P2 is deliberately replayed without the corrected guard to measure
the old defect; these are SECOND-STAGE diagnostics, not final C1 pipeline scores.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

from experiments.evidence_packer_v2.llm_eval import rows, review_packet
from experiments.hybrid_mechanisms.interfaces import body
from experiments.hybrid_mechanisms.transport import Client, preflight, read, save, serialized
from experiments.retrieval_bakeoff_v1.runner import decode
from experiments.retrieval_bakeoff_v1.corpus import build_corpus
from guardian_truth.evidence_packer import pack, PackerConfig
from guardian_truth.multipacket import complementary, unify
from guardian_truth.source_search.store import digest
from .offline import ROOT, OUT, BASE, FC_BASE, MODEL, historical


def hashes():
    paths = list(Path(__file__).parent.glob('*.py')) + list((ROOT/'src/guardian_truth').rglob('*.py'))
    for directory in ('src/guardian_truth/evidence_packer','src/guardian_truth/coverage_v2',
                      'src/guardian_truth/multipacket','src/guardian_truth/source_search',
                      'experiments/hybrid_mechanisms','experiments/retrieval_bakeoff_v1'):
        paths += list((ROOT/directory).glob('*.py'))
    paths += [ROOT/'experiments/evidence_packer_v2/llm_eval.py',ROOT/'scripts/compare_u2_facet_cover.py',
              ROOT/'src/guardian_truth/parsing.py', ROOT/'src/guardian_truth/source_store.py',
              ROOT/'src/guardian_truth/policy_table/schema.py', ROOT/'src/guardian_truth/source_search/tool_catalog.py',
              ROOT/'experiments/research_v3/pilot.py']
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
            for p in sorted(set(paths)) if p.exists()}


def delta_rank(d):
    def quality(s):
        if not s: return (0,0)
        return (int(s['complete_evidence_set_success']),sum(s['categories'][k]['found'] for k in ('policy','history')))
    old,new=quality(d['old_score']),quality(d['new_score'])
    return (-(new[0]-old[0]),-(new[1]-old[1]),d['id'])


def prepare():
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('HISTORICAL_BASELINE_REQUIRES_HASH_SEED_0')
    if (OUT/'protocol.json').exists():
        verify(); print('ALREADY_FROZEN'); return
    old,oldfc=historical()
    data={r['id']:r for r in rows()}
    deltas=read(OUT/'offline_deltas.json')
    jobs=[]; selection=[]
    def pair(cohort,family,row,packets,label,explanation=None):
        pid=f'{cohort}/{family}/{row["id"]}'
        selection.append(dict(pair_id=pid,id=row['id'],cohort=cohort,family=family,label=label,
                              explanation=explanation))
        for arm,p in zip(('OLD','NEW'),packets):
            rp=review_packet(p,p.get('mode')=='FULL_INPUT')
            req=body(rp,'mistral',MODEL,interface='I4')
            jobs.append(dict(pair_id=pid,id=row['id'],cohort=cohort,family=family,arm=arm,
                packet=rp,request=req,wire_sha256=hashlib.sha256(serialized(req)).hexdigest(),
                source_sha256=p.get('source_sha256') or build_corpus({k:row[k] for k in ('prompt','response')}).store.source_sha256,
                request_bytes=len(serialized(req)),packet_failure=p.get('failure')))
    for family in ('U2','FC'):
        candidates=[d for d in deltas if d['budget']==20000 and d['family']==family and d['source_changed']
                    and max(d['old_bytes'],d['new_bytes'])<=30000]
        chosen=[]
        for label,n in ((1,2),(0,1)):
            chosen += sorted([d for d in candidates if d['label']==label],key=delta_rank)[:n]
        for d in chosen:
            row=data[d['id']];src={k:row[k] for k in ('prompt','response')}
            packets=(old.pack(src,old.PackerConfig(budget_bytes=20000)),pack(src,PackerConfig(budget_bytes=20000))) if family=='U2' else (
                oldfc.select_evidence(build_corpus(src),budget_bytes=20000),
                __import__('guardian_truth.coverage_v2',fromlist=['select_evidence']).select_evidence(build_corpus(src),budget_bytes=20000))
            if any(p.get('failure') for p in packets): raise ValueError('SELECTED_PACKET_FAILURE')
            pair('valid_known',family,row,packets,row['label'],row['explanation'])
    synroot=ROOT/'outputs/multipacket_v1/suite_syn_m1'
    sgold=read(synroot/'GOLD_eval_only.json')
    candidates=[]
    for line in (synroot/'inputs.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line);A=pack(row,PackerConfig(budget_bytes=20000))
        if A['mode']=='FULL_INPUT':continue
        p=complementary(row,A,shared_normative=False);q=complementary(row,A,shared_normative=True)
        if p.get('failure') or q.get('failure'):continue
        if any(r['category']=='POLICY' for r in p['read_sources']):continue
        if not any(r['category']=='POLICY' for r in q['read_sources']):continue
        if not (set(q['selected_units'])-set(A['selected_units'])):continue
        if max(len(serialized(body(review_packet(x,False),'mistral',MODEL))) for x in (p,q))>30000:continue
        candidates.append((row,p,q,sgold[row['id']]))
    chosen=[]
    for label,n in ((1,2),(0,1)):
        chosen += sorted([c for c in candidates if c[3]['label']==label],key=lambda c:c[0]['id'])[:n]
    for row,p,q,gold in chosen:
        (p,q),_=unify(row,[p,q])
        pair('synthetic_stage_only','C1_P2',row,(p,q),gold['label'],gold)
    if len(jobs)>18:raise ValueError('PLANNED_HTTP_OVER_LIMIT')
    # Interleave old/new and alternate pair order, precluding all-old-first bias.
    jobs=[j for i in range(0,len(jobs),2) for j in (jobs[i:i+2] if (i//2)%2==0 else jobs[i:i+2][::-1])]
    save(OUT/'jobs.json',jobs);save(OUT/'selection_eval_only.json',selection)
    protocol=dict(version='retrieval-corrections-v2',historical_u2=BASE,historical_fc=FC_BASE,historical_hash_seed=0,
        code_hashes=hashes(),jobs_sha256=digest(jobs),selection_sha256=digest(selection),
        audit_hashes={name:hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in (
            'outputs/retrieval_corrections_v2/offline_rows.json','outputs/retrieval_corrections_v2/offline_deltas.json',
            'experiments/retrieval_bakeoff_v1/fixtures/references.json',
            'outputs/multipacket_v1/suite_syn_m1/inputs.jsonl','outputs/multipacket_v1/suite_syn_m1/GOLD_eval_only.json')},
        valid_sha256=hashlib.sha256((ROOT/'valid.parquet').read_bytes()).hexdigest(),
        packages={k:importlib.metadata.version(k) for k in ('bm25s','numpy','pydantic','pandas','pyarrow')},
        providers={'mistral':dict(model=MODEL,context_limit=262144)},limits=dict(http=18,tokens=130000),
        selection_rule='At20k, source-changing <=30k request bytes: each U2/FC two positive + one negative known-valid cases; rank complete-set gain then policy/history span gain then id. C1 two positive + one negative SYN cases with old-zero/new-nonzero policy and new units, lexicographic id. No selection by new model answers.',
        interpretation='Known diagnostic sample, no holdout/generalization or final pipeline claim. C1 shared-policy isolated using same corrected U2 first packet. No retries, no model fallback, UNKNOWN/technical null project0; label and source-supported cause reported separately.',
        cause_audit_status='PENDING_SEPARATE_INDEPENDENT_SOURCE_REVIEW',
        planned_requests=len(jobs),planned_pairs=len(selection),complete_input='All parsed source-event spans including full original catalog; parser transport delimiters excluded')
    protocol['protocol_sha256']=digest(protocol);save(OUT/'protocol.json',protocol)
    print(json.dumps(dict(status='FROZEN_NO_INFERENCE',pairs=len(selection),requests=len(jobs),protocol=protocol['protocol_sha256'])))


def verify():
    p=read(OUT/'protocol.json')
    if digest({k:v for k,v in p.items() if k!='protocol_sha256'})!=p['protocol_sha256']:raise ValueError('PROTOCOL_CHANGED')
    if hashes()!=p['code_hashes']:raise ValueError('FROZEN_CODE_CHANGED')
    if any(hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=h for name,h in p['audit_hashes'].items()):
        raise ValueError('FROZEN_AUDIT_OR_SOURCE_DATA_CHANGED')
    if digest(read(OUT/'jobs.json'))!=p['jobs_sha256']:raise ValueError('FROZEN_REQUESTS_CHANGED')
    if digest(read(OUT/'selection_eval_only.json'))!=p['selection_sha256']:raise ValueError('FROZEN_SELECTION_CHANGED')
    if hashlib.sha256((ROOT/'valid.parquet').read_bytes()).hexdigest()!=p['valid_sha256']:raise ValueError('GOLD_DATA_CHANGED')
    if any(importlib.metadata.version(k)!=v for k,v in p['packages'].items()):raise ValueError('PACKAGE_CHANGED')
    return p


def run(live=False):
    p=verify();client=Client(OUT/'model',p,live=live)
    if live:
        result=preflight('mistral',MODEL);save(OUT/'model/preflight.json',result)
        if result['status']!='READY':print(json.dumps(result));return
    records=[]
    for index,j in enumerate(read(OUT/'jobs.json')):
        rec,failure=client.ask(f'{j["pair_id"]}/{j["arm"]}','mistral',j['request'])
        d=decode(rec,failure,j['packet'])
        if rec and rec.get('actual_model')!=MODEL:
            d=dict(d,decision=None,failure='ACTUAL_MODEL_MISMATCH')
        records.append(dict(index=index,pair_id=j['pair_id'],id=j['id'],cohort=j['cohort'],family=j['family'],arm=j['arm'],
            wire_sha256=j['wire_sha256'],request_sha256=(rec or {}).get('request_sha256'),
            usage=((rec or {}).get('provider_response') or {}).get('usage'),**d))
        save(OUT/'model/decisions.json',records)
        print(json.dumps({k:records[-1].get(k) for k in ('index','cohort','family','arm','decision','failure')}),flush=True)
    save(OUT/'model/budget.json',client.summary());print(json.dumps(client.summary()))


def report():
    verify();records=read(OUT/'model/decisions.json');sel={s['pair_id']:s for s in read(OUT/'selection_eval_only.json')}
    expected={(j['pair_id'],j['arm']):j['wire_sha256'] for j in read(OUT/'jobs.json')}
    actual={(r['pair_id'],r['arm']):r['wire_sha256'] for r in records}
    if len(actual)!=len(records) or actual!=expected:
        raise ValueError('INCOMPLETE_DUPLICATE_OR_CHANGED_PAIRED_RECORDS')
    summary=[]
    for cohort in ('valid_known','synthetic_stage_only'):
      for family in sorted({r['family'] for r in records if r['cohort']==cohort}):
        for arm in ('OLD','NEW'):
            rs=[r for r in records if r['cohort']==cohort and r['family']==family and r['arm']==arm]
            tp=fp=fn=tn=unknown=tech=0
            for r in rs:
                y=sel[r['pair_id']]['label'];pred=r['decision']=='ERROR'
                tp+=bool(y and pred);fp+=bool(not y and pred);fn+=bool(y and not pred);tn+=bool(not y and not pred)
                unknown+=r['decision']=='UNKNOWN';tech+=r['decision'] is None
            f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0
            summary.append(dict(cohort=cohort,family=family,arm=arm,n=len(rs),tp=tp,fp=fp,fn=fn,tn=tn,f1=f1,unknown=unknown,technical=tech,
                prompt_tokens=sum((r.get('usage') or {}).get('prompt_tokens',0) for r in rs),
                completion_tokens=sum((r.get('usage') or {}).get('completion_tokens',0) for r in rs)))
    save(OUT/'model/summary.json',summary);print(json.dumps(summary,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','run','report']);ap.add_argument('--live',action='store_true');a=ap.parse_args()
    if a.stage=='prepare':prepare()
    elif a.stage=='run':run(a.live)
    else:report()
