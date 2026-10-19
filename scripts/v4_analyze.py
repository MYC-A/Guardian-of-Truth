"""Predeclared paired V4 comparisons; no checkpoint, threshold or archive selection."""
import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
import numpy as np
from scipy.stats import rankdata
from sklearn.metrics import roc_auc_score
from v3_analyze_hours import metrics,quota
from v3_analyze_e2 import matched_prefix
from v3_decision_rule import shifted_sample
from v4_shape_gate import scan
from guardian_truth.judge.mechanical import analyze


def read(p):return [json.loads(l) for l in p.read_bytes().splitlines()]
def table(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def evaluate(data,ix,shape=False,rate=.4):
    rows=[data[int(i)] for i in ix];y=np.array([r['label'] for r in rows]);h=np.array([r['hard'] or shape and r['shape'] for r in rows],dtype=bool)
    keys=set.intersection(*(set(r['scores']) for r in rows));scores={k:np.array([r['scores'][k] for r in rows]) for k in sorted(keys)}
    if 'current35b' in scores:
        for name in ('v4','v3'):
            if name in scores:scores['blend_'+name]=(rankdata(scores['current35b'])+rankdata(scores[name]))/(2*len(y))
    predictions={k:np.array(quota(s,set(np.flatnonzero(h)),rate)) for k,s in scores.items()}
    report={k:dict(metrics=metrics(y,p),auc=float(roc_auc_score(y,scores[k])) if len(set(y))==2 else None) for k,p in predictions.items()}
    reference='current35b' if 'current35b' in scores else 'base4b';target=report[reference]['metrics']['tp']
    for k,s in scores.items():
        report[k]['matched_tp']=matched_prefix(y,s,target,h)
        old=predictions[reference];p=predictions[k]
        report[k]['changes']=dict(tp_gained=int(sum((old==0)&(p==1)&(y==1))),tp_lost=int(sum((old==1)&(p==0)&(y==1))),
            fp_removed=int(sum((old==1)&(p==0)&(y==0))),fp_added=int(sum((old==0)&(p==1)&(y==0))))
    return report,reference


def cohort(name,data,out):
    groups=defaultdict(list)
    for i,r in enumerate(data):groups[r['group']].append(i)
    keys=sorted(groups);y=np.array([r['label'] for r in data]);result=dict(rows=len(data),positive=int(sum(y)),groups=len(groups),points={})
    for shape in (False,True):
        mode='bounded_shape' if shape else 'legacy_mechanical'
        # Prior shift is a diagnostic resampling of existing domains, not a
        # simulation or reconstruction of the unseen competition distribution.
        for prior in (None,.12,.20):
            point=mode+':'+('native' if prior is None else str(prior));rng=np.random.default_rng(20261019)
            ix=np.arange(len(data)) if prior is None else shifted_sample(y,prior,rng)
            value,reference=evaluate(data,ix,shape);item=dict(arms=value,reference=reference)
            if prior is None:item['diagnostic_rates']={str(q):evaluate(data,ix,shape,q)[0] for q in (.30,.50)}
            differences=defaultdict(list);raw=[];brng=np.random.default_rng(20261019)
            for rep in range(1000):
                sampled=np.array([i for k in brng.choice(keys,len(keys),replace=True) for i in groups[str(k)]])
                if prior is not None:
                    if len(set(y[sampled]))!=2:continue
                    sampled=sampled[shifted_sample(y[sampled],prior,brng)]
                vv,_=evaluate(data,sampled,shape);ref=vv[reference];entry=dict(rep=rep,arms={})
                for arm,v in vv.items():
                    d=v['metrics']['f1']-ref['metrics']['f1'];differences[arm].append(d)
                    entry['arms'][arm]=dict(f1_delta=d,fp=v['matched_tp']['fp'],tp=v['matched_tp']['tp'])
                raw.append(entry)
            item['paired_f1_ci95']={k:list(map(float,np.quantile(v,[.025,.975]))) for k,v in differences.items() if v}
            with gzip.open(out/(name+'_'+point.replace(':','_')+'_draws.jsonl.gz'),'wt',encoding='utf-8') as f:
                for r in raw:f.write(json.dumps(r)+'\n')
            result['points'][point]=item
    return result


def main():
    p=argparse.ArgumentParser()
    for name in ('run','frozen','protected','saved','combined','old_run','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--reference',type=Path);a=p.parse_args();a.out.mkdir(exist_ok=False);csv.field_size_limit(2**31-1)
    done=json.loads((a.run/'DONE.json').read_bytes());assert done['complete']
    raw=read(a.run/'scores.jsonl');lookup={(r['partition'],r['arm'],r['id']):r for r in raw};assert len(raw)==len(lookup)
    if not all(r['exact'] and r.get('score') is not None and math.isfinite(r['score']) for r in raw):
        write(a.out/'RESULTS.json',dict(status='INCOMPLETE_EXACT_COVERAGE_NO_ACCEPT'));return
    index=json.loads((a.combined/'INDEX.json').read_bytes())['rows'];combined={(r['dataset'],r['original_id']):r['id'] for r in index}
    old={(r['partition'],r['arm'],r['id']):r['score'] for r in read(a.old_run/'scores.jsonl')}
    cohorts={};valid={r['id'] for r in table(a.saved/'valid46_r1/rows.csv')}
    for source,saved in [('regression_seen','regression_r1'),('compli_dev','dev_r1b')]:
        inputs=table(a.protected/source/'inputs.csv');gold=read(a.protected/source/'labels.jsonl');ref=table(a.saved/saved/'rows.csv')
        assert len(inputs)==len(gold)==len(ref);rows=[]
        for r,g,b in zip(inputs,gold,ref):
            assert r['id']==g['id']==b['id'] and int(b['label'])==g['label']
            key=combined[source,r['id']];scores={name:lookup['regression_seen',arm,key]['score'] for name,arm in [('base4b','base'),('v4','adapter')]}
            scores['current35b']=float(b['score'])
            if source=='regression_seen':scores['v3']=old['regression_seen','adapter',r['id']]
            rows.append(dict(id=r['id'],label=g['label'],group=g.get('conversation') or g.get('group') or r['id'],domain=g['domain'],
                hard=bool(b['hard']),shape=bool(scan(r['prompt'],r['response'])['violations']),scores=scores))
        if source=='regression_seen':
            cohorts['seen397']=rows;cohorts['valid46']=[r for r in rows if r['id'] in valid]
            cohorts['real191']=[r for r in rows if r['domain'] in {'ext_tau2','hold_tau2h','hold_holdout2'}]
        else:cohorts['dev520']=rows
    new_ref={r['id']:r for r in table(a.reference/'run/rows.csv')} if a.reference else {}
    for name in ('dev','holdout'):
        gold=read(a.frozen/(name+'.jsonl'));inputs=read(a.frozen/(name+'_inputs.jsonl'));rows=[]
        for g,r in zip(gold,inputs):
            assert g['id']==r['id'];scores={n:lookup[name,arm,r['id']]['score'] for n,arm in [('base4b','base'),('v4','adapter')]}
            if new_ref:scores['current35b']=float(new_ref[r['id']]['score'])
            rows.append(dict(id=r['id'],label=g['label'],group=g['split_component'],domain=g['domain'],
                hard=bool(analyze(r['prompt'],r['response']).hard),shape=bool(scan(r['prompt'],r['response'])['violations']),scores=scores))
        cohorts[name]=rows
    write(a.out/'COHORTS.json',cohorts)
    result=dict(status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',datasets={},full_exact_coverage=True,
        ranking_and_quota_recomputed_in_every_group_draw=True,checkpoint_selected_on_holdout=False,
        prior_shift_is_not_domain_shift=True,production_changed=False,zip_created=False,private_improvement_measured=False,
        adapter_sha256=done['adapter_sha256'],frozen_sha256=hashlib.sha256((a.frozen/'FROZEN.json').read_bytes()).hexdigest())
    for name,data in cohorts.items():
        result['datasets'][name]=cohort(name,data,a.out);write(a.out/'RESULTS.json',result)
        print(json.dumps(dict(event='analyzed',cohort=name,rows=len(data))),flush=True)
    write(a.out/'DONE.json',dict(complete=True,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))


if __name__=='__main__':main()
