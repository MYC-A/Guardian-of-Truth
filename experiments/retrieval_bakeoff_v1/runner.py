"""Frozen offline bakeoff and bounded single-provider model diagnostics."""
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path

from guardian_truth.source_search.store import digest
from guardian_truth.parsing import decode_json
from experiments.hybrid_mechanisms.transport import Client, read, save, bound
from experiments.hybrid_mechanisms.interfaces import body, admit
from experiments.hybrid_mechanisms.runner import preflight
from .corpus import build_corpus
from .adapters import METHODS, retrieve, deterministic_extension
from .scoring import score_reference, aggregate
from .gaps import GapReply, PROMPT as GAP_PROMPT, apply_plan

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT = ROOT/'outputs/retrieval_bakeoff_v1'
TOKEN_PACKET_LIMIT = 20000

def code_hashes():
    paths = list(HERE.glob('*.py')) + list((HERE/'fixtures').glob('*.json'))
    paths += list((ROOT/'experiments/hybrid_mechanisms').glob('*.py'))
    paths += list((ROOT/'experiments/telecom_causal_recovery').glob('*.py'))
    paths += list((ROOT/'experiments/research_v5').glob('*.py'))
    paths += [ROOT/'experiments/searh_23/evidence_graph_search_probe/ranked_search.py']
    paths += list((ROOT/'src/guardian_truth').rglob('*.py'))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sorted(paths)}

def cases():
    from .dataset import load_cases
    return load_cases()

def references():
    value = read(HERE/'fixtures/references.json')
    if isinstance(value,dict) and 'cases' in value:value=value['cases']
    if isinstance(value,list):return {v['case_id']:v for v in value}
    return value

def prepare(out):
    cc=cases()
    protocol=dict(version='retrieval-bakeoff-v1',base_commit='f89d271b21deeb5e2820a8c9111857223ca26015',
        code_hashes=code_hashes(),source_sha256={r['id']:build_corpus(r).store.source_sha256 for r in cc},
        valid_parquet_sha256=hashlib.sha256((ROOT/'valid.parquet').read_bytes()).hexdigest(),
        packages={k:importlib.metadata.version(k) for k in ('bm25s','numpy','pydantic','pandas','pyarrow')},
        providers={'mistral':dict(model='ministral-14b-2512',context_limit=262144)},
        limits=dict(http=18,tokens=130000),methods=list(METHODS),
        budgets=[dict(reads=8,tokens=None),dict(reads=12,tokens=None),dict(reads=8,tokens=TOKEN_PACKET_LIMIT),dict(reads=12,tokens=TOKEN_PACKET_LIMIT)],
        selection='Development only: max complete reference sets, then total required-unit recall, then min transmitted UTF8 bound, then method order. Evaluation never selects/tunes.',
        model_design='Impact: first development case supported by original A plus up to two S2G cases; A, best8, intermediate8 at equal20k source bound. Unsupported A gets no call; remove last intermediate jobs until impact<=6. S2G: three diverse development cases x S0 best12/S1 best8 deterministic extension/S2 best8 one gap and one final, all20k source bound. Total18 ceiling; exact reuse when identical; no retry or reallocation after failures.',
        model_case_selection='Two development cases missing best8 reference sets with different domains, then one complete-set control. Prefer a third distinct domain. If no complete control exists select closest partial reference and disclose.',
        interpretation='Known development/regression examples, no independent holdout. Explicit original windows, not complete parent/journal. References never enter retrieval/model prompts.',
        official_s2g='OFFICIAL_S2G_NOT_EXECUTED; S2G_INSPIRED_API_BASED uses one API gap pass and exact original source accumulation.',
        review_interface='Unchanged I4 decision-last, explicit labels; strict Mistral schema and original ID/actor admission; fixed subset-absence contract.')
    protocol['protocol_sha256']=digest(protocol)
    if (out/'protocol.json').exists() and read(out/'protocol.json')!=protocol:raise ValueError('PREPARATION_ALREADY_FROZEN_DIFFERENT')
    save(out/'protocol.json',protocol)
    for i,row in enumerate(cc):
        c=build_corpus(row);save(out/'catalogs'/f'{i:02d}.json',dict(case_id=row['id'],source_sha256=c.store.source_sha256,
            sources=c.catalog,current_targets=c.current_targets,declarations=c.declarations,
            receipt_diagnostics=c.receipt_diagnostics))
    print(json.dumps(dict(status='PREPARED_NO_INFERENCE',cases=len(cc),protocol=protocol['protocol_sha256'])))

def verify(out):
    p=read(out/'protocol.json')
    if digest({k:v for k,v in p.items() if k!='protocol_sha256'})!=p['protocol_sha256']:raise ValueError('PROTOCOL_CHANGED')
    if code_hashes()!=p['code_hashes']:raise ValueError('FROZEN_CODE_OR_REFERENCE_CHANGED')
    if any(importlib.metadata.version(k)!=v for k,v in p['packages'].items()):raise ValueError('FROZEN_PACKAGE_VERSION_CHANGED')
    if hashlib.sha256((ROOT/'valid.parquet').read_bytes()).hexdigest()!=p['valid_parquet_sha256']:raise ValueError('ORIGINAL_DATA_CHANGED')
    for r in cases():
        if build_corpus(r).store.source_sha256!=p['source_sha256'][r['id']]:raise ValueError('SOURCE_CHANGED')
    return p

def offline(out):
    p=verify(out);refs=references();allrows=[]
    for index,row in enumerate(cases()):
        c=build_corpus(row)
        for budget in p['budgets']:
            key=f"k{budget['reads']}"+(f"_t{budget['tokens']}" if budget['tokens'] else '')
            for method in METHODS:
                packet=retrieve(c,method,budget['reads'],budget['tokens'])
                entry=dict(case_id=row['id'],split=row['split'],index=index,method=method,budget=key,
                           packet=packet,score=score_reference(refs[row['id']],packet))
                save(out/'offline_packets'/f'{index:02d}_{method}_{key}.json',entry)
                allrows.append(entry)
        print(json.dumps(dict(case_id=row['id'],status='OFFLINE_COMPLETE')),flush=True)
    groups=defaultdict(list)
    for r in allrows:groups[(r['split'],r['method'],r['budget'])].append(r)
    summary=[dict(split=split,method=method,budget=budget,**aggregate(rr),
        source_utf8_bound=sum(r['packet']['cost']['source_token_upper_bound'] for r in rr),
        seconds=sum(r['packet']['seconds'] for r in rr)) for (split,method,budget),rr in groups.items()]
    save(out/'offline_summary.json',summary)
    dev=[g for g in summary if g['split']=='dev' and g['budget']=='k8' and g['method']!='A']
    def rank(g):
        found=sum(v['found'] for k,v in g['categories'].items() if k in ('policy','history','declaration','exception','target'))
        required=sum(v['required'] for k,v in g['categories'].items() if k in ('policy','history','declaration','exception','target'))
        return (-g['complete'],-(found/required if required else 0),g['source_utf8_bound'],METHODS.index(g['method']))
    ordered=sorted(dev,key=rank)
    save(out/'selection.json',dict(best=ordered[0]['method'],intermediate='local_bm25' if ordered[0]['method']!='local_bm25' else 'B3',
                                 based_on='DEVELOPMENT_ONLY_FROZEN_CRITERIA',ranking=ordered))

def review_packet(packet):
    # Plain-language KB returns may contain norms. They retain assistant actors;
    # their inclusion is candidate semantics, not a code-certified policy source.
    def candidate_norm(s):
        if s.get('category')=='POLICY':return True
        if s.get('kind')!='result':return False
        _,valid=decode_json(s['text'])
        return not valid
    norms=[s for s in packet['read_sources'] if candidate_norm(s)]
    ids={s['source_id'] for s in norms}
    return dict(source_sha256=packet['source_sha256'],current_response='\n'.join(s['text'] for s in packet['current_targets']),
        current_targets=packet['current_targets'],declarations=packet['declarations'],normative_sources=norms,
        history=[s for s in packet['read_sources'] if s['source_id'] not in ids],
        evidence_contract=packet['evidence_contract'],uncovered=packet['uncovered'],
        coverage='EXACT_SELECTED_ORIGINAL_SPANS_ONLY_NOT_COMPLETE_JOURNAL')

def decode(record,failure,packet):
    if failure or not record:return dict(decision=None,raw_decision=None,failure=failure or 'MISSING_RECORD')
    if record['status']!='OK':return dict(decision=None,raw_decision=None,failure=record['status'])
    data=record.get('provider_response')
    choices=data.get('choices') if isinstance(data,dict) else None
    if (not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict)
            or not isinstance(choices[0].get('message'),dict)):
        return dict(decision=None,raw_decision=None,failure='PROVIDER_SHAPE_INVALID')
    choice=choices[0];value,valid=decode_json(choice.get('message',{}).get('content'))
    raw=value.get('decision') if isinstance(value,dict) else None
    if not valid or choice.get('finish_reason')!='stop':return dict(decision=None,raw_decision=raw,failure='INVALID_OR_UNFINISHED_JSON')
    try:reply=admit(value,packet)
    except ValueError as e:return dict(decision=None,raw_decision=raw,raw_reply=value,failure='ADMISSION:'+str(e))
    return dict(decision=reply['decision'],raw_decision=raw,reply=reply,failure=None)

def model_cases(out):
    selection=read(out/'selection.json');rows=cases()
    dev=[]
    for i,row in enumerate(rows):
        if row['split']!='dev':continue
        e=read(out/'offline_packets'/f"{i:02d}_{selection['best']}_k8_t{TOKEN_PACKET_LIMIT}.json")
        dev.append((i,row,e))
    chosen=[];domains=set()
    for i,row,e in dev:
        domain=row['id'].split('__')[0]
        if not e['score']['complete_evidence_set_success'] and domain not in domains and len(chosen)<2:
            chosen.append((i,row,e));domains.add(domain)
    controls=[t for t in dev if t[2]['score']['complete_evidence_set_success'] and t[1]['id'] not in {r[1]['id'] for r in chosen}]
    controls.sort(key=lambda t:(t[1]['id'].split('__')[0] in domains,t[0]))
    if controls:chosen.append(controls[0])
    if len(chosen)<3:
        for t in dev:
            if t[1]['id'] not in {r[1]['id'] for r in chosen}:chosen.append(t)
            if len(chosen)==3:break
    return chosen[:3]

def decode_gap(record,failure,corpus,initial):
    value=None
    try:
        if failure or not record or record['status']!='OK':raise ValueError(failure or (record or {}).get('status','NO_RECORD'))
        data=record.get('provider_response')
        choices=data.get('choices') if isinstance(data,dict) else None
        if (not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict)
                or not isinstance(choices[0].get('message'),dict)):
            raise ValueError('GAP_PROVIDER_SHAPE_INVALID')
        choice=choices[0];value,valid=decode_json(choice['message'].get('content'))
        if not valid or choice.get('finish_reason')!='stop':raise ValueError('GAP_INVALID_OR_UNFINISHED_JSON')
        packet=apply_plan(corpus,initial,value,
            read_policy_ids={s['source_id'] for s in review_packet(initial)['normative_sources']},token_limit=TOKEN_PACKET_LIMIT)
        return value,'VALID_MODEL_HYPOTHESIS',packet
    except (ValueError,KeyError,IndexError,TypeError) as exc:
        return value,type(exc).__name__+':'+str(exc),None

def prepare_models(out):
    p=verify(out);chosen=model_cases(out);sel=read(out/'selection.json');jobs=[]
    impact=[]
    for i,row in enumerate(cases()):
        if row['split']!='dev':continue
        baseline=read(out/'offline_packets'/f'{i:02d}_A_k8_t{TOKEN_PACKET_LIMIT}.json')
        if not baseline['packet']['failure']:
            impact.append((i,row,baseline));break
    for item in chosen:
        if item[1]['id'] not in {r[1]['id'] for r in impact}:impact.append(item)
        if len(impact)==3:break
    for i,row,initial in impact:
        for method in ('A',sel['best'],sel['intermediate']):
            entry=read(out/'offline_packets'/f'{i:02d}_{method}_k8_t{TOKEN_PACKET_LIMIT}.json')
            if entry['packet']['failure']:
                jobs.append(dict(name=f'{i:02d}_impact_{method}',case_id=row['id'],skip=entry['packet']['failure']));continue
            packet=review_packet(entry['packet']);request=body(packet,'mistral',p['providers']['mistral']['model'])
            job=dict(name=f'{i:02d}_impact_{method}',case_id=row['id'],kind='impact',packet=packet,request=request)
            jobs.append(job);save(out/'prepared'/f"{job['name']}.json",job)
    save(out/'model_plan.json',dict(cases=[dict(index=i,case_id=r['id'],initial_complete=e['score']['complete_evidence_set_success']) for i,r,e in chosen],
        jobs=jobs,requests_before_s2g=sum(not j.get('skip') for j in jobs),s2g_reserved_attempts=12,
        ceiling=18,selection=sel))
    while sum(not j.get('skip') for j in jobs)>6:
        # Reserve the mandatory three-case S0/S1/S2 experiment first; omit the
        # intermediate third case by the frozen case order, not model answers.
        omit=next(j for j in reversed(jobs) if not j.get('skip') and j.get('kind')=='impact' and j['name'].endswith('_'+sel['intermediate']))
        omit['skip']='S2G_PRIORITY_CALL_RESERVATION'
        save(out/'model_plan.json',dict(cases=[dict(index=i,case_id=r['id'],initial_complete=e['score']['complete_evidence_set_success']) for i,r,e in chosen],jobs=jobs,
            requests_before_s2g=sum(not j.get('skip') for j in jobs),s2g_reserved_attempts=12,ceiling=18,selection=sel))

def run_models(out,phase,live=False):
    p=verify(out);client=Client(out,p,live=live);plan=read(out/'model_plan.json')
    predictions=read(out/'model_predictions.json') if (out/'model_predictions.json').exists() else []
    names={r['name'] for r in predictions}
    def judge(job,source_packet=None):
        if job['name'] in names:return
        if source_packet is not None and source_packet.get('failure'):
            job=dict(job,skip=source_packet['failure'])
        if not job.get('skip') and (not job['packet']['current_targets'] or not job['packet']['normative_sources']):
            job=dict(job,skip='NO_CURRENT_TARGET_OR_NORMATIVE_EVIDENCE')
        if job.get('skip'):result=dict(decision=None,raw_decision=None,failure=job['skip']);record=None
        else:
            save(out/'prepared'/f"{job['name']}.json",job)
            record,failure=client.ask(job['name'],'mistral',job['request'])
            result=decode(record,failure,job['packet'])
        rr=dict(name=job['name'],case_id=job['case_id'],kind=job.get('kind'),result=result,
                request_sha256=record['request_sha256'] if record else None,
                tokens=record['known_tokens'] if record else 0,seconds=record.get('seconds',0) if record else 0)
        predictions.append(rr);names.add(rr['name']);save(out/'model_predictions.json',predictions)
        if source_packet is not None:save(out/'s2g_packets'/f"{job['name']}.json",source_packet)
        print(json.dumps(rr,ensure_ascii=False),flush=True)
    if phase=='impact':
        meta=preflight('mistral',p['providers']['mistral']['model']) if live else read(out/'preflight.json')
        save(out/'preflight.json',meta)
        if meta.get('status')!='READY':save(out/'preflight_stop.json',meta);return
        for job in plan['jobs']:judge(job)
    elif phase=='s2g':
        for spec in plan['cases']:
            i=spec['index'];row=next(r for r in cases() if r['id']==spec['case_id']);c=build_corpus(row)
            best=plan['selection']['best'];initial=read(out/'offline_packets'/f'{i:02d}_{best}_k8_t{TOKEN_PACKET_LIMIT}.json')['packet']
            s0=read(out/'offline_packets'/f'{i:02d}_{best}_k12_t{TOKEN_PACKET_LIMIT}.json')['packet']
            s1=deterministic_extension(c,initial['selected_ids'],12,TOKEN_PACKET_LIMIT)
            for arm,packet in [('S0',s0),('S1',s1)]:
                pp=review_packet(packet);judge(dict(name=f'{i:02d}_{arm}',case_id=row['id'],kind=arm,packet=pp,
                    request=body(pp,'mistral',p['providers']['mistral']['model'])),packet)
            gp=review_packet(initial)
            catalog=[{k:s[k] for k in ('source_id','parent_source_id','document','start','end','role','kind','tool') if k in s}|
                      dict(navigation_preview=s['text'][:120],preview_complete=len(s['text'])<=120) for s in c.catalog]
            data=dict(packet=gp,already_read=initial['selected_ids'],catalog=catalog,remaining_distinct_reads=12-len(initial['selected_ids']),
                      source_operations='read original source / lexical search only',sufficiency_is_proof=False)
            request=dict(model=p['providers']['mistral']['model'],temperature=0,max_tokens=1000,
                messages=[dict(role='system',content=GAP_PROMPT),dict(role='user',content=json.dumps(data,ensure_ascii=False,separators=(',',':')))],
                response_format=dict(type='json_schema',json_schema=dict(name='evidence_gaps',strict=True,schema=GapReply.model_json_schema())))
            name=f'{i:02d}_S2_gap';save(out/'prepared'/f'{name}.json',dict(name=name,case_id=row['id'],request=request))
            record,failure=client.ask(name,'mistral',request)
            value,status,s2=decode_gap(record,failure,c,initial)
            save(out/'s2g_gap_results'/f'{i:02d}.json',dict(case_id=row['id'],status=status,reply=value,
                request_sha256=record['request_sha256'] if record else None,transport_failure=failure,
                original_implementation='OFFICIAL_S2G_NOT_EXECUTED'))
            if s2 is None:
                judge(dict(name=f'{i:02d}_S2',case_id=row['id'],kind='S2',skip='GAP_INVALID_NO_FINAL_REVIEW'));continue
            pp=review_packet(s2);judge(dict(name=f'{i:02d}_S2',case_id=row['id'],kind='S2',packet=pp,
                request=body(pp,'mistral',p['providers']['mistral']['model'])),s2)
    else:raise ValueError('PHASE_UNKNOWN')
    save(out/f'{phase}_completion.json',dict(phase=phase,summary=client.summary()))

def replay(out):
    p=verify(out);client=Client(out,p,live=False)
    for path in sorted((out/'requests').glob('*.json')):
        req=read(path);item=client.ledger[req['request_sha256']]
        record,failure=client.ask(item['name'],req['provider'],req['body'])
        if failure or not record:raise ValueError('RAW_REPLAY_FAILED')
    for pred in read(out/'model_predictions.json') if (out/'model_predictions.json').exists() else []:
        if pred['request_sha256']:
            job=read(out/'prepared'/(pred['name']+'.json'));record=read(out/'raw'/(pred['request_sha256']+'.json'))
            if decode(record,None,job['packet'])!=pred['result']:raise ValueError('PREDICTION_CHANGED')
    def timeless(value):
        if isinstance(value,dict):return {k:timeless(v) for k,v in value.items() if k!='seconds'}
        if isinstance(value,list):return [timeless(v) for v in value]
        return value
    controller_audit=[]
    if (out/'model_plan.json').exists():
        plan=read(out/'model_plan.json');best=plan['selection']['best']
        for spec in plan['cases']:
            i=spec['index'];row=next(r for r in cases() if r['id']==spec['case_id']);c=build_corpus(row)
            initial=read(out/'offline_packets'/f'{i:02d}_{best}_k8_t{TOKEN_PACKET_LIMIT}.json')['packet']
            for arm in ('S0','S1'):
                path=out/'s2g_packets'/f'{i:02d}_{arm}.json'
                if path.exists():
                    fresh=(retrieve(c,best,12,TOKEN_PACKET_LIMIT) if arm=='S0'
                           else deterministic_extension(c,initial['selected_ids'],12,TOKEN_PACKET_LIMIT))
                    if timeless(fresh)!=timeless(read(path)):raise ValueError('CONTROLLER_CHANGED:'+arm)
            gap_path=out/'s2g_gap_results'/f'{i:02d}.json'
            if not gap_path.exists():continue
            saved=read(gap_path);key=saved['request_sha256']
            record=read(out/'raw'/(key+'.json')) if key else None
            value,status,packet=decode_gap(record,saved.get('transport_failure'),c,initial)
            if value!=saved['reply'] or status!=saved['status']:raise ValueError('GAP_DERIVATION_CHANGED')
            finalpath=out/'s2g_packets'/f'{i:02d}_S2.json'
            if packet is not None:
                if not finalpath.exists() or timeless(packet)!=timeless(read(finalpath)):raise ValueError('S2_CONTROLLER_CHANGED')
            elif finalpath.exists():raise ValueError('INVALID_PLAN_HAS_EVIDENCE')
            controller_audit.append(dict(case_id=row['id'],status=status,reconstructed=True))
    save(out/'offline_replay.json',dict(status='PASS',inference_http=0,usage=client.summary(),
        controller_audit=controller_audit,request_count=len(client.ledger),semantic_rows=len(read(out/'model_predictions.json')) if (out/'model_predictions.json').exists() else 0))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','offline','prepare_models','impact','s2g','replay']);parser.add_argument('--out',type=Path,default=DEFAULT);parser.add_argument('--live',action='store_true');a=parser.parse_args()
    if a.command=='prepare':prepare(a.out)
    elif a.command=='offline':offline(a.out)
    elif a.command=='prepare_models':prepare_models(a.out)
    elif a.command in ('impact','s2g'):run_models(a.out,a.command,a.live)
    else:replay(a.out)
