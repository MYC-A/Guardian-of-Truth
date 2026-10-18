"""Local gold analysis after checkpoint freeze; no model, threshold or ZIP changes."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src')]
import numpy as np
from scipy.stats import rankdata
from sklearn.metrics import roc_auc_score,average_precision_score
from guardian_truth.judge.decision import decide

def read(path):return [json.loads(line) for line in path.read_bytes().splitlines()]
def table(path):
    with path.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))
def metrics(y,pred):
    y=np.asarray(y,dtype=int);pred=np.asarray(pred,dtype=int)
    tp=int(np.sum((y==1)&(pred==1)));fp=int(np.sum((y==0)&(pred==1)))
    fn=int(np.sum((y==1)&(pred==0)));tn=int(np.sum((y==0)&(pred==0)))
    return dict(tp=tp,fp=fp,fn=fn,tn=tn,precision=tp/max(1,tp+fp),recall=tp/max(1,tp+fn),
                f1=2*tp/max(1,2*tp+fp+fn),fpr=fp/max(1,fp+tn),false_discovery_rate=fp/max(1,tp+fp))
def quota(scores,hard=(),rate=.4):return decide(len(scores),set(hard),dict(enumerate(map(float,scores))),rate)
def at_recall(y,s,recall=.615,hard=()):
    target=max(sum(y[i] for i in hard),math.ceil(recall*sum(y)))
    chosen=set(hard);tp=sum(y[i] for i in chosen)
    for i in sorted(range(len(y)),key=lambda i:(-s[i],i)):
        if tp>=target:break
        if i not in chosen:chosen.add(i);tp+=y[i]
    return metrics(y,[int(i in chosen) for i in range(len(y))])
def assess(y,s,hard=()):
    both=len(set(y))==2
    return dict(roc_auc=float(roc_auc_score(y,s)) if both else None,
        average_precision=float(average_precision_score(y,s)) if both else None,
        at40=metrics(y,quota(s,hard)),
        diagnostic_quotas={str(q):metrics(y,quota(s,hard,q)) for q in (.3,.5,.6)},
        diagnostic_matched_recall={str(r):at_recall(y,s,r,hard) for r in (.5,.615,.8,.9)})
def paired_ci(y,base,new,groups,hard=()):
    by=defaultdict(list)
    for i,g in enumerate(groups):by[g].append(i)
    keys=sorted(by);rng=np.random.default_rng(20261019);hard=set(hard)
    f1=[];auc=[];fp_reduction=[]
    for _ in range(1000):
        ix=[i for key in rng.choice(keys,len(keys),replace=True) for i in by[str(key)]]
        yy=[y[i] for i in ix];bb=[base[i] for i in ix];nn=[new[i] for i in ix]
        hh={j for j,i in enumerate(ix) if i in hard}
        f1.append(metrics(yy,quota(nn,hh))['f1']-metrics(yy,quota(bb,hh))['f1'])
        if len(set(yy))==2:auc.append(float(roc_auc_score(yy,nn)-roc_auc_score(yy,bb)))
        old=at_recall(yy,bb,hard=hh)['fp'];now=at_recall(yy,nn,hard=hh)['fp']
        if old:fp_reduction.append((old-now)/old)
    def interval(values):return dict(ci95=list(map(float,np.quantile(values,[.025,.975]))) if values else None,valid_replicates=len(values))
    return dict(groups=len(keys),draws=1000,quota_recomputed_within_draw=True,
        f1_difference=interval(f1),auc_difference=interval(auc),matched_615_fp_relative_reduction=interval(fp_reduction),
        matched_recall_thresholds_use_gold_diagnostically_not_deployable=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--frozen',type=Path,required=True)
    p.add_argument('--protected',type=Path,required=True);p.add_argument('--saved',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=False);csv.field_size_limit(2**31-1)
    done=json.loads((a.run/'DONE.json').read_bytes());trained=json.loads((a.run/'TRAINED.json').read_bytes())
    assert done['complete'] and done['adapter_sha256']==trained['adapter_sha256']
    scores=read(a.run/'scores.jsonl');lookup={(r['partition'],r['arm'],r['id']):r for r in scores}
    assert len(scores)==len(lookup),'DUPLICATE_SCORES'
    coverage=all(r['exact'] and r.get('score') is not None and math.isfinite(r['score']) for r in scores)
    result=dict(status='EXPLORATORY_ONLY',full_exact_coverage=coverage,datasets={},human_reviewed=0,
        adapter_sha256=done['adapter_sha256'],training=done,production_accepted=False,zip_created=False)
    if not coverage:
        result['error']='INCOMPLETE_EXACT_COVERAGE_NO_ACCEPT';(a.out/'ANALYSIS.json').write_text(json.dumps(result,indent=2));return
    for partition in ('dev','holdout'):
        gold=read(a.frozen/(partition+'.jsonl'));y=[r['label'] for r in gold]
        ss={arm:[lookup[partition,arm,r['id']]['score'] for r in gold] for arm in ('base','adapter')}
        result['datasets'][partition]=dict(rows=len(y),positive=sum(y),human_verified=False,
            arms={arm:assess(y,s) for arm,s in ss.items()},
            paired=paired_ci(y,ss['base'],ss['adapter'],[r['split_component'] for r in gold]),
            all_yes=metrics(y,[1]*len(y)))
    inputs=table(a.protected/'regression_seen/inputs.csv');gold=read(a.protected/'regression_seen/labels.jsonl')
    saved=table(a.saved/'regression_r1/rows.csv');valid=table(a.saved/'valid46_r1/rows.csv')
    assert len(inputs)==len(gold)==len(saved)==397
    assert [r['id'] for r in inputs]==[r['id'] for r in gold]==[r['id'] for r in saved]
    assert all(g['label']==int(s['label']) for g,s in zip(gold,saved))
    valid_ids={r['id'] for r in valid}
    subsets=dict(seen397=list(range(397)),real191=[i for i,g in enumerate(gold) if g['domain'] in {'ext_tau2','hold_tau2h','hold_holdout2'}],
        valid46=[i for i,r in enumerate(inputs) if r['id'] in valid_ids])
    for name,ix in subsets.items():
        y=[gold[i]['label'] for i in ix];hard={j for j,i in enumerate(ix) if saved[i]['hard']}
        ss={arm:[lookup['regression_seen',arm,inputs[i]['id']]['score'] for i in ix] for arm in ('base','adapter')}
        ss['current35b_max']=[float(saved[i]['score']) for i in ix]
        ss['fixed_equal_rank_blend']=[float(x) for x in (rankdata(ss['current35b_max'])+rankdata(ss['adapter']))/(2*len(ix))]
        result['datasets'][name]=dict(rows=len(ix),positive=sum(y),previously_viewed=True,hard=len(hard),
            arms={arm:assess(y,s,hard) for arm,s in ss.items()},all_yes=metrics(y,[1]*len(y)),
            paired_adapter_vs_base=paired_ci(y,ss['base'],ss['adapter'],[gold[i]['conversation'] for i in ix],hard),
            paired_blend_vs_current=paired_ci(y,ss['current35b_max'],ss['fixed_equal_rank_blend'],[gold[i]['conversation'] for i in ix],hard))
    real=result['datasets']['real191']['arms']['adapter'];val=result['datasets']['valid46']['arms']['adapter']
    result['original_acceptance_gates']=dict(human_review=False,full_v3_long_input_requirement=False,
        real_auc_above_v1=real['roc_auc']>.830780,valid_auc_not_below_base_by_more_than02=val['roc_auc']>=.937618-.02,
        target_gpu_full_submission_runtime_measured=False,
        holdout_fp_improvement_against_current_production_max_measured=False)
    result['limitations']=['Constructed holdout is machine/source checked, not human verified independent competition data',
        'Protected sets are previously viewed; valid46 and real191 are subsets of397',
        '35B saved max uses different context/review pipeline, not a pure model-size comparison',
        'Matched-recall diagnostics use gold and cannot be deployed as fitted thresholds',
        'No platform submission or evidence of leaderboard improvement',
        'Confidence intervals condition on these frozen models; no training-seed uncertainty']
    (a.out/'ANALYSIS.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({name:{arm:dict(f1=v['at40']['f1'],auc=v['roc_auc']) for arm,v in data['arms'].items()} for name,data in result['datasets'].items()},indent=2))

if __name__=='__main__':main()
