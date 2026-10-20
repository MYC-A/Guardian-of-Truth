"""Recompute full-profile metrics, domain effects and grouped uncertainty offbox."""
import argparse
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v8_replay_report import member,sha
from scripts.v5_valid46_pipeline import metrics
from scripts.v7_evaluate import keep_accusation
from guardian_truth.judge.decision import decide
from scripts import judge_submission as primary


def quota_bootstrap(rows,gold,hard,ranked,keep):
    from collections import defaultdict
    import numpy as np
    groups=defaultdict(list)
    for i,r in enumerate(rows):groups[r.get('group') or r['original_id']].append(i)
    keys=list(groups);rng=np.random.default_rng(20261020);draws={k:[] for k in ('base','new','new_vs_base')}
    for _ in range(1000):
        indices=[i for key in rng.choice(len(keys),len(keys),replace=True) for i in groups[keys[key]]]
        subset=[rows[i] for i in indices];h={j for j,i in enumerate(indices) if i in hard}
        baseline=decide(len(indices),h,{j:ranked[i] for j,i in enumerate(indices)},.4)
        original=metrics(subset,gold,baseline);values={}
        for arm in ('base','new'):
            filtered=[int(bool(y) and (j in h or keep[arm][i])) for j,(i,y) in enumerate(zip(indices,baseline))]
            values[arm]=metrics(subset,gold,filtered)
            draws[arm].append(tuple(values[arm][k]-original[k] for k in ('f1','fp','tp')))
        draws['new_vs_base'].append(tuple(values['new'][k]-values['base'][k] for k in ('f1','fp','tp')))
    return dict(groups=len(keys),resamples=1000,seed=20261020,common_draws=True,
        quota_and_ranking_recomputed_per_draw=True,model_outputs_frozen=True,independent_validation=False,
        difference_95pct={arm:{k:list(map(float,np.quantile([d[j] for d in draws[arm]],[.025,.975])))
            for j,k in enumerate(('f1','fp','tp'))} for arm in draws})


def run(a):
    done=member(a.run,'evaluation-v10/DONE.json')
    if not done['complete']:raise ValueError('INCOMPLETE_FULL_PROFILE')
    existing=member(a.run,'evaluation-v10/RESULTS.json')
    decisions=member(a.run,'evaluation-v10/work/decisions.jsonl',True)
    pred=member_csv(a.run,'evaluation-v10/predictions.csv')
    metadata=member(a.data,'prepared-v1/EVAL_INDEX.json')['rows']
    metadata={r['original_id']:r for r in metadata if 'dev520' in r['cohorts']}
    if len(decisions)!=520 or len(pred)!=520 or len(metadata)!=520:raise ValueError('ROW_COVERAGE')
    if [r['id'] for r in pred]!=[r['id'] for r in decisions]:raise ValueError('DECISION_ORDER')
    rows=[metadata[r['id']] for r in decisions];gold={r['id']:r['label'] for r in rows}
    hard={i for i,d in enumerate(decisions) if d['hard']}
    # Reuse only parsers, not the onbox aggregation. Raw scores are reread offbox.
    with tempfile.TemporaryDirectory(prefix='guardian-v10-audit-') as temp:
        path=Path(temp)/'scores.jsonl'
        import tarfile
        with tarfile.open(a.run) as t:path.write_bytes(t.extractfile('evaluation-v10/work/scores.jsonl').read())
        overall,missing,inexact,events=primary.read_scores(path,exact_only=True)
        final=primary.read_review_scores(path,isolate_duplicates=True)
    if missing or inexact or len(overall)!=520 or len(final)!=520 or 'done' not in events:
        raise ValueError('EXACT_SCORE_COVERAGE')
    before=decide(520,hard,{i:max(overall[i],final[i]) for i in range(520)},.4)
    if before!=[int(r['label']) for r in pred]:raise ValueError('MAX_DECISION_REPLAY')
    original=decide(520,hard,overall,.4)
    result=dict(complete=True,status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',
        input_archives_sha256={key:sha(getattr(a,key)) for key in ('run','verifier','data')},
        rows=520,quota=.4,threshold=0,quota_refill=False,chunk=64,production_batch_unchanged=False,
        exact_overall=520,exact_final=520,hard=len(hard),
        current_overall_only=metrics(rows,gold,original),full_max=metrics(rows,gold,before),
        changed_by_full_max=sum(x!=y for x,y in zip(original,before)),
        pipeline_elapsed_seconds=done['seconds'],cold_start=False,compiler_cache_reused=True,
        private_improvement_measured=False,production_promoted=False,independent_validation=False,
        arms={},domains={})
    if result['full_max']!=existing['baseline']:raise ValueError('ONBOX_BASELINE_METRIC_DISAGREEMENT')
    filtered={};keep={}
    for arm in ('base','new'):
        values={r['id']:r for r in member(a.verifier,f'evaluation-v8/{arm}/scores.jsonl',True)}
        keep[arm]=[keep_accusation(values[r['id']]) for r in rows]
        labels=[int(bool(y) and (i in hard or keep_accusation(values[r['id']])) ) for i,(r,y) in enumerate(zip(rows,before))]
        filtered[arm]=labels
        item=dict(metrics=metrics(rows,gold,labels),
            removed_fp=sum(x and not y and gold[r['id']]==0 for r,x,y in zip(rows,before,labels)),
            lost_tp=sum(x and not y and gold[r['id']]==1 for r,x,y in zip(rows,before,labels)))
        if item['metrics']!=existing['arms'][arm]['metrics']:raise ValueError('ONBOX_FILTER_METRIC_DISAGREEMENT')
        result['arms'][arm]=item
    result['grouped_bootstrap']=quota_bootstrap(rows,gold,hard,{i:max(overall[i],final[i]) for i in range(520)},keep)
    for domain in sorted({r['domain'] for r in rows}):
        positions=[i for i,r in enumerate(rows) if r['domain']==domain];subset=[rows[i] for i in positions]
        item=dict(rows=len(subset),before=metrics(subset,gold,[before[i] for i in positions]),arms={})
        for arm,labels in filtered.items():
            item['arms'][arm]=dict(metrics=metrics(subset,gold,[labels[i] for i in positions]),
                removed_fp=sum(before[i] and not labels[i] and gold[rows[i]['id']]==0 for i in positions),
                lost_tp=sum(before[i] and not labels[i] and gold[rows[i]['id']]==1 for i in positions))
        result['domains'][domain]=item
    a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(complete=True,out=str(a.out),sha256=sha(a.out))))


def member_csv(archive,name):
    import tarfile
    with tarfile.open(archive) as t:text=t.extractfile(name).read().decode('utf-8')
    return list(csv.DictReader(io.StringIO(text)))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('run','verifier','data','out'):p.add_argument('--'+key,type=Path,required=True)
    run(p.parse_args())
