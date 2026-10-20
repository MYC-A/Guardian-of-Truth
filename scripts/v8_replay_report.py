"""Independently audit offbox V7/V8 replay archives without publishing transcripts."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import tarfile


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def member(archive,name,lines=False):
    with tarfile.open(archive,'r:gz') as t:
        raw=t.extractfile(name).read()
    return [json.loads(x) for x in raw.splitlines() if x] if lines else json.loads(raw)


def transitions(rows,gold,left,right):
    counts=Counter()
    for r in rows:
        i=r['id'];a=left[i];b=right[i]
        old=not a['admitted'] or a['score']>0
        new=not b['admitted'] or b['score']>0
        if old==new:continue
        mechanism='newly_admitted' if not a['admitted'] else 'same_input_rescoring'
        outcome=('lost_tp' if gold[i] else 'removed_fp') if old else ('gained_tp' if gold[i] else 'added_fp')
        counts[mechanism+'::'+outcome]+=1
    return dict(counts)


def common_admitted(rows,gold,arms):
    selected=[r for r in rows if not r['hard'] and all(arms[a][r['id']]['admitted'] for a in arms)]
    result=dict(rows=len(selected),diagnostic_only=True,
        caveat='Selected on both models admission; not an independent or representative quality estimate',arms={})
    for arm,values in arms.items():
        tp=fp=fn=tn=0
        for row in selected:
            positive=values[row['id']]['score']>0;label=gold[row['id']]
            tp+=int(positive and label==1);fp+=int(positive and label==0)
            fn+=int(not positive and label==1);tn+=int(not positive and label==0)
        result['arms'][arm]=dict(tp=tp,fp=fp,fn=fn,tn=tn)
    return result


def run(a):
    protocol=member(a.data,'prepared-v1/REPLAY_PROTOCOL.json')
    index=member(a.data,'prepared-v1/EVAL_INDEX.json')['rows']
    selection=set(member(a.data,'prepared-v1/EVAL_PROTOCOL.json')['ids'])
    rows=[r for r in index if r['id'] in selection];gold={r['id']:r['label'] for r in rows}
    result=dict(scope='offbox technical replay audit; source support is not semantic proof',
        input_archives_sha256={k:sha(getattr(a,k)) for k in ('v7','v8','data')},arms={},
        human_reviewed=False,independent_validation=False,private_improvement_measured=False,
        production_promoted=False)
    if len(rows)!=757 or len(gold)!=757:raise ValueError('GOLD_ID_COVERAGE')
    current={}
    for arm in ('base','new'):
        oldlist=member(a.v7,f'evaluation-v3/{arm}/scores.jsonl',True)
        newlist=member(a.v8,f'evaluation-v8/{arm}/scores.jsonl',True)
        old={r['id']:r for r in oldlist};new={r['id']:r for r in newlist}
        current[arm]=new
        if len(oldlist)!=757 or len(newlist)!=757 or set(old)!=selection or set(new)!=selection:
            raise ValueError('ARM_ID_COVERAGE')
        for i,r in new.items():
            prior=old[i]
            if r['review']!=prior['review'] or r['input_sha256']!=prior['input_sha256']:
                raise ValueError('SAVED_REVIEW_OR_SOURCE_DRIFT')
            if prior['admitted'] and not r['admitted']:raise ValueError('LOST_SOURCE_SUPPORT')
            if prior['admitted'] and prior['score_input_sha256']!=r['score_input_sha256']:
                raise ValueError('EXISTING_FINAL_TOKEN_DRIFT')
            if r['admitted'] and (not r['exact'] or r['score'] is None):raise ValueError('INEXACT_FINAL')
        repeat=member(a.v8,f'evaluation-v8/{arm}/repeat_scores.jsonl',True)
        if len(repeat)!=92:raise ValueError('REPEAT_COVERAGE')
        deltas=[];flips=0;nonzero=0
        for r in repeat:
            first=new[r['id']]
            if r['review']!=first['review'] or r['admitted']!=first['admitted']:
                raise ValueError('FIXED_REVIEW_CHANGED_IN_REPEAT')
            if r['admitted']:
                if not r['exact'] or r['score_input_sha256']!=first['score_input_sha256']:
                    raise ValueError('REPEAT_FINAL_TOKEN_DRIFT')
                delta=r['score']-first['score'];deltas.append(delta);nonzero+=int(delta!=0)
                flips+=int((r['score']>0)!=(first['score']>0))
        item=dict(rows=757,source_protocol_counts=protocol['counts'][arm],
            new_source_support_kinds=dict(Counter(r['source_support']['kind'] for i,r in new.items() if r['admitted'] and not old[i]['admitted'])),
            old_admitted_token_inputs_verified=True,saved_reviews_verified=True,
            fixed_review_score_stability=dict(comparisons=92,admitted_identical_inputs=len(deltas),
                nonzero_score_differences=nonzero,decision_flips=flips,
                max_abs_score_difference=max(map(abs,deltas),default=None),
                sd_differences_over_sqrt2=statistics.stdev(deltas)/(2**.5) if len(deltas)>1 else None,
                caveat='Differences share a reference; this is not independent per-row noise certification'),
            cohorts={})
        for cohort in ('real191','dev520','valid46'):
            subset=[r for r in rows if cohort in r['cohorts']]
            # Raw verifier transitions are distinct from baseline-pool veto results.
            # Mechanical hard positives cannot be vetoed in the actual decision.
            subset=[r for r in subset if not r['hard']]
            item['cohorts'][cohort]=dict(nonhard_rows=len(subset),
                raw_verifier_transitions=transitions(subset,gold,old,new))
        result['arms'][arm]=item
    result['common_admitted_diagnostic']={c:common_admitted([r for r in rows if c in r['cohorts']],gold,current)
        for c in ('real191','dev520','valid46')}
    result['v8_pair_results']=member(a.v8,'evaluation-v8/PAIR_RESULTS.json')
    a.out.write_text(json.dumps(result,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(complete=True,report=str(a.out),sha256=sha(a.out))))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('v7','v8','data','out'):p.add_argument('--'+key,type=Path,required=True)
    run(p.parse_args())
