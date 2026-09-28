"""Exploratory replay: complete-link and constrained correlation partition.

Only SAME edges may join members. UNKNOWN/RELATED/DIFFERENT and absent
pairs all forbid a merge. Exact clique partition maximizes retained SAME
agreements, with complete transitivity by construction. Uses saved pair
decisions, never gold. This replay follows inspection of E3 and is not a
new sealed algorithm-selection experiment.
"""
from __future__ import annotations
import json
import shutil
import sys
from functools import lru_cache
from pathlib import Path
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE.parent/'event_canon_v1'))
from ec_cluster import build_clusters
from ec_track_b import cluster_to_nodes

SOURCE=HERE/'outputs'
TARGET=HERE/'outputs_clustering'


def correlation_partition(mids,pairs):
    mids=sorted(mids)
    if len(mids)>16:
        return build_clusters(pairs,'cl'), 'size_bound_complete_link'
    labs={tuple(sorted((r['a'],r['b']))):r['label'] for r in pairs}
    cliques={}
    for mask in range(1,1<<len(mids)):
        ids=[i for i in range(len(mids)) if mask&(1<<i)]
        if all(labs.get(tuple(sorted((mids[i],mids[j]))))=='SAME_EVENT'
               for i in ids for j in ids if i<j):
            cliques[mask]=len(ids)*(len(ids)-1)//2
    @lru_cache(None)
    def solve(remaining):
        if not remaining: return (0,())
        first=remaining&-remaining
        options=[]
        for mask,weight in cliques.items():
            if mask&first and mask&remaining==mask:
                score,partition=solve(remaining^mask)
                options.append((score+weight,tuple(sorted((mask,)+partition))))
        # Fixed tie order; no labels, domain names, or test metric involved.
        bestscore=max(x[0] for x in options)
        return min(x for x in options if x[0]==bestscore)
    _,partition=solve((1<<len(mids))-1)
    return {mid:k for k,mask in enumerate(partition) for i,mid in enumerate(mids) if mask&(1<<i)}, 'exact_clique_partition'


def main():
    cases=json.loads((HERE/'frozen/frozen_cases.json').read_text(encoding='utf-8'))
    manifest={'status':'exploratory replay after E3 inspection; no test-based selection',
              'methods':['complete_link','constrained_correlation'],
              'merge_requirement':'every cross-pair explicitly SAME_EVENT',
              'objective':'maximize within-cluster SAME pairs; deterministic mask tie order'}
    reuse=[]
    def fingerprint(nodes):
        return [{k:n[k] for k in ('span','start','role','governed_tools','members')} for n in nodes]
    for case in cases:
        cid=case['case_id']
        for directory in ('FRONTEND','ALIGNMENT'):
            (TARGET/directory).mkdir(parents=True,exist_ok=True)
            shutil.copy2(SOURCE/directory/f'{cid}.json',TARGET/directory/f'{cid}.json')
        for src in ('CANON_F','EVENTNESS_CANON_F'):
            data=json.loads((SOURCE/f'TRACKB_{src}'/f'{cid}.json').read_text(encoding='utf-8'))
            for method in ('CL','CORR'):
                if method=='CL':
                    assignment=build_clusters(data['pair_src'],'cl'); algorithm='complete_link'
                else:
                    assignment,algorithm=correlation_partition([m['mid'] for m in data['mentions']],data['pair_src'])
                nodes=cluster_to_nodes(case,data['mentions'],assignment)
                for node in nodes:
                    same=next((n for n in data['nodes'] if set(n['members'])==set(node['members'])),None)
                    # Identical clusters preserve previously frozen attributes
                    # rather than resampling majority-vote ties.
                    if same:
                        for k in ('role','governed_tools','span','start'): node[k]=same[k]
                folder=TARGET/f'TRACKB_{src}_{method}'; folder.mkdir(parents=True,exist_ok=True)
                (folder/f'{cid}.json').write_text(json.dumps({**data,'assign':assignment,'nodes':nodes,
                                                            'algorithm':algorithm},indent=2)+'\n',encoding='utf-8')
                old=SOURCE/f'DOWNSTREAM_canon_TRACKB_{src}_ms_E'/f'{cid}.json'
                if fingerprint(nodes)==fingerprint(data['nodes']) and old.exists():
                    dest=TARGET/f'DOWNSTREAM_canon_TRACKB_{src}_{method}_ms_C'
                    dest.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(old,dest/old.name)
                    reuse.append({'case_id':cid,'arm':f'{src}_{method}','source':str(old.relative_to(HERE)),
                                  'reason':'identical ordered node spans/start/roles/tools/members; same frontend and relation stack'})
                print(cid,src,method,len(nodes))
    (TARGET/'protocol.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    (TARGET/'reused_predictions.json').write_text(json.dumps(reuse,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__': main()
