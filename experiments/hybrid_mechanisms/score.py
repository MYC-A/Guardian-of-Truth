"""Post-inference scorer. Unmeasured/technical failures are not semantic UNKNOWN."""
from collections import defaultdict
from .runner import DEFAULT,HERE
from .transport import read,save


def confusion(items,gold):
    tp=fp=fn=tn=0
    for r in items:
        y=gold[r['case']]['label'];p=int(r['result']['decision']=='ERROR')
        if y and p:tp+=1
        elif p:fp+=1
        elif y:fn+=1
        else:tn+=1
    return dict(TP=tp,FP=fp,FN=fn,TN=tn,F1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,
                n=len(items),UNKNOWN=sum(r['result']['decision']=='UNKNOWN' for r in items))


def score(out=DEFAULT):
    pred=read(out/'predictions.json');gold=read(HERE/'fixtures/gold.json')
    annotations=read(out/'causal_annotations.json') if (out/'causal_annotations.json').exists() else {}
    groups=defaultdict(list)
    for r in pred:
        if r['stage']=='A':continue
        # Factorial groups compare same two original cases; separate aug arms
        # never aggregate different subsets under a shared inflated F1.
        key=(r['provider'],r['name'].removeprefix(r['provider']+'_').replace(r['case']+'_','',1))
        groups[key].append(r)
    report=[]
    for (provider,arm),rr in groups.items():
        admitted=[r for r in rr if r['result']['decision'] in ('ERROR','NO_ERROR','UNKNOWN') and not r['result']['failure']]
        ann=[annotations[r['name']] for r in rr if r['name'] in annotations]
        report.append(dict(provider=provider,arm=arm,cases=[r['case'] for r in rr],planned_records=len(rr),
                           admitted=len(admitted),technical_or_budget_failures=[dict(name=r['name'],failure=r['result']['failure']) for r in rr if r not in admitted],
                           conditional_admitted_metric=confusion(admitted,gold),
                           binary_correct_with_failure_as_non_detection=sum(r['result']['decision'] is not None and int(r['result']['decision']=='ERROR')==gold[r['case']]['label'] for r in rr),
                           known_tokens=sum(r['result'].get('known_tokens',0) or 0 for r in rr),
                           seconds=sum(r['result'].get('seconds',0) or 0 for r in rr),
                           causal_audit_count=len(ann),cause_correct=sum(a.get('cause_correct') is True for a in ann),
                           decision_reason_consistent=sum(a.get('decision_reason_consistent') is True for a in ann),
                           unknown_mapping=0,dataset='KNOWN_VALID46_SELECTED_DEVELOPMENT_ONLY'))
    save(out/'scores.json',report)
    return report


if __name__=='__main__':
    import argparse,json
    p=argparse.ArgumentParser();p.add_argument('--out',type=__import__('pathlib').Path,default=DEFAULT);a=p.parse_args()
    print(json.dumps(score(a.out),indent=2))
