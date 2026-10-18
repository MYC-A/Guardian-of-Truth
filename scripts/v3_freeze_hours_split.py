"""Freeze components and source budgets before optimization or quality selection."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from v3_data import judge_input

def stable(x):return hashlib.sha256(('guardian-v3-split:'+x).encode()).hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--pilot',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--training-seconds',type=int,required=True);a=parser.parse_args();a.out.mkdir(exist_ok=False)
    rows=[json.loads(l) for l in a.data.read_bytes().splitlines()];groups=defaultdict(list)
    from v3_decontaminate import ids
    parent={r['split_component']:r['split_component'] for r in rows};owners={}
    def root(key):
        while parent[key]!=key:parent[key]=parent[parent[key]];key=parent[key]
        return key
    def union(left,right):
        left,right=root(left),root(right)
        if left!=right:parent[max(left,right)]=min(left,right)
    for r in rows:
        req=judge_input(r)
        for entity in ids(req['prompt']+'\0'+req['response']):
            if entity in owners:union(r['split_component'],owners[entity])
            else:owners[entity]=r['split_component']
    for r in rows:
        r['pre_entity_component']=r['split_component'];r['split_component']=root(r['split_component'])
        groups[r['split_component']].append(r)
    keys=sorted(groups,key=stable);parts={'holdout':[],'dev':[],'train_pool':[]}
    assigned={};used=set()
    for partition,target in [('holdout',300),('dev',150)]:
        for key in keys:
            if key in used or len(groups[key])>100:continue
            assigned[key]=partition;used.add(key);parts[partition].extend(groups[key])
            if len(parts[partition])>=target:break
    for key in keys:
        if key not in used:assigned[key]='train_pool';parts['train_pool'].extend(groups[key])
    # All occurrences of a named entity across candidate components must share a split.
    # v3_decontaminate groups scenario/pair/near links; enforce entities here too by
    # refusing a split that the grouping phase did not unite (never silently leak).
    entities={}
    for row in rows:
        request=judge_input(row);partition=assigned[row['split_component']]
        for entity in ids(request['prompt']+'\0'+request['response']):
            if entity in entities:assert entities[entity]==partition,('CANDIDATE_ENTITY_SPLIT',entity)
            entities[entity]=partition
    pilot=json.loads(a.pilot.read_bytes());rate=pilot['tokens_per_second']
    token_budget=int(rate*a.training_seconds/1.5)
    limits={'tau2':600,'ToolACE':600,'ToolRM':400,'RAGTruth':200}
    pairs=defaultdict(list)
    for row in parts['train_pool']:pairs[(row['source'],row.get('pair_id') or row['id'])].append(row)
    training=[];counts=Counter();used_tokens=0
    candidates=sorted(pairs,key=lambda x:stable(x[1]));pending=set(candidates)
    while pending:
        progress=False
        for source in limits:
            source_keys=[key for key in candidates if key in pending and key[0]==source]
            if not source_keys:continue
            key=source_keys[0];pending.remove(key);batch=pairs[key];size=sum(r['n_tokens'] for r in batch)
            if counts[source]+len(batch)>limits[source] or used_tokens+size>token_budget:continue
            training.extend(batch);counts[source]+=len(batch);used_tokens+=size;progress=True
        if not progress and not pending:break
    assert training and len(parts['holdout'])>=300 and parts['dev'],'INSUFFICIENT_CLEAN_COMPONENTS'
    positive=sum(r['label'] for r in training);negative=len(training)-positive
    hard=sum(r['is_hard_negative'] for r in training)
    gates=dict(source_cap=max(counts.values())/len(training)<=.40,
               label_balance=.30<=positive/len(training)<=.40,
               hard_negative_fraction=hard/max(1,negative)>=.30,
               long_input_fraction=sum(r['n_tokens']>16384 for r in training)/len(training)>=.20,
               human_review=False)
    # Original long/human gates remain failures, but are explicitly allowed only
    # for this exploratory shortened series. Do not waive the other basic checks.
    assert gates['source_cap'] and gates['label_balance'] and gates['hard_negative_fraction'],gates
    for name,data in [('train',training),('dev',parts['dev']),('holdout',parts['holdout'])]:
        with (a.out/(name+'.jsonl')).open('w',encoding='utf8') as f:
            for row in data:f.write(json.dumps(row)+'\n')
        if name!='train':
            with (a.out/(name+'_inputs.jsonl')).open('w',encoding='utf8') as f:
                for row in data:
                    request=judge_input(row);request.pop('hints');f.write(json.dumps(request)+'\n')
    manifest=dict(status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',train_rows=len(training),train_sources=dict(counts),
        train_positive=positive,hard_negatives=hard,train_tokens=used_tokens,pilot_tokens_per_second=rate,
        selection_token_budget=token_budget,frozen_source_row_caps=limits,training_seconds=a.training_seconds,
        dev_rows=len(parts['dev']),holdout_rows=len(parts['holdout']),component_assignments=assigned,
        gates=gates,source_data_sha256=hashlib.sha256(a.data.read_bytes()).hexdigest(),
        files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.out.glob('*.jsonl')})
    (a.out/'FROZEN.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({k:v for k,v in manifest.items() if k!='component_assignments'}),flush=True)

if __name__=='__main__':main()
