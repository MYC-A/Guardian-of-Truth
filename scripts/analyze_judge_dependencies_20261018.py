"""Offline dependency audit of existing experiments; ZERO model calls or fitting.

Reads historical Git blobs directly (Windows-incompatible ':' paths need no
checkout). Local saved Granite/JEV scores are optional diagnostic inputs, never
used to fit a threshold/weight or select a runtime profile. All valid46 is seen.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
FILES=['result-structured_granite-original4800.json','result-structured_granite-headtail_matched.json',
       'result-structured_granite-structured10000.json','result-jev_eval_head-jev_headtail.json',
       'result-jev_eval_head-jev_structured.json']
GOLDS={'ext_tau2':'outputs/verification_v4/external/tau2v2/GOLD_eval_only.json',
       'hold_tau2h':'outputs/universal_repair/holdout/tau2h/GOLD_frozen.json',
       'hold_holdout2':'outputs/guardian_v6/holdout2/GOLD_frozen.json',
       'lb_long':'outputs/verification_v2/lockbox/long/GOLD_eval_only.json',
       'lb2_long':'outputs/verification_v2/lockbox2/long/GOLD_eval_only.json',
       'lb3_long':'outputs/verification_v2/lockbox3/long/GOLD_eval_only.json'}


def sha(data):return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,stderr=subprocess.PIPE)


def metrics(y,pred):
    tp=sum(a==1 and b==1 for a,b in zip(y,pred));fp=sum(a==0 and b==1 for a,b in zip(y,pred))
    fn=sum(a==1 and b==0 for a,b in zip(y,pred));tn=sum(a==0 and b==0 for a,b in zip(y,pred))
    return dict(tp=tp,fp=fp,fn=fn,tn=tn,f1=2*tp/(2*tp+fp+fn) if tp+fp+fn else 0.,
                precision=tp/(tp+fp) if tp+fp else 0.,recall=tp/(tp+fn) if tp+fn else 0.)


def rank_metrics(y,scores):
    pos=[s for y_,s in zip(y,scores) if y_];neg=[s for y_,s in zip(y,scores) if not y_]
    auc=sum((a>b)+.5*(a==b) for a in pos for b in neg)/(len(pos)*len(neg))
    tp=fp=0;ap=0.
    for s in sorted(set(scores),reverse=True):
        ys=[y_ for y_,v in zip(y,scores) if v==s]
        add=sum(ys);tp+=add;fp+=len(ys)-add
        ap+=add/len(pos)*tp/(tp+fp)
    return dict(roc_auc=auc,average_precision=ap)


def corr(x,y):
    mx=sum(x)/len(x);my=sum(y)/len(y)
    dx=[v-mx for v in x];dy=[v-my for v in y]
    denom=math.sqrt(sum(v*v for v in dx)*sum(v*v for v in dy))
    return sum(a*b for a,b in zip(dx,dy))/denom if denom else None


def ranks(xs):
    values={v:(sum(t<v for t in xs)+(sum(t==v for t in xs)+1)/2) for v in set(xs)}
    return [values[v] for v in xs]


def prevalence_projection(counts,pi):
    tpr=counts['tp']/(counts['tp']+counts['fn']);fpr=counts['fp']/(counts['fp']+counts['tn'])
    tp=pi*tpr;fp=(1-pi)*fpr;fn=pi*(1-tpr)
    return dict(assumed_positive_rate=pi,tpr_held_fixed=tpr,fpr_held_fixed=fpr,
                precision=tp/(tp+fp),recall=tpr,f1=2*tp/(2*tp+fp+fn),
                interpretation='COUNTERFACTUAL_FIXED_TPR_FPR_NOT_QWEN36_PREDICTION')


def incremental(base,combined):
    dt=combined['tp']-base['tp'];df=combined['fp']-base['fp']
    assert dt>=0 and df>=0, 'Incremental diagnostic requires nested positive selections'
    f1=2*base['tp']/(2*base['tp']+base['fp']+base['fn'])
    precision=dt/(dt+df) if dt+df else None
    return dict(added_tp=dt,added_fp=df,incremental_precision=precision,
                required_incremental_precision_for_f1_gain=f1/2,
                nested_selection_assumption=True,observed_f1_gain=combined['f1']>base['f1'])


def main():
    # Long production transcripts exceed the stdlib CSV default (128 KiB).
    csv.field_size_limit(2**31-1)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--revision',default='4dda1dd4b901d7d26246117f1695002d1d893b5e')
    p.add_argument('--artifact-root',type=Path)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    revision=git('rev-parse',a.revision).decode().strip()
    goldrev=git('rev-parse','403d811e').decode().strip()
    evidence=[]
    def blob(path,rev=revision):
        raw=git('show',rev+':'+path)
        evidence.append(dict(path=path,revision=rev,bytes=len(raw),sha256=sha(raw)))
        return raw
    manifest=json.loads(blob('outputs/guardian_complementarity/inputs/MANIFEST.json'))
    primary=json.loads(blob('outputs/guardian_complementarity/combine_primary.json'))
    secondary=json.loads(blob('outputs/guardian_complementarity/combine_secondary.json'))
    platform=json.loads(blob('docs/judge_20261013/JUDGE_PLATFORM_RESULTS_20261018.json'))
    latest=platform['runs'][-1]['metrics'];target_f1=.62
    assert 0<latest['precision']<=1 and 0<latest['recall']<=1
    target_precision=target_f1*latest['recall']/(2*latest['recall']-target_f1)
    platform_frontier=dict(source='owner-reported aggregates; no row-level execution receipt',
        profile=platform['runs'][-1]['profile'],reported=latest,target_f1=target_f1,
        required_precision_holding_recall_fixed=target_precision,
        max_f1_holding_precision_fixed=2*latest['precision']/(1+latest['precision']),
        warning='Algebraic sensitivity; a threshold change need not preserve precision or recall')
    inventories=[];exact=defaultdict(list);prompts=defaultdict(list)
    for name,record in manifest.items():
        path='outputs/guardian_complementarity/inputs/'+name+'.csv';raw=blob(path)
        rs=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline='')))
        assert sha(raw)==record['sha256'] and len(rs)==record['rows'],('MANIFEST_MISMATCH',name)
        gold=json.loads(blob(GOLDS[name],goldrev)) if name in GOLDS else None
        labels=[int(gold[r['id']]['label']) for r in rs if gold and r['id'] in gold]
        tasks={r['id'].split('::')[0] for r in rs}
        for r in rs:
            exact[sha(json.dumps([r['prompt'],r['response']],ensure_ascii=False).encode())].append((name,r['id']))
            prompts[sha(r['prompt'].encode())].append((name,r['id']))
        inventories.append(dict(dataset=name,rows=len(rs),sha256=sha(raw),input_columns=list(rs[0]),
            unique_ids=len({r['id'] for r in rs}),task_id_prefix_proxy_groups=len(tasks),
            labelled=len(labels) if gold else None,positive=sum(labels) if gold else None,
            negative=len(labels)-sum(labels) if gold else None,
            gold_revision=goldrev if gold else None,gold_path=GOLDS.get(name),
            label_semantic_provenance='saved_current-turn_gold_with_target_metadata; not re-adjudicated' if gold else
            'valid.parquet; labels analysed separately if local saved scores are supplied',
            previous_use='SEEN_RESEARCH; NOT_FRESH_HOLDOUT'))
    def pooled_sets(data, names):
        scores={}
        for model in ('QB2','GR','QB2|GR'):
            counts={k:sum(data['sets'][s]['scores'][model][k] for s in names)
                    for k in ('tp','fp','fn','tn')}
            assert all(isinstance(v,int) and v>=0 for v in counts.values())
            tp,fp,fn=counts['tp'],counts['fp'],counts['fn']
            counts['f1']=2*tp/(2*tp+fp+fn)
            scores[model]=counts
        return dict(pooled=scores,sets={s:data['sets'][s] for s in names})
    # The historical secondary JSON pooled valid46 together with lb2/lb3.
    # Keep that source scope explicit and recompute the report's lb2/lb3 cohort.
    cohorts={}
    for name,data in [('primary',primary),('secondary_source_with_valid46',secondary),
                      ('secondary_lb2_lb3',pooled_sets(secondary,('lb2_long','lb3_long')))]:
        base=data['pooled']['QB2'];combined=data['pooled']['QB2|GR']
        n=sum(base[k] for k in ('tp','fp','fn','tn'));positive=base['tp']+base['fn']
        cohorts[name]=dict(n=n,positive=positive,negative=n-positive,positive_rate=positive/n,
            datasets=list(data['sets']),
            original_scores=data['pooled'],or_incremental=incremental(base,combined),
            all_positive_f1=2*positive/(n+positive),
            prior_shift_sensitivity={model:[prevalence_projection(data['pooled'][model],pi) for pi in (.1,.25,.5,.75)]
                                    for model in ('QB2','GR','QB2|GR')},
            warning='Historical Qwen3.8 Q8 B2 vs Granite; cohorts seen; neither is current Qwen3.6 AWQ',
            per_dataset={s:dict(n=r['n'],positive=r['pos'],or_incremental=incremental(r['scores']['QB2'],r['scores']['QB2|GR']))
                         for s,r in data['sets'].items()})
        assert sum(r['n'] for r in data['sets'].values())==n, ('COHORT_N_MISMATCH',name)
        assert sum(r['pos'] for r in data['sets'].values())==positive, ('COHORT_POS_MISMATCH',name)
    local=None
    if a.artifact_root:
        goldfile=a.artifact_root/'valid46-inputs.json';raw=goldfile.read_bytes();gold=json.loads(raw.decode('utf-8-sig'))
        evidence.append(dict(path=str(goldfile),bytes=len(raw),sha256=sha(raw)))
        assert len(gold)==46 and len({r['id'] for r in gold})==46
        y=[int(r['label']) for r in gold];assert set(y)=={0,1}
        variants={};summary={}
        for filename in FILES:
            path=a.artifact_root/filename;raw=path.read_bytes();data=json.loads(raw)
            evidence.append(dict(path=str(path),bytes=len(raw),sha256=sha(raw)))
            rs=data['records'];assert len(rs)==len(gold)
            assert all(r['index']==i and r['id']==g['id'] for i,(r,g) in enumerate(zip(rs,gold)))
            scores=[float(r['p_yes']) for r in rs];pred=[int(r['pred']) for r in rs]
            assert all(math.isfinite(v) and 0<=v<=1 for v in scores) and set(pred)<={0,1}
            variants[data['variant']]=dict(scores=scores,pred=pred)
            summary[data['variant']]=dict(observed=metrics(y,pred),ranking=rank_metrics(y,scores),
                input_tokens=sum(r['in_tok'] for r in rs),inference_seconds=data['inference_seconds'],
                startup_seconds=data['startup_seconds'],score_calibration_verified=False)
        pairs=[]
        for left,right in itertools.combinations(variants,2):
            x,z=variants[left],variants[right];union=[a or b for a,b in zip(x['pred'],z['pred'])]
            addition=metrics(y,union)
            pairs.append(dict(left=left,right=right,spearman_score_corr=corr(ranks(x['scores']),ranks(z['scores'])),
                binary_error_phi=corr([int(p!=g) for p,g in zip(x['pred'],y)],[int(p!=g) for p,g in zip(z['pred'],y)]),
                disagreement_rows=sum(a!=b for a,b in zip(x['pred'],z['pred'])),
                left_fixed_by_right=sum(a!=g and b==g for a,b,g in zip(x['pred'],z['pred'],y)),
                left_broken_by_right=sum(a==g and b!=g for a,b,g in zip(x['pred'],z['pred'],y)),
                diagnostic_or=addition,or_incremental=incremental(summary[left]['observed'],addition)))
        local=dict(scope='SEEN_VALID46_DIAGNOSTICS_ONLY_NO_THRESHOLD_FIT_OR_PROFILE_SELECTION',rows=46,
            positive=sum(y),negative=len(y)-sum(y),variants=summary,pairs=pairs,
            current_qwen36_scores_present_in_these_five_files=False,
            warning='Granite/JEV saved runs; not current Qwen3.6 architecture proof')
    out=dict(schema='guardian-experiment-dependencies-v1',revision=revision,inference_calls=0,labels_changed=0,
        fitted_thresholds=0,fitted_weights=0,production_changed=False,submission_attempts=0,
        inventory=inventories,exact_duplicate_groups=[v for v in exact.values() if len(v)>1],
        shared_prompt_groups=[v for v in prompts.values() if len(v)>1],
        group_warning='Task id prefix is a diagnostic proxy only; no verified family-separated split or near-duplicate audit',
        historical_complementarity=cohorts,saved_score_diagnostics=local,
        platform_metric_frontier=platform_frontier,evidence=evidence,
        verdict='EXPLORATORY_NOT_INDEPENDENT_GAIN_OR_PLATFORM_EXECUTION_PROOF')
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(a.out),input_rows=sum(r['rows'] for r in inventories),
        labelled_inputs=sum(r['labelled'] or 0 for r in inventories),exact_duplicate_groups=len(out['exact_duplicate_groups']),
        primary=cohorts['primary']['or_incremental'],saved_variants=len(local['variants']) if local else 0),indent=2))


if __name__=='__main__':main()
