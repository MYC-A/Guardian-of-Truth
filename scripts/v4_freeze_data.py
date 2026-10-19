"""Audit, decontaminate and freeze V4 inputs BEFORE optimization.

New source components form evaluation; old TRAIN components are pinned to TRAIN.
No protected labels, prior model predictions or quality metrics enter selection.
"""
import argparse
from collections import Counter,defaultdict
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import time
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
from jsonschema import Draft202012Validator
from v3_data import validate,canonical
from v3_decontaminate import NearIndex,ids,shingles,neartext,norm,pairtext
from v4_data import judge_input,training_text
from v4_shape_gate import scan


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def stable(s):return hashlib.sha256(('guardian-v4-freeze:'+s).encode()).hexdigest()
def read(path):return [json.loads(l) for l in path.read_bytes().splitlines()]
def write(path,data):path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def template(r):return r['domain'],r['family'],r.get('template_id','legacy:'+r['family'])
def pair_key(r):return r.get('pair_id') or r['id']
def group_keys(r):return [(field,r[field]) for field in ('scenario_id','group_id','pair_id') if r.get(field)]


def audit(r):
    validate(r);req=judge_input(r)
    from guardian_truth.transcript import parse_document
    p=parse_document(req['prompt']);t=parse_document(req['response'],'response')
    assert not p.diagnostics and not t.diagnostics,'TRANSCRIPT_PARSE'
    assert len(t.messages)==1 and t.messages[0].role=='assistant','CURRENT_TARGET_NOT_ONE_ASSISTANT'
    if r['label']==0:
        assert not scan(req['prompt'],req['response'])['violations'],'CORRECT_TWIN_SHAPE_VIOLATION'
        functions={x.get('function',x)['name']:x.get('function',x) for x in r['tools']}
        for c in r['target_turn'].get('tool_calls') or []:
            f=c.get('function',c);assert f['name'] in functions,'CORRECT_TWIN_UNKNOWN_TOOL'
            args=f['arguments'];args=json.loads(args) if isinstance(args,str) else args
            assert not list(Draft202012Validator(functions[f['name']]['parameters']).iter_errors(args)),'CORRECT_TWIN_SCHEMA'
        if r.get('construction_origin')=='NATIVE_DB_CONSTRUCTED_NOT_REFERENCE_DIALOGUE':
            assert r['proof']['native_target_execution']['complete'],'CORRECT_TWIN_NATIVE_FAILURE'
    return req


def alias_pair(rows):
    """Rename identifiers everywhere, including schema required/$ref and receipts.

    Selected AFTER decontamination. No entity ID changes; original receipts and
    inverse map remain available. Not counted as extra templates or examples.
    """
    key=rows[0].get('pair_id') or rows[0]['id']
    if int(stable('rename:'+key)[:8],16)/2**32>=.30:return rows
    names=set();params=set()
    def properties(schema):
        if isinstance(schema,dict):
            for k,v in schema.items():
                if k=='properties':params.update(v)
                properties(v)
        elif isinstance(schema,list):
            for v in schema:properties(v)
    for t in rows[0]['tools']:
        f=t.get('function',t);names.add(f['name']);properties(f.get('parameters',{}))
    mapping={k:'tool_'+stable(k)[:10] for k in names}
    mapping.update({k:'arg_'+stable(k)[:10] for k in params if k not in names})
    if not mapping:return rows
    pattern=re.compile(r'(?<![A-Za-z0-9_])(?:'+'|'.join(re.escape(k) for k in sorted(mapping,key=lambda k:(-len(k),k)))+r')(?![A-Za-z0-9_])')
    def rename(x):
        if isinstance(x,str):return pattern.sub(lambda m:mapping[m.group()],x)
        if isinstance(x,dict):return {mapping.get(k,k):rename(v) for k,v in x.items()}
        if isinstance(x,list):return [rename(v) for v in x]
        return x
    def schema(x):
        if isinstance(x,dict):
            out={}
            for k,v in x.items():
                if k=='properties':out[k]={mapping.get(n,n):schema(s) for n,s in v.items()}
                elif k=='required':out[k]=[mapping.get(n,n) for n in v]
                elif k=='description':out[k]=rename(v)
                elif k in {'enum','const','default','$ref','type','title'}:out[k]=copy.deepcopy(v)
                else:out[k]=schema(v)
            return out
        if isinstance(x,list):return [schema(v) for v in x]
        return x
    def message(m):
        m=copy.deepcopy(m);m['content']=rename(m.get('content') or '')
        if m.get('name'):m['name']=mapping.get(m['name'],m['name'])
        for c in m.get('tool_calls') or []:
            f=c.get('function',c);f['name']=mapping.get(f['name'],f['name']);f['arguments']=rename(f['arguments'])
        return m
    def tools(ts):
        ts=copy.deepcopy(ts)
        for t in ts:
            f=t.get('function',t);f['name']=mapping[f['name']]
            if 'description' in f:f['description']=rename(f['description'])
            f['parameters']=schema(f['parameters'])
        return ts
    out=[]
    for r in rows:
        c=copy.deepcopy(r)
        for k in ('policy','governing_rule'):c[k]=rename(c[k])
        c['tools']=tools(c['tools']);c['history']=[message(m) for m in c['history']];c['target_turn']=message(c['target_turn'])
        c['alias_map']=mapping;c['original_source_input_sha256']=stable(canonical(judge_input(r)))
        # Proof remains the actual unrenamed native execution; do not fabricate
        # an execution receipt for APIs that do not exist in the native env.
        c['alias_execution_binding']='inverse alias_map recovers original native receipt'
        out.append(c)
    return out


def main():
    a=argparse.ArgumentParser();a.add_argument('--drafts',type=Path,nargs='+',required=True)
    a.add_argument('--legacy',type=Path,required=True);a.add_argument('--protected',type=Path,required=True)
    a.add_argument('--old-frozen',type=Path,required=True);a.add_argument('--model',type=Path,required=True)
    a.add_argument('--preview',action='store_true',help='component/source inventory only; never write FROZEN')
    a.add_argument('--out',type=Path,required=True);a=a.parse_args();a.out.mkdir(exist_ok=False);start=time.time()
    csv.field_size_limit(2**31-1);protected=NearIndex();entities=set();exact=set();hashes={};pn=0
    for name in ('regression_seen','compli_dev','compli_eval'):
        path=a.protected/name/'inputs.csv';hashes[str(path)]=sha(path)
        with path.open(newline='') as f:
            for r in csv.DictReader(f):
                text=pairtext(r);protected.add('benchmark:'+name+':'+r['id'],shingles(neartext(r)));entities.update(ids(text));exact.add(norm(text));pn+=1
    for name in ('dev','holdout','stress'):
        path=a.old_frozen/(name+'_inputs.jsonl');hashes[str(path)]=sha(path)
        for r in read(path):
            text=pairtext(r);protected.add('old_eval:'+name+':'+r['id'],shingles(neartext(r)));entities.update(ids(text));exact.add(norm(text));pn+=1
    print(json.dumps(dict(event='protected_index',rows=pn,entities=len(entities))),flush=True)
    rows=[];excluded=[];seen_ids=set();bad_pairs=set()
    for path in a.drafts+[a.legacy]:
        hashes[str(path)]=sha(path)
        for r in read(path):
            assert r['id'] not in seen_ids,('DUPLICATE_SOURCE_ROW',r['id'])
            seen_ids.add(r['id'])
            r=copy.deepcopy(r);r['legacy_train']=path==a.legacy
            if r['legacy_train']:r['template_id']='legacy:'+r['family']
            try:request=audit(r)
            except Exception as e:
                bad_pairs.add(r.get('pair_id') or r['id'])
                excluded.append(dict(id=r.get('id'),reason='SOURCE_AUDIT',error_type=type(e).__name__,error=str(e).splitlines()[0][:600]));continue
            rows.append(r)
    retained=[]
    for r in rows:
        if (r.get('pair_id') or r['id']) in bad_pairs:
            excluded.append(dict(id=r['id'],reason='TWIN_SOURCE_AUDIT_FAILED'))
        else:retained.append(r)
    rows=retained
    parent=list(range(len(rows)));groups={};candidate=NearIndex();owner={};reasons={};old=set()
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def join(i,j):
        i,j=root(i),root(j)
        if i!=j:parent[max(i,j)]=min(i,j)
    for i,r in enumerate(rows):
        request=judge_input(r);text=pairtext(request);values=shingles(neartext(request));why=[]
        if norm(text) in exact:why.append('EXACT_PROTECTED_INPUT')
        overlap=ids(text)&entities
        if overlap:why.append(dict(entity_overlap=sorted(overlap)))
        matches,_=protected.query(values)
        if matches:why.append(dict(near_protected=matches))
        if why:reasons[i]=why
        for key in group_keys(r):
            if key in groups:join(i,groups[key])
            else:groups[key]=i
        for entity in ids(text):
            if entity in owner:join(i,owner[entity])
            else:owner[entity]=i
        matches,keys=candidate.query(values)
        for j,_ in matches:join(i,j)
        candidate.add(i,values,keys)
        if r['legacy_train']:old.add(i)
        if i%200==0:print(json.dumps(dict(event='grouped',rows=i+1,total=len(rows))),flush=True)
    banned={root(i) for i in reasons};pinned={root(i) for i in old};components=defaultdict(list)
    for i,r in enumerate(rows):
        if root(i) in banned:
            excluded.append(dict(id=r['id'],reason='PROTECTED_COMPONENT',component=root(i),matches=reasons.get(i,['SHARED_COMPONENT'])));continue
        r['split_component']='v4-component:'+str(root(i));components[root(i)].append(r)
    assignments={};eval_parts={};keys=sorted(components,key=lambda k:stable(str(k)))
    for name,target in [('holdout',300),('dev',150)]:
        chosen=[]
        for k in keys:
            if k in pinned or k in assignments:continue
            assignments[k]=name;chosen.extend(components[k])
            if len(chosen)>=target:break
        eval_parts[name]=chosen
    train_pool=[r for k in keys if k not in assignments for r in components[k]]
    # Complete-pair template caps, source limits and external fraction. Selection
    # is independent of scores. Preserve old TRAIN lineage, never evaluation.
    pairs=defaultdict(list)
    for r in train_pool:pairs[pair_key(r)].append(r)
    training=[];caps=Counter();external=[];legacy=[]
    for k in sorted(pairs,key=stable):
        batch=pairs[k];key=template(batch[0]);n=len(batch)
        if caps[key]+n>60:
            excluded.extend(dict(id=r['id'],reason='TEMPLATE_CAP_60') for r in batch);continue
        caps[key]+=n
        if batch[0]['source']!='tau2':external.append(batch)
        elif batch[0]['legacy_train']:legacy.append(batch)
        else:training.extend(batch)
    # Native legacy and current contrast rows are kept; old external rows never
    # get a second/new source allocation on top of the total <=15% cap.
    for batch in legacy:training.extend(batch)
    max_external=int(len(training)*.15/.85)
    for batch in external:
        if len(batch)<=max_external:training.extend(batch);max_external-=len(batch)
        else:excluded.extend(dict(id=r['id'],reason='TOTAL_EXTERNAL_CAP_15_PERCENT') for r in batch)
    if a.preview:
        (a.out/'excluded.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in excluded),encoding='utf-8')
        result=dict(status='PREVIEW_NOT_FROZEN_NOT_TRAIN_READY',components=len(components),
            new_components=sum(k not in pinned for k in components),excluded=len(excluded),
            partitions={name:dict(rows=len(data),by_domain=dict(Counter(r['domain'] for r in data)),
                by_family=dict(Counter(r['family'] for r in data)),natural=sum(r.get('natural_trajectory',False) for r in data))
                for name,data in dict(train=training,**eval_parts).items()},source_sha256=hashes,seconds=time.time()-start)
        write(a.out/'PREVIEW.json',result);print(json.dumps(result),flush=True);return
    assert training and eval_parts['dev'] and eval_parts['holdout'],'NO_CLEAN_NEW_TRAIN_OR_EVAL_COMPONENTS'
    from transformers import AutoTokenizer
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    # Aliases are applied to whole pairs only after grouping/exclusion. Any alias
    # identifier/schema issue excludes the pair, never silently changes its gold.
    def finalize(data):
        batches=defaultdict(list)
        for r in data:batches[pair_key(r)].append(r)
        kept=[]
        for k in sorted(batches,key=stable):
            batch=alias_pair(batches[k])
            try:
                for r in batch:
                    audit(r);r['n_tokens']=training_text(tok,r,32768)[1]
            except Exception as e:
                excluded.extend(dict(id=r['id'],reason='RENDER_ALIAS_OR_CONTEXT_AUDIT',error=str(e)) for r in batch);continue
            kept.extend(batch)
        return kept
    parts={'train':finalize(training),'dev':finalize(eval_parts['dev']),'holdout':finalize(eval_parts['holdout']),'stress':[]}
    assert parts['train'] and parts['dev'] and parts['holdout'],'FINALIZATION_EMPTY_PARTITION'
    sources=Counter(r['source'] for r in parts['train']);total=len(parts['train'])
    assert sum(n for s,n in sources.items() if s!='tau2')/total<=.15,'POST_RENDER_EXTERNAL_CAP'
    partitions={}
    for name,data in parts.items():
        for r in data:
            k=r['split_component'];assert k not in partitions or partitions[k]==name,'COMPONENT_LEAK';partitions[k]=name
        (a.out/(name+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in data),encoding='utf-8')
        if name!='train':
            requests=[]
            for r in data:
                req=judge_input(r);req.pop('hints');requests.append(req)
            (a.out/(name+'_inputs.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests),encoding='utf-8')
    (a.out/'excluded.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in excluded),encoding='utf-8')
    stats={name:dict(rows=len(data),positive=sum(r['label'] for r in data),natural=sum(r.get('natural_trajectory',False) for r in data),
        legacy=sum(r['legacy_train'] for r in data),tokens=sum(r['n_tokens'] for r in data),max_tokens=max((r['n_tokens'] for r in data),default=0),
        over16k=sum(r['n_tokens']>16384 for r in data),sources=dict(Counter(r['source'] for r in data)),
        templates={str(k):v for k,v in Counter(template(r) for r in data).items()}) for name,data in parts.items()}
    manifest=dict(status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',complete=True,renderer='v4_explicit_current_assistant_header',
        stats=stats,files={p.name:sha(p) for p in a.out.glob('*.jsonl')},source_files=hashes,component_partitions=partitions,
        excluded=len(excluded),candidate_components=len(components),old_train_components_pinned=len(pinned),human_reviewed=False,
        protected_labels_used=False,private_test_improvement_measured=False,absolute_acceptance=False,
        gates=dict(external_fraction=sum(n for s,n in sources.items() if s!='tau2')/total,template_cap=60,
                   label_positive_fraction=stats['train']['positive']/total,
                   original_label_balance_30_to40=.30<=stats['train']['positive']/total<=.40,
                   long_input_fraction=stats['train']['over16k']/total,human_review=False,new_holdout_rows=stats['holdout']['rows']),
        script_sha256=sha(Path(__file__)),seconds=time.time()-start)
    write(a.out/'FROZEN.json',manifest);print(json.dumps({k:v for k,v in manifest.items() if k not in {'stats','files','source_files','component_partitions'}}),flush=True)


if __name__=='__main__':main()
