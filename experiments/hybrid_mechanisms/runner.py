"""Frozen prepare/run/replay workflow; labels enter only separate scoring."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'src'))
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import digest
from . import interfaces, packets
from .transport import Client, read, save, preflight
from .retrieval import BoundedRetrieval
from .consistency import audit_consistency,hypothesis_adapter
from experiments.telecom_causal_recovery import packets as old_packets, review as old_review

HERE = Path(__file__).parent
DEFAULT = ROOT/'outputs/hybrid_mechanisms_v1'


def sha(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def hashes():
    files = list(HERE.glob('*.py')) + list((ROOT/'experiments/research_v5').glob('*.py'))
    files += list((ROOT/'experiments/telecom_causal_recovery').glob('*.py'))
    files += [ROOT/'experiments/research_v3/pilot.py'] + list((ROOT/'src').rglob('*.py'))
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}


def historical_hashes():
    return {name:sha(ROOT/name) for name in (
        'outputs/research_v5/paired_role_diagnostic/predictions.json',
        'outputs/telecom_causal_recovery/v1/automatic_predictions.json',
        'outputs/telecom_causal_recovery/v1/prepared_requests/AUTO_plan.json',
        'outputs/telecom_causal_recovery/v1/raw/8007271ee679af1493b66f076745f0db863b3ffe19b3d48215c09db293da8c1f.json')}


def rows():
    return {r['name']:r for r in (json.loads(l) for l in (HERE/'fixtures/inputs.jsonl').read_text(encoding='utf-8').splitlines())}


def prepared():
    return {name:packets.prepare_packet(r,r['retrieval']) for name,r in rows().items()}


def prepare(out):
    if (out/'protocol.json').exists(): raise ValueError('FROZEN_OUTPUT_EXISTS')
    pp = dict(version='hybrid-mechanisms-v1', base_commit='6035918cdcef6d5600aecfd91bc2f01a4d5cf73c',
              code_hashes=hashes(), historical_input_hashes=historical_hashes(),inputs_sha256=sha(HERE/'fixtures/inputs.jsonl'),
              scoring_gold_sha256=sha(HERE/'fixtures/gold.json'),
              providers={'mistral':dict(model='ministral-14b-2512',endpoint='https://api.mistral.ai/v1/chat/completions',context_limit=262144),
                         'ollama':dict(model='gemma4:31b',endpoint='https://ollama.com/v1/chat/completions',context_limit=131072)},
              limits=dict(http=36,tokens=280000), max_tokens=1700,temperature=0,timeout=120,
              retry=0,fallback=False,unknown_binary_mapping=0,inference_reads_gold=False,
              interface_selection='I4 fixed a priori; never optimize labels or observed F1. Record field order failures; no order-causal claim if generation does not honor order.',
              response_modes='Mistral strict json_schema; Ollama json_object plus identical schema in system text. Provider difference is confounded with decoding mode.',
              phases=['factorial','augment','split','retrieval','extras','gate'],
              allocation='16 factorial +4 K +4 C +4 separated stages +1 cached-R0 new final +2 R1 plans/1 final +1 coverage final +2 extra cases +1 V2 <=36. Skipped calls are not automatically reallocated.',
              reservation='Full UTF8 serialized body bytes+2048 template allowance+output cap. No truncated inputs. Actual verified usage refunds reservation. Missing usage retains full reservation and provider breaker. Conservative budget may stop unmeasured arms.',
              retrieval_limits=dict(full_reads=8,planning_rounds=2),
              proof_contract='Typed model norms are hypotheses. Consistency is a flag; bounded ERROR proof requires independent source-qualified norm/action/state/exception closure. Empty exception list is not closure.',
              dataset='4 preselected known valid46 development cases; binary labels untouched. No independent holdout or overall valid46 improvement claim.')
    pp['protocol_sha256']=digest(pp); save(out/'protocol.json',pp)
    records=[]
    for name, p in prepared().items():
        save(out/'packets'/(name+'.json'),p)
        records.append(dict(name=name,**packets.validate_packet(rows()[name],p)))
    save(out/'preparation.json',records)
    for provider, spec in pp['providers'].items():
        for name in ('telecom','bank'):
            for interface in ('I1','I2','I3','I4'):
                b=interfaces.body(prepared()[name],provider,spec['model'],interface)
                save(out/'prepared_requests'/f'{provider}_{name}_{interface}.json',b)
    print(json.dumps(dict(prepared=True,inference_http=0,protocol_sha256=pp['protocol_sha256'])),flush=True)


def verify(out):
    p=read(out/'protocol.json')
    if p['protocol_sha256'] != digest({k:v for k,v in p.items() if k!='protocol_sha256'}):raise ValueError('PROTOCOL_CHANGED')
    if p['code_hashes'] != hashes() or p['historical_input_hashes'] != historical_hashes() or p['inputs_sha256'] != sha(HERE/'fixtures/inputs.jsonl'):raise ValueError('FROZEN_CODE_OR_INPUT_CHANGED')
    return p


def decode(record, failure, packet, stage=None):
    out=dict(failure=failure,raw_reply=None,admitted_reply=None,decision=None,raw_decision=None,code_proof=False)
    if record is None:return out
    out.update(request_sha256=record['request_sha256'],provider_model=record.get('provider_response',{}).get('model'),
               known_tokens=record.get('known_tokens'),seconds=record.get('seconds'))
    if record['status']!='OK':out['failure']=record['status'];return out
    choices=record['provider_response'].get('choices',[])
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):out['failure']='CHOICES_INVALID';return out
    c=choices[0]
    if not isinstance(c.get('message'),dict):out['failure']='MESSAGE_INVALID';return out
    text=c['message'].get('content');reply,valid=decode_json(text)
    out['raw_reply']=reply
    if isinstance(reply,dict):out.update(raw_decision=reply.get('decision'),raw_field_order=list(reply))
    if c.get('finish_reason')!='stop' or not valid:out['failure']='UNFINISHED_OR_INVALID_REPLY';return out
    try:
        out['admitted_reply']=interfaces.admit(reply,packet,stage)
        out['decision']=out['admitted_reply'].get('decision')
    except Exception as exc:out['failure']='ADMISSION:'+str(exc)
    return out


def reference_predictions():
    data=read(ROOT/'outputs/research_v5/paired_role_diagnostic/predictions.json')
    return {r['id']:r['reply'] for r in data if r['arm']=='D0'}


def catalog(row):
    # Identical historical initial catalog makes saved one-shot selection eligible
    # for source-discovery comparison; final judgment is a new request.
    return old_packets.catalog(row)


PLAN_PROMPT='''Plan read-only source discovery for the current move. You have an indexed catalog, original declarations and prior complete reads, not oracle evidence. Locate applicable norms, independent conditions, exact entity facts, chronology and exceptions. Search snippets are navigation only. At most 8 distinct full-source reads across all rounds. Return {operations:[{operation:READ_SOURCE|SEARCH_SOURCES,source_id:string|null,query:string|null}], gaps:[{gap_id:string,question:string,policy_sources:[source_id],target_sources:[target_id],required_fact_type:string,candidate_source_ids:[source_id],visited_source_ids:[source_id],status:OPEN|RESOLVED|UNRESOLVED,supporting_sources:[source_id],unresolved_reason:string|null}], sufficient:boolean}. Use source IDs from the catalog. Do not mark a gap resolved unless supporting full sources were actually read or are selected for complete reading in this round. No business tools can execute. Stop when sufficient, otherwise retain actual questions. Choose remaining reads from evidence, not prior judge opinions.'''


def planner_body(data,model):
    return dict(model=model,temperature=0,max_tokens=1700,response_format=dict(type='json_object'),
                messages=[dict(role='system',content=PLAN_PROMPT),dict(role='user',content=json.dumps(data,ensure_ascii=False,separators=(',',':')))])


def retrieval_packet(row, cat, context):
    g,target,norms=old_packets.extract(row)
    normmap={n['source_id']:n for n in norms}
    found=context['read_sources']
    if isinstance(found,dict):found=list(found.values())
    byid={s['source_id']:{k:v for k,v in s.items() if k!='windows'} for s in found}
    for sid,s in byid.items():
        metadata=g.store.sources.get(sid,{})
        s.setdefault('role',metadata.get('role','system' if sid in normmap else 'unknown'))
        s.setdefault('kind',metadata.get('kind','NORMATIVE_SOURCE' if sid in normmap else 'unknown'))
    if 'h0' in byid:
        for n in norms:byid[n['source_id']]=n
    p=packets.prepare_packet(row,row['retrieval'])
    p['normative_sources']=[s for sid,s in byid.items() if sid in normmap]
    p['history']=[s for sid,s in byid.items() if sid not in normmap]
    p['declarations']=cat['declarations']
    p['retrieval']='AUTOMATIC_READ_ONLY_FULL_SOURCE_CONTROL'
    p['read_trace']=dict(read_source_ids=[s['source_id'] for s in found],gap_ledger=context['gap_ledger'],
                         reads_remaining=context['reads_remaining'],coverage='COMPLETE_SELECTED_SOURCES_ONLY')
    p['omitted_normative_source_ids']=[sid for sid in normmap if sid not in byid]
    p['omitted_history_source_ids']=[sid for sid in g.store.sources if re.fullmatch(r'h\d+',sid) and sid not in byid]
    return p


def coverage_plan(row,cat):
    """Gold-free one-shot raw identity and temporal coverage, no business names.

    Norms ranked by action lexical overlap; history results by literal target
    operand presence and earliest/latest diversity, with their unique calls.
    This selects observations, not certified ownership/current state.
    """
    g,target,norms=old_packets.extract(row)
    words=set(re.findall(r'\w+',target['tool'].replace('_',' ').casefold()))
    score=lambda n:sum(n['text'].casefold().count(w) for w in words)
    chosen=[n['source_id'] for n in sorted(norms,key=lambda n:(-score(n),n['start']))[:2]]
    vals=[v for v in target['arguments'].values() if isinstance(v,str)]
    results=[(sid,s) for sid,s in g.store.sources.items() if re.fullmatch(r'h\d+',sid)
             and s['kind']=='result' and any(v in g.store.text(sid) for v in vals)]
    ordered=sorted(results,key=lambda t:t[1]['event'])
    diversity=[]
    if ordered:diversity=[ordered[0],ordered[-1]]+ordered[1:-1]
    for sid,s in diversity:
        prev='h'+str(s['event']-1)
        pair=[prev,sid] if g.store.sources.get(prev,{}).get('kind')=='call' else [sid]
        if len(chosen)+len([x for x in pair if x not in chosen])>8:continue
        chosen += [x for x in pair if x not in chosen]
    return dict(operations=[dict(operation='READ_SOURCE',source_id=sid,query=None) for sid in chosen],gaps=[],sufficient=False)


def run(out, phase, live):
    protocol=verify(out); client=Client(out,protocol,live=live)
    allrows=rows(); bases=prepared();predpath=out/'predictions.json'
    predictions=read(predpath) if predpath.exists() else []
    byname={r['name']:r for r in predictions}
    def ask(name,case,provider='mistral',interface='I4',packet=None,stage=None,semantics=None,purpose=None):
        p=packet or bases[case];model=protocol['providers'][provider]['model']
        b=interfaces.body(p,provider,model,interface,stage,semantics,purpose)
        if name in byname:
            # Still exercise exact transport replay; never trust derived cache alone.
            record,failure=client.ask(name,provider,b)
            fresh=decode(record,failure,p,stage)
            if fresh!=byname[name]['result']:raise ValueError('PREDICTION_REPLAY_CHANGED')
            return byname[name]
        save(out/'phase_packets'/(name+'.json'),p)
        record,failure=client.ask(name,provider,b);result=decode(record,failure,p,stage)
        r=dict(name=name,case=case,provider=provider,interface=interface,stage=stage,
               source_sha256=p['source_sha256'],packet_sha256=digest(p),result=result)
        predictions.append(r);byname[name]=r;save(predpath,predictions)
        print(json.dumps(dict(name=name,decision=result['decision'],raw_decision=result['raw_decision'],failure=result['failure'],model=result.get('provider_model'))),flush=True)
        return r
    if phase=='factorial':
        for provider,spec in protocol['providers'].items():
            if live:
                meta=preflight(provider,spec['model']);save(out/'preflight'/(provider+'.json'),meta)
            else:
                path=out/'preflight'/(provider+'.json')
                meta=read(path) if path.exists() else dict(status='PREFLIGHT_CACHE_MISSING_OFFLINE')
            if meta.get('status')!='READY':
                save(out/'skipped'/(provider+'.json'),dict(reason=meta,inference_calls=0));continue
            for case in ('telecom','bank'):
                for interface in ('I1','I2','I3','I4'):ask(f'{provider}_{case}_{interface}',case,provider,interface)
    elif phase=='augment':
        refs=reference_predictions()
        for case in ('telecom','bank'):
            for a in ('K1','K2','C1','C2'):
                ask(f'mistral_{case}_{a}',case,packet=packets.arm(allrows[case],bases[case],a,refs.get(allrows[case]['id'],{})))
    elif phase=='split':
        for case in ('telecom','bank'):
            a=ask(f'mistral_{case}_stageA',case,stage='A')
            semantic=a['result']['admitted_reply']
            if semantic is None:continue
            save(out/'code_adapters'/(case+'.json'),dict(conditional_audit=audit_consistency(dict(decision='UNKNOWN',**semantic)),
                                                       hypothesis_aggregation=hypothesis_adapter(semantic)))
            ask(f'mistral_{case}_stageB',case,stage='B',semantics=semantic)
    elif phase=='retrieval':
        row=allrows['telecom'];cat=catalog(row)
        oldb=old_review.body(cat,plan=True)
        saved=read(ROOT/'outputs/telecom_causal_recovery/v1/prepared_requests/AUTO_plan.json')
        if oldb!=saved:raise ValueError('R0_SAVED_PLAN_NOT_EQUIVALENT')
        # Reuse old plan only, never old budget-stopped final.
        oldpred=read(ROOT/'outputs/telecom_causal_recovery/v1/automatic_predictions.json')
        plan=next(r for r in oldpred if r['name']=='AUTO_plan')['reply']
        g,_,norms=old_packets.extract(row)
        catitems=cat['normative_catalog']+cat['history_catalog']
        def controller():return BoundedRetrieval(g.store,catitems,['t0'],max_reads=8,max_rounds=2)
        r0=controller();r0.step(dict(operations=plan['operations'],gaps=[],sufficient=False))
        save(out/'retrieval/R0.json',r0.result())
        ask('mistral_telecom_R0_final','telecom',packet=retrieval_packet(row,cat,r0.context()))
        # Fresh SourceStore prevents quote-allocation side effects between arms.
        g,_,_=old_packets.extract(row);r1=controller()
        for round_no in range(2):
            b=planner_body(dict(initial_catalog=cat,retrieval_context=r1.context(),round=round_no+1,
                                remaining_full_reads=r1.context()['reads_remaining']),protocol['providers']['mistral']['model'])
            name=f'mistral_telecom_R1_plan{round_no+1}';save(out/'prepared_dynamic'/(name+'.json'),b)
            record,failure=client.ask(name,'mistral',b)
            if failure or record is None or record['status']!='OK':
                save(out/'retrieval/R1_plan_failure.json',dict(name=name,failure=failure or record['status']));break
            cc=record['provider_response'].get('choices')
            if not isinstance(cc,list) or len(cc)!=1 or not isinstance(cc[0],dict) or not isinstance(cc[0].get('message'),dict):
                save(out/'retrieval/R1_plan_failure.json',dict(name=name,failure='PLAN_PROVIDER_SHAPE_INVALID'));break
            c=cc[0];value,valid=decode_json(c['message'].get('content'))
            if not valid or c.get('finish_reason')!='stop':
                save(out/'retrieval/R1_plan_failure.json',dict(name=name,failure='PLAN_INVALID',reply=value));break
            try:trace=r1.step(value)
            except Exception as exc:
                save(out/'retrieval/R1_plan_failure.json',dict(name=name,failure=type(exc).__name__+':'+str(exc),reply=value));break
            save(out/'retrieval'/f'R1_round{round_no+1}.json',dict(plan=value,trace=trace))
            if r1.result()['stop_reason']:break
        save(out/'retrieval/R1.json',r1.result())
        ask('mistral_telecom_R1_final','telecom',packet=retrieval_packet(row,cat,r1.context()))
        g,_,_=old_packets.extract(row);r2=controller();r2.step(coverage_plan(row,cat))
        save(out/'retrieval/coverage.json',r2.result())
        ask('mistral_telecom_coverage_final','telecom',packet=retrieval_packet(row,cat,r2.context()))
    elif phase=='extras':
        for case in ('multicall','exception'):ask(f'mistral_{case}_I4',case)
    elif phase=='gate':
        # Typed contradiction supplies conditional flags; one bounded semantic review.
        candidates=[]
        for case in ('telecom','bank'):
            a=byname.get(f'mistral_{case}_stageA',{}).get('result',{}).get('admitted_reply')
            d=byname.get(f'mistral_{case}_I4',{}).get('result',{}).get('decision')
            if a and d:
                report=audit_consistency(dict(decision=d,**a));save(out/'gate'/(case+'.json'),report)
                if report.get('flags'):candidates.append((case,a,d,report))
        if candidates:
            case,a,d,report=candidates[0]
            p=dict(bases[case],consistency_diagnostic=dict(status='CONDITIONAL_MODEL_HYPOTHESIS_FLAG',earlier_decision=d,assessments=a,audit=report))
            ask(f'mistral_{case}_V2',case,packet=p,purpose='gate_review')
        else:save(out/'gate/V2_skipped.json',dict(reason='NO_TYPED_CONTRADICTION_FLAG',calls=0))
    else:raise ValueError('UNKNOWN_PHASE')
    save(out/(phase+'_completion.json'),dict(phase=phase,summary=client.summary(),prediction_count=len(predictions),live=live))


def replay(out):
    protocol=verify(out);client=Client(out,protocol,live=False)
    records=read(out/'predictions.json') if (out/'predictions.json').exists() else []
    audit=[]
    # Dynamic planning calls are not semantic predictions, but remain charged,
    # immutable inference records and must receive the same exact-wire replay.
    for request in sorted((out/'requests').glob('*.json')):
        req=read(request);record,failure=client.ask(client.ledger[req['request_sha256']]['name'],req['provider'],req['body'])
        if record is None:raise ValueError('RETAINED_REQUEST_WITHOUT_RAW:'+str(failure))
    for r in records:
        p=read(out/'phase_packets'/(r['name']+'.json'))
        if digest(p)!=r['packet_sha256']:raise ValueError('PACKET_CHANGED')
        packets.validate_packet(rows()[r['case']],p)
        key=r['result'].get('request_sha256')
        if not key:continue
        req=read(out/'requests'/(key+'.json'))
        raw,failure=client.ask(r['name'],r['provider'],req['body'])
        fresh=decode(raw,failure,p,r['stage'])
        if fresh!=r['result']:raise ValueError('DERIVED_PREDICTION_CHANGED')
        audit.append(dict(name=r['name'],raw_decision=fresh['raw_decision'],decision=fresh['decision'],failure=fresh['failure'],raw_field_order=fresh.get('raw_field_order')))
    retrieval_audit=[]
    if (out/'retrieval/R0.json').exists():
        row=rows()['telecom'];cat=catalog(row)
        if old_review.body(cat,plan=True)!=read(ROOT/'outputs/telecom_causal_recovery/v1/prepared_requests/AUTO_plan.json'):
            raise ValueError('R0_EQUIVALENCE_CHANGED')
        oldpred=read(ROOT/'outputs/telecom_causal_recovery/v1/automatic_predictions.json')
        plan=next(r for r in oldpred if r['name']=='AUTO_plan')['reply']
        for arm_name in ('R0','R1','coverage'):
            g,_,_=old_packets.extract(row)
            c=BoundedRetrieval(g.store,cat['normative_catalog']+cat['history_catalog'],['t0'],max_reads=8,max_rounds=2)
            if arm_name=='R0':c.step(dict(operations=plan['operations'],gaps=[],sufficient=False))
            elif arm_name=='coverage':c.step(coverage_plan(row,cat))
            else:
                for f in sorted((out/'retrieval').glob('R1_round*.json')):
                    stored=read(f)
                    round_no=int(re.search(r'round(\d+)',f.stem)[1])
                    name=f'mistral_telecom_R1_plan{round_no}'
                    item=next(i for i in client.ledger.values() if i['name']==name)
                    raw=read(out/'raw'/(item['request_sha256']+'.json'))
                    content=raw['provider_response']['choices'][0]['message']['content']
                    raw_plan,valid=decode_json(content)
                    if not valid or raw_plan!=stored['plan']:raise ValueError('R1_RAW_PLAN_CHANGED')
                    trace=c.step(raw_plan)
                    if trace!=stored['trace']:raise ValueError('R1_CONTROLLER_TRACE_CHANGED')
            if c.result()!=read(out/'retrieval'/(arm_name+'.json')):raise ValueError('RETRIEVAL_REPLAY_CHANGED:'+arm_name)
            final='mistral_telecom_'+('coverage' if arm_name=='coverage' else arm_name)+'_final'
            if retrieval_packet(row,cat,c.context())!=read(out/'phase_packets'/(final+'.json')):
                raise ValueError('RETRIEVAL_FINAL_PACKET_CHANGED')
            retrieval_audit.append(dict(arm=arm_name,reads=c.result()['distinct_complete_reads'],stop_reason=c.result()['stop_reason']))
    save(out/'offline_replay.json',dict(status='PASS',inference_http=0,records=audit,retrieval=retrieval_audit,summary=client.summary()))
    print(json.dumps(dict(status='PASS',predictions=len(records),summary=client.summary())),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run','replay']);p.add_argument('--out',type=Path,default=DEFAULT);p.add_argument('--phase',default='factorial');p.add_argument('--live',action='store_true');a=p.parse_args()
    if a.mode=='prepare':prepare(a.out)
    elif a.mode=='run':run(a.out,a.phase,a.live)
    else:replay(a.out)


if __name__=='__main__':main()
