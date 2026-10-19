"""Interim points only for fully paired cohorts; no tuning or partial-cohort F1.

Uses the frozen comparison's existing evaluator and rule. Does not start model
calls, select checkpoints, or replace the final grouped confidence intervals.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
import numpy as np
from v4_analyze import evaluate, read, table
from guardian_truth.judge.mechanical import analyze


def main():
    p=argparse.ArgumentParser();p.add_argument('--lab',type=Path,required=True);a=p.parse_args()
    csv.field_size_limit(2**31-1)
    lab=a.lab;data=lab/'v4-20261019';source=data/'train-v1/scores.jsonl'
    # A trailing line can still be in flight. Earlier complete records must
    # decode; silently skipping an interior malformed record is forbidden.
    lines=source.read_bytes().splitlines();raw=[]
    for i,line in enumerate(lines):
        try:raw.append(json.loads(line))
        except ValueError:
            if i!=len(lines)-1:raise
    lookup={(r['partition'],r['arm'],r['id']):r for r in raw}
    assert len(lookup)==len(raw),'DUPLICATE_SCORE_RECORD'
    index=json.loads((data/'external-combined-v1/INDEX.json').read_bytes())['rows']
    combined={(r['dataset'],r['original_id']):r['id'] for r in index}
    valid={r['id'] for r in table(lab/'runs/valid46_r1/rows.csv')};cohorts={};gold_hashes={}
    for part in ('dev','holdout'):
        gold=read(data/'frozen-v2'/(part+'.jsonl'));inputs=read(data/'frozen-v2'/(part+'_inputs.jsonl'))
        assert len(gold)==len(inputs)
        rows=[]
        for g,r in zip(gold,inputs):
            assert r['id']==g['id']
            rows.append(dict(id=g['id'],partition=part,score_id=g['id'],label=g['label'],group=g['split_component'],
                hard=bool(analyze(r['prompt'],r['response']).hard),shape=False,scores={}))
        cohorts[part]=rows;gold_hashes[part]=hashlib.sha256((data/'frozen-v2'/(part+'.jsonl')).read_bytes()).hexdigest()
    for name,saved in [('regression_seen','regression_r1'),('compli_dev','dev_r1b')]:
        gold=read(lab/'data/guardian-judge-eval-data-v1'/name/'labels.jsonl');ref=table(lab/'runs'/saved/'rows.csv')
        assert len(gold)==len(ref);rows=[]
        for g,r in zip(gold,ref):
            assert g['id']==r['id'] and g['label']==int(r['label'])
            rows.append(dict(id=g['id'],partition='regression_seen',score_id=combined[name,g['id']],label=g['label'],
                group=g.get('conversation') or g.get('group') or g['id'],domain=g['domain'],
                hard=bool(r['hard']),shape=False,scores={'current35b':float(r['score'])}))
        if name=='regression_seen':
            cohorts['seen397']=rows;cohorts['real191']=[r for r in rows if r['domain'] in {'ext_tau2','hold_tau2h','hold_holdout2'}]
            cohorts['valid46']=[r for r in rows if r['id'] in valid]
        else:cohorts['dev520']=rows
    result=dict(status='INTERIM_EXPLORATORY',confidence_intervals_pending=True,private_gain_measured=False,
        human_reviewed=False,new_dev_holdout_35b_reference_pending=True,added_shape_gate=False,
        coverage=dict(Counter(str((r['arm'],r['partition'])) for r in raw)),gold_sha256=gold_hashes,cohorts={})
    import guardian_truth.judge.mechanical as mechanical
    import guardian_truth.transcript.parser as parser
    import guardian_truth.transcript.catalog as catalog
    result['runtime_source_sha256']={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [Path(__file__),Path(mechanical.__file__),Path(parser.__file__),Path(catalog.__file__)]}
    for name,rows in cohorts.items():
        complete=0;receipts=[]
        for r in rows:
            for arm,key in [('base','base4b'),('adapter','v4')]:
                score=lookup.get((r['partition'],arm,r['score_id']))
                if score is not None and score.get('exact') and score.get('score') is not None and np.isfinite(score['score']):
                    r['scores'][key]=score['score'];receipts.append(score)
            complete+=all(k in r['scores'] for k in ('base4b','v4'))
        item=dict(rows=len(rows),paired_rows=complete,complete=complete==len(rows))
        if item['complete']:
            item.update(positive=sum(r['label'] for r in rows),groups=len({r['group'] for r in rows}),
                paired_scores_sha256=hashlib.sha256(json.dumps(receipts,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                point_040=evaluate(rows,np.arange(len(rows)),False,.4)[0])
        result['cohorts'][name]=item
    target=data/'interim-v1.json';temp=target.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');temp.replace(target)
    print(json.dumps(result,allow_nan=False))


if __name__=='__main__':main()
