"""Label-free protected-input matching and candidate scenario components."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from v3_data import judge_input
from guardian_truth.judge.prompting import system_block


def norm(text):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text).casefold()).strip()


def pairtext(row):
    return row['prompt']+'\0'+row['response']


def neartext(row):
    prompt=row['prompt'];head=system_block(prompt)
    return prompt[len(head):]+'\0'+row['response']


def shingles(text):
    words=re.findall(r'\w+|[^\w\s]',norm(text))
    parts=(' '.join(words[i:i+5]) for i in range(max(1,len(words)-4)))
    return np.unique(np.fromiter((int.from_bytes(hashlib.blake2b(s.encode(),digest_size=4).digest(),'little') for s in parts),dtype=np.uint64))


def ids(text):
    pattern=r'(?i)["\x27]?(user_id|customer_id|order_id|reservation_id|booking_id|line_id|account_id|payment_id|device_id|resource_id)["\x27]?\s*[:=]\s*["\x27]?([a-zA-Z0-9_#-]{4,})'
    return {(m.group(1).casefold(),m.group(2)) for m in re.finditer(pattern,text)}


class NearIndex:
    def __init__(self):
        rng=np.random.default_rng(20261019)
        self.a=rng.integers(1,2**32-5,128,dtype=np.uint64)
        self.b=rng.integers(0,2**32-5,128,dtype=np.uint64)
        self.bands=defaultdict(set);self.values={}

    def keys(self,values):
        # 128 affine MinHash functions over 32-bit shingle digests;32bands x4.
        sig=np.full(128,2**32-5,dtype=np.uint64)
        for start in range(0,len(values),2048):
            h=(self.a[:,None]*values[None,start:start+2048]+self.b[:,None])%np.uint64(2**32-5)
            sig=np.minimum(sig,h.min(1))
        return [(i,sig[i*4:(i+1)*4].tobytes()) for i in range(32)]

    def query(self,values):
        keys=self.keys(values);candidates=set()
        for key in keys:candidates.update(self.bands.get(key,()))
        matches=[]
        for identity in candidates:
            other=self.values[identity];intersection=len(np.intersect1d(values,other,assume_unique=True))
            score=intersection/(len(values)+len(other)-intersection)
            if score>=.8:matches.append((identity,score))
        return matches,keys

    def add(self,identity,values,keys=None):
        self.values[identity]=values
        for key in self.keys(values) if keys is None else keys:self.bands[key].add(identity)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--draft',type=Path,required=True)
    p.add_argument('--protected',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    csv.field_size_limit(2**31-1);a.out.mkdir(exist_ok=False);started=time.time()
    (a.out/'START.json').write_text(json.dumps(dict(started_unix=started,threshold=.8,minhash=128,bands=32,seed=20261019)))
    protected=NearIndex();exact={};entities=set();protected_count=0;file_hashes={}
    for name in ('regression_seen','compli_dev','compli_eval'):
        path=a.protected/name/'inputs.csv';file_hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        with path.open(encoding='utf8',newline='') as f:
            for row in csv.DictReader(f):
                text=pairtext(row);identity=name+':'+row['id'];values=shingles(neartext(row))
                protected.add(identity,values);exact[norm(text)]=identity;entities.update(ids(text));protected_count+=1
        print(json.dumps(dict(event='protected_indexed',dataset=name,total=protected_count)),flush=True)
    rows=[json.loads(line) for line in a.draft.read_bytes().splitlines()]
    parent=list(range(len(rows)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def join(i,j):
        i,j=root(i),root(j)
        if i!=j:parent[max(i,j)]=min(i,j)
    groups={};candidates=NearIndex();reject={};near_links=0
    for i,row in enumerate(rows):
        model=judge_input(row);text=pairtext(model);values=shingles(neartext(model))
        reasons=[]
        if norm(text) in exact:reasons.append(dict(kind='exact_normalized',source=exact[norm(text)]))
        matched,_=protected.query(values)
        reasons.extend(dict(kind='near',source=k,jaccard=v) for k,v in matched)
        overlap=ids(text)&entities
        if overlap:reasons.append(dict(kind='entity_id',values=sorted(overlap)))
        if reasons:reject[i]=reasons
        for field in ('group_id','scenario_id','pair_id'):
            value=row.get(field)
            if value:
                key=(field,value)
                if key in groups:join(i,groups[key])
                else:groups[key]=i
        matched,keys=candidates.query(values)
        for identity,_ in matched:join(i,identity);near_links+=1
        candidates.add(i,values,keys)
        if i%1000==999:print(json.dumps(dict(event='candidate_indexed',rows=i+1)),flush=True)
    banned={root(i) for i in reject};kept=[];excluded=[]
    for i,row in enumerate(rows):
        component='component:'+str(root(i))
        if root(i) in banned:excluded.append(dict(id=row['id'],component=component,reasons=reject.get(i,[dict(kind='shared_scenario_or_pair_with_excluded')])));continue
        row['split_component']=component;row['decontamination_status']='EXACT_NEAR_AND_NAMED_ID_CHECKED_NOT_SEMANTIC_INDEPENDENCE'
        kept.append(row)
    for filename,data in [('candidate_rows.jsonl',kept),('excluded.jsonl',excluded)]:
        with (a.out/filename).open('w',encoding='utf8') as f:
            for row in data:f.write(json.dumps(row,ensure_ascii=True)+'\n')
    result=dict(complete=True,train_ready=False,rows_before=len(rows),rows_after=len(kept),excluded=len(excluded),
        direct_matches=len(reject),protected_rows=protected_count,protected_inputs_sha256=file_hashes,
        protected_named_entity_pairs=len(entities),candidate_near_links=near_links,components=len({r['split_component'] for r in kept}),
        candidate_sha256=hashlib.sha256((a.out/'candidate_rows.jsonl').read_bytes()).hexdigest(),seconds=time.time()-started,
        limitations=['MinHash candidate retrieval is probabilistic; .8 applies to32bit shingle sets',
          'Named entity IDs require explicit key/value syntax; unstructured aliases are not fully covered',
          'No semantic contamination certification; no split or audit/holdout acceptance from this check'])
    (a.out/'DONE.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)


if __name__=='__main__':main()
