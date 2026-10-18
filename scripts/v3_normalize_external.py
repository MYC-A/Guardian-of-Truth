"""Build source-faithful candidate rows, never a train-ready v3 release."""
import argparse
from collections import Counter, defaultdict
import hashlib
import heapq
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from v3_data import canonical, judge_input, pair_hash, training_text, validate

SEED='guardian-v3-20261019'


def stable(text):
    return hashlib.sha256((SEED+'\0'+text).encode()).hexdigest()


def specs(tools):
    return {t.get('function',t)['name']:t.get('function',t) for t in tools}


def structural_errors(calls, tools):
    catalog=specs(tools); errors=[]
    for call in calls:
        f=call.get('function',call);name=f.get('name');args=f.get('arguments')
        if isinstance(args,str):args=json.loads(args)
        if name not in catalog:errors.append('unknown_function');continue
        if not isinstance(args,dict):errors.append('arguments_not_object');continue
        raw=catalog[name].get('parameters',{})
        props=raw.get('properties',{}) if raw.get('type')=='object' or 'properties' in raw else raw
        if not isinstance(props,dict):raise ValueError('UNSUPPORTED_TOOL_SPEC')
        if any(k not in props for k in args):errors.append('undeclared_parameter')
        if isinstance(raw.get('required'),list) and any(k not in args for k in raw['required']):errors.append('missing_required')
    return sorted(set(errors))


def trm_history(messages):
    result=[];last_name=None
    for i,m in enumerate(messages):
        role=m['role'];content=m['content']
        if role=='assistant_tool_call':
            calls=json.loads(content)
            if not isinstance(calls,list) or len(calls)!=1:raise ValueError('AMBIGUOUS_PARALLEL_HISTORY_RESULTS')
            last_name=calls[0].get('function',calls[0])['name']
            row=dict(id=f'm{i}',role='assistant',content='',tool_calls=calls)
        elif role=='tool':
            if last_name is None:raise ValueError('UNBOUND_SOURCE_TOOL_RESULT')
            row=dict(id=f'm{i}',role='tool',name=last_name,content=content);last_name=None
        elif role in ('user','assistant','system'):
            row=dict(id=f'm{i}',role=role,content=content)
        else:raise ValueError('UNSUPPORTED_SOURCE_ROLE')
        result.append(row)
    return result


def toolrm_candidates(payload, revision, counts):
    import pyarrow as pa
    import pyarrow.ipc as ipc
    pools=defaultdict(list)
    for path in sorted(payload.glob('*.arrow')):
        with pa.memory_map(str(path),'r') as handle:
            for batch in ipc.open_stream(handle):
                for r in batch.to_pylist():
                    counts['ToolRM:raw_pairs']+=1
                    try:
                        tools=json.loads(r['tools']);good=json.loads(r['tool_calls_correct']);bad=json.loads(r['tool_calls_incorrect'])
                        if not isinstance(good,list) or not isinstance(bad,list):raise ValueError('NON_LIST_TARGET')
                        if not good:raise ValueError('NO_CALL_PAIR_HAS_NO_SOURCE_ASSISTANT_TEXT')
                        if structural_errors(good,tools):raise ValueError('CORRECT_CALL_SCHEMA_CONFLICT')
                        errors=structural_errors(bad,tools)
                        if not errors:raise ValueError('INCORRECT_ONLY_SEMANTIC_OR_EQUIVALENT_NOT_AUTOPROVEN')
                        history=trm_history(r['conversation'])
                        # Canonical user dialogue binds model/obfuscation variants to one scenario.
                        scenario=stable(canonical([m['content'].strip().casefold() for m in history if m['role']=='user']))
                        policy=('Use tools only when required to fulfill the user request. Use only tools and parameter names '
                                'declared in the available catalog. Required parameters must be supplied. '
                                'All argument values must be supported by the user request and earlier tool results.')
                        common=dict(source='ToolRM',source_revision=revision,domain=r['dataset_name'],family=errors[0],
                            scenario_id='toolrm:'+scenario,group_id='toolrm:'+scenario,pair_id='toolrm:'+r['uuid'],
                            policy=policy,tools=tools,history=history,governing_rule=policy,
                            evidence_msg_ids=[m['id'] for m in history],label_origin='upstream',is_hard_negative=False,
                            n_tokens=0,license='Apache-2.0',source_generator=r['generator_model'],
                            audit_status='NOT_AUDITED_NOT_TRAIN_READY',source_error_evidence=errors)
                        rows=[]
                        for label,calls in ((0,good),(1,bad)):
                            row=dict(common,id='toolrm:'+r['uuid']+':'+str(label),label=label,
                                     target_turn=dict(role='assistant',content='',tool_calls=calls),
                                     violation_type='tool_args' if label else 'none')
                            validate(row);rows.append(row)
                        stratum=(r['dataset_name'],errors[0]);key=int(stable(r['uuid']),16)
                        item=(-key,r['uuid'],rows)
                        heap=pools[stratum]
                        if len(heap)<500:heapq.heappush(heap,item)
                        elif key < -heap[0][0]:heapq.heapreplace(heap,item)
                        counts['ToolRM:structurally_eligible_pairs']+=1
                    except (ValueError,KeyError,TypeError,AssertionError) as e:
                        counts['ToolRM:excluded:'+str(e)[:100]]+=1
        print(json.dumps(dict(event='scanned',file=path.name,raw_pairs=counts['ToolRM:raw_pairs'])),flush=True)
    ordered={key:sorted(heap,key=lambda v:-v[0]) for key,heap in pools.items()}
    used=set();out=[];offset=0
    while len(out)<3000:
        changed=False
        for key in sorted(ordered):
            items=ordered[key]
            if offset>=len(items):continue
            changed=True;rows=items[offset][2];scenario=rows[0]['scenario_id']
            if scenario in used:continue
            used.add(scenario);out.extend(rows)
            if len(out)>=3000:break
        if not changed:break
        offset+=1
    counts['ToolRM:selected_pairs']=len(out)//2
    return out


def rag_candidates(payload, revision, counts):
    sources={r['source_id']:r for r in (json.loads(line) for line in (payload/'source_info.jsonl').read_bytes().splitlines())}
    buckets={0:[],1:[]}
    for line in (payload/'response.jsonl').read_bytes().splitlines():
        r=json.loads(line);counts['RAGTruth:raw_responses']+=1
        if r['split']!='train' or r['quality']!='good':counts['RAGTruth:excluded_split_or_quality']+=1;continue
        labels=r['labels']
        if labels and not any(v['label_type'].startswith('Evident ') for v in labels):
            counts['RAGTruth:excluded_subtle_only_materiality_ambiguous']+=1;continue
        label=int(bool(labels));s=sources[r['source_id']]
        policy='Use only facts supported by the retrieved context. Do not invent or contradict facts. If evidence is insufficient, say so.'
        question=s['source_info'].get('question') if isinstance(s['source_info'],dict) else None
        user=question or {'Summary':'Summarize the supplied context.','Data2txt':'Describe the supplied structured record.'}.get(s['task_type'],'Answer using the supplied context.')
        context=s['source_info']
        tools=[dict(name='retrieve_context',description='Read-only access to the task context.',parameters={})]
        history=[dict(id='m0',role='user',content=user),dict(id='m1',role='assistant',content='',tool_calls=[dict(name='retrieve_context',arguments={})]),
                 dict(id='m2',role='tool',name='retrieve_context',content=context)]
        row=dict(id='ragtruth:'+r['id'],source='RAGTruth',source_revision=revision,domain=s['task_type'],family='grounded_response',
                 scenario_id='ragtruth:'+r['source_id'],group_id='ragtruth:'+r['source_id'],pair_id=None,policy=policy,tools=tools,
                 history=history,target_turn=dict(role='assistant',content=r['response']),label=label,
                 violation_type='unsupported_fact' if label else 'none',governing_rule=policy,evidence_msg_ids=['m2'],
                 label_origin='upstream',is_hard_negative=False,n_tokens=0,license='MIT',
                 audit_status='NOT_AUDITED_NOT_TRAIN_READY',source_dataset=s['source'],
                 source_label_types=sorted({v['label_type'] for v in labels}),
                 adaptation='Original source context exposed as a synthetic read-tool result; no genuine tool execution')
        validate(row);buckets[label].append(row)
    out=[];used=set()
    # Draft balance only; no claim of final source caps, hard negatives or15k size.
    for label,target in ((0,1700),(1,300)):
        taken=0
        for row in sorted(buckets[label],key=lambda r:stable(r['id'])):
            if row['scenario_id'] in used:continue
            out.append(row);used.add(row['scenario_id']);taken+=1
            if taken>=target:break
        counts['RAGTruth:selected:'+str(label)]=taken
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    a.out.mkdir(exist_ok=False);start=time.time()
    (a.out/'START.json').write_text(json.dumps(dict(started_unix=start,seed=SEED,training_started=False)))
    counts=Counter();inventory=json.loads((a.root/'source-inventory/sources_manifest.json').read_bytes())
    revisions={r['repository']:r['revision'] for r in inventory['sources']}
    payload=a.root/'payloads'
    for r in json.loads((payload/'DOWNLOADS.json').read_bytes()):
        assert r['complete'];path=payload/r['file'];assert hashlib.sha256(path.read_bytes()).hexdigest()==r['sha256']
    rows=toolrm_candidates(payload,revisions['ibm-research/ToolRM-train-data'],counts)
    rows+=rag_candidates(payload,revisions['ParticleMedia/RAGTruth'],counts)
    from transformers import AutoTokenizer
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    verified=json.loads((a.model/'VERIFIED.json').read_bytes());assert verified['revision']=='cdbee75f17c01a7cc42f958dc650907174af0554'
    hashes={};conflicts=set();kept=[];token_lengths=[]
    for row in rows:
        try:
            _,count=training_text(tok,row,32768)
        except ValueError:
            counts[row['source']+':over_cap_excluded']+=1;continue
        row['n_tokens']=count;key=pair_hash(row)
        if key in hashes:
            counts['duplicate_pairs']+=1
            if hashes[key]['label']!=row['label']:conflicts.add(key)
            continue
        hashes[key]=row;kept.append(row);token_lengths.append(count)
    kept=[r for r in kept if pair_hash(r) not in conflicts]
    # Never publish a lone contrast twin after a cap/conflict exclusion.
    pairs=Counter(r['pair_id'] for r in kept if r['pair_id'])
    kept=[r for r in kept if r['pair_id'] is None or pairs[r['pair_id']]==2]
    counts['conflicting_input_hashes_removed']=len(conflicts)
    target=a.out/'candidate_rows.jsonl'
    with target.open('w',encoding='utf8') as f:
        for row in kept:f.write(json.dumps(row,ensure_ascii=True)+'\n')
    stats=dict(rows=len(kept),positive=sum(r['label'] for r in kept),sources=dict(Counter(r['source'] for r in kept)),
        domains=dict(Counter(r['domain'] for r in kept)),families=dict(Counter(r['family'] for r in kept)),
        over_16k=sum(r['n_tokens']>16384 for r in kept),max_tokens=max((r['n_tokens'] for r in kept),default=0),
        hard_negatives=sum(r['is_hard_negative'] for r in kept),counts=dict(counts),
        candidate_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),seconds=time.time()-start,
        complete=True,train_ready=False,training_started=False,
        outstanding=['tau2 natural simulations and paired perturbations',
          'CompliBench generator missing from published revision','protected near-duplicate and source-entity audit',
          '30 percent renaming and semantic paraphrase verification','35B disagreement and5percent label audit',
          'human-reviewed frozen holdout and100 paraphrase reviews','source caps,15-25k size,20percent long inputs and hard-negative quota',
          'final group/scenario/pair split and training protocol'])
    (a.out/'DONE.json').write_text(json.dumps(stats,indent=2));print(json.dumps(stats),flush=True)


if __name__=='__main__':main()
