"""Frozen v2 analysis; gold is read locally, only after checkpoint freeze."""
import argparse,csv,hashlib,json,math
from pathlib import Path
from audit_lora_results_cpu_20261018 import read,table,quota
from analyze_lora_standalone_audit_20261018 import metrics
from sklearn.metrics import roc_auc_score,average_precision_score
from scipy.stats import rankdata


def assess(y,s,hard=()):
    positive=sorted([v for t,v in zip(y,s) if t],reverse=True)
    matched={}
    for recall in (.5,.615,.8,.9):
        threshold=positive[max(0,math.ceil(recall*len(positive))-1)]
        m=metrics(y,[int(v>=threshold) for v in s]);m.update(threshold=threshold,fpr=m['fp']/(m['fp']+m['tn']))
        matched[str(recall)]=m
    return dict(ranking=dict(roc_auc=float(roc_auc_score(y,s)),average_precision=float(average_precision_score(y,s))),
                quotas={str(q):metrics(y,quota(s,q,hard)) for q in (.3,.4,.5,.6)},
                zero=metrics(y,[int(v>0 or i in hard) for i,v in enumerate(s)]),
                matched_recall_diagnostic=matched)


def flips(y,base,new):
    return dict(tp_gained=sum(t and not b and n for t,b,n in zip(y,base,new)),
                tp_lost=sum(t and b and not n for t,b,n in zip(y,base,new)),
                fp_removed=sum(not t and b and not n for t,b,n in zip(y,base,new)),
                fp_added=sum(not t and not b and n for t,b,n in zip(y,base,new)))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    p.add_argument('--old',type=Path,required=True);p.add_argument('--protected',type=Path,required=True)
    p.add_argument('--saved',type=Path,required=True);a=p.parse_args();csv.field_size_limit(2**31-1)
    run=a.study/'run';done=json.loads((run/'DONE.json').read_bytes());trained=json.loads((run/'TRAINED.json').read_bytes())
    assert done['complete'] and done['training_steps']==42 and done['adapter_sha256']==trained['adapter_sha256']
    records=read(run/'scores.jsonl');by={(r['partition'],r['arm'],r['id']):r for r in records}
    assert len(records)==len(by)==815 and all(r['exact'] and math.isfinite(r['score']) for r in records)
    out=dict(schema='tooltruth-v2-analysis',scope='CONSTRUCTED_DIAGNOSTIC_PLUS_SEEN_GUARDIAN_NOT_HIDDEN_TEST',datasets={})
    old_pilot={(r['partition'],r['arm'],r['id']):r for r in read(a.old/'run/scores.jsonl')}
    base_deltas=[]
    for (partition,arm,identity),r in by.items():
        if partition=='natural_validation' and arm=='base':
            prior=old_pilot[partition,arm,identity]
            assert r['input_sha256']==prior['input_sha256']
            base_deltas.append(abs(r['score']-prior['score']))
    assert len(base_deltas)==41
    out['unchanged_base_audit']=dict(rows=41,exact_equal=sum(d==0 for d in base_deltas),max_abs_difference=max(base_deltas))
    primary=read(a.study/'primary-scores.jsonl');ps={r['key']:r for r in primary if 'key' in r and 'score' in r}
    assert len(ps)==588 and all(r['exact'] and not r['trimmed'] for r in ps.values())
    for name in ('natural_validation','tooltruth_validation'):
        gold=read(a.study/(name+'_gold.jsonl'));y=[r['label'] for r in gold];arms={}
        for arm in ('base','adapter'):
            s=[by[name,arm,r['id']]['score'] for r in gold];arms[arm]=assess(y,s)
        if name=='tooltruth_validation':
            arms['qwen35b_unhinted']=assess(y,[ps[420+i]['score'] for i in range(len(gold))])
        out['datasets'][name]=dict(rows=len(y),positives=sum(y),all_yes=metrics(y,[1]*len(y)),arms=arms)
    inputs=table(a.protected/'regression_seen/inputs.csv');gold=read(a.protected/'regression_seen/labels.jsonl')
    saved=table(a.saved/'regression_r1/rows.csv');old=read(a.old/'transfer/scores.jsonl')
    ob={(r['arm'],r['id']):r for r in old if r['dataset']=='regression_seen'}
    assert [r['id'] for r in inputs]==[r['id'] for r in gold]==[r['id'] for r in saved]
    assert all(int(s['label'])==g['label'] for s,g in zip(saved,gold))
    new=[]
    for row in inputs:
        r=by['regression_seen','adapter',row['id']]
        assert r['row_sha256']==hashlib.sha256((row['prompt']+'\0'+row['response']).encode('utf8','surrogatepass')).hexdigest()
        assert r['input_sha256']==ob['base',row['id']]['input_sha256']==ob['adapter',row['id']]['input_sha256']
        new.append(r['score'])
    validrows=table(a.saved/'valid46_r1/rows.csv');validids={r['id'] for r in validrows}
    pools={'seen397':list(range(397)),
           'real191':[i for i,r in enumerate(gold) if r['domain'] in {'ext_tau2','hold_tau2h','hold_holdout2'}],
           'valid46':[i for i,r in enumerate(inputs) if r['id'] in validids]}
    assert [inputs[i]['id'] for i in pools['valid46']]==[r['id'] for r in validrows]
    details=[]
    for name,ix in pools.items():
        y=[gold[i]['label'] for i in ix];hard={j for j,i in enumerate(ix) if saved[i]['hard']}
        ss={'qwen4b_base':[ob['base',inputs[i]['id']]['score'] for i in ix],
            'qwen4b_v1':[ob['adapter',inputs[i]['id']]['score'] for i in ix],
            'qwen4b_v2':[new[i] for i in ix],
            'qwen35b_overall':[float(saved[i]['primary_score']) for i in ix],
            'qwen35b_final':[float(saved[i]['final_score']) for i in ix],
            'qwen35b_current_max':[float(saved[i]['score']) for i in ix]}
        assert all(v==max(float(saved[i]['primary_score']),float(saved[i]['final_score'])) for v,i in zip(ss['qwen35b_current_max'],ix))
        ss['fixed_rank_ensemble_v2']=[float(v) for v in (rankdata(ss['qwen35b_overall'])+rankdata(ss['qwen4b_v2']))/(2*len(ix))]
        ss['fixed_rank_current_max_v2']=[float(v) for v in (rankdata(ss['qwen35b_current_max'])+rankdata(ss['qwen4b_v2']))/(2*len(ix))]
        arms={k:assess(y,v,hard) for k,v in ss.items()}
        arms['fixed_rank_ensemble_v2'].pop('zero')
        arms['fixed_rank_current_max_v2'].pop('zero')
        out['datasets'][name]=dict(rows=len(ix),positives=sum(y),hard=len(hard),all_yes=metrics(y,[1]*len(y)),arms=arms,
            changes_at40={k:flips(y,quota(ss['qwen35b_overall'],.4,hard),quota(ss[k],.4,hard))
                          for k in ('qwen4b_v2','fixed_rank_ensemble_v2')})
        out['datasets'][name]['changes_vs_current_max_at40']={k:flips(y,quota(ss['qwen35b_current_max'],.4,hard),quota(ss[k],.4,hard))
                           for k in ('qwen4b_v2','fixed_rank_current_max_v2')}
        if name=='valid46':
            pb=quota(ss['qwen4b_base'],.4,hard);pn=quota(ss['qwen4b_v2'],.4,hard)
            details=[dict(id=inputs[i]['id'],label=y[j],base=ss['qwen4b_base'][j],v2=ss['qwen4b_v2'][j],before=pb[j],after=pn[j]) for j,i in enumerate(ix) if pb[j]!=pn[j]]
    r=out['datasets']['real191']['arms']['qwen4b_v2'];v=out['datasets']['valid46']['arms']['qwen4b_v2']
    conditions=dict(complete_coverage=True,real_auc_above_v1=r['ranking']['roc_auc']>.830780,
                    valid_auc_drop_at_most_02=v['ranking']['roc_auc']>=.937618-.02,
                    valid_f1_at40_at_least_0809268=v['quotas']['0.4']['f1']>=.809268)
    out.update(gate=dict(conditions=conditions,passes=all(conditions.values()),production_accepted=False),valid_changes=details,
               training_seconds=done['training_seconds'],wall_seconds=done['wall_seconds'],adapter_sha256=done['adapter_sha256'],
               limitations=['Real and valid sets are previously viewed, not a fresh target holdout',
                            '35B saved reference context/hints differ from4B',
                            'Matched-recall thresholds use gold diagnostically and are not deployable thresholds',
                            'No platform result or contest runtime measurement'])
    (a.study/'ANALYSIS.json').write_bytes((json.dumps(out,indent=2)+'\n').encode())
    print(json.dumps({name:{arm:dict(f1_at40=v['quotas']['0.4']['f1'],auc=v['ranking']['roc_auc']) for arm,v in d['arms'].items()} for name,d in out['datasets'].items()},indent=2))
    print(json.dumps(out['gate']))


if __name__=='__main__':main()
