"""Post-hoc comparable-subset reporting, separate from frozen predictions."""
from collections import defaultdict
from .fenced_replay import ROOT
from experiments.hybrid_mechanisms.transport import read,save
from experiments.hybrid_mechanisms.runner import HERE,DEFAULT


def metric(pairs):
    tp=fp=fn=tn=0
    for gold,decision in pairs:
        if decision not in ('ERROR','NO_ERROR','UNKNOWN'):raise ValueError('TECHNICAL_FAILURE_IS_NOT_A_LABEL')
        p=int(decision=='ERROR')
        if gold and p:tp+=1
        elif p:fp+=1
        elif gold:fn+=1
        else:tn+=1
    denominator=2*tp+fp+fn
    return dict(n=len(pairs),TP=tp,FP=fp,FN=fn,TN=tn,F1=2*tp/denominator if denominator else None,
                UNKNOWN=sum(d=='UNKNOWN' for _,d in pairs),unknown_binary_mapping=0)


def group(row):
    name=row['name'];case=row['case']
    if case in ('multicall','exception'):return 'EXTRA_I4'
    if row['stage']=='B':return 'STAGE_B'
    return name.removeprefix(row['provider']+'_'+case+'_')


def main(out=DEFAULT):
    pp=read(out/'predictions.json');gold=read(HERE/'fixtures/gold.json')
    annotations=read(out/'causal_annotations.json');groups=defaultdict(list)
    for row in pp:
        if row['stage']=='A':continue
        groups[(row['provider'],group(row))].append(row)
    report=[]
    for (provider,arm),rr in groups.items():
        admitted=[(gold[r['case']]['label'],r['result']['decision']) for r in rr if not r['result']['failure'] and r['result']['decision']]
        raw=[(gold[r['case']]['label'],r['result']['raw_decision']) for r in rr if r['result']['raw_decision'] in ('ERROR','NO_ERROR','UNKNOWN')]
        aa=[annotations[r['name']] for r in rr if r['name'] in annotations]
        report.append(dict(provider=provider,arm=arm,cases=[r['case'] for r in rr],planned=len(rr),
            strict_admitted_metric=metric(admitted),full_subset_strict_F1=metric(admitted)['F1'] if len(admitted)==len(rr) else None,
            raw_label_diagnostic=metric(raw),raw_diagnostic_complete=len(raw)==len(rr),
            failed_names=[r['name'] for r in rr if r['result']['failure']],
            cause_correct=sum(a['cause_correct'] is True for a in aa),causal_audited=len(aa),
            all_component_correct=sum(all(a.get(k) is True for k in ('cause_correct','norm_scope_correct','source_grounding_correct','exception_correct','decision_reason_consistent')) for a in aa),
            known_tokens=sum(r['result'].get('known_tokens',0) or 0 for r in rr),seconds=sum(r['result'].get('seconds',0) or 0 for r in rr)))
    fmt=read(out/'format_diagnostic.json');alternate=[]
    for interface in ('I1','I2','I3','I4'):
        rr=[r for r in fmt['rows'] if r['provider']=='ollama' and r['interface']==interface]
        pairs=[(gold[r['case']]['label'],r['alternate_format_admission']['decision']) for r in rr if r['alternate_format_admission'].get('fully_admitted')]
        alternate.append(dict(provider='ollama',interface=interface,contract='POSTHOC_SINGLE_COMPLETE_JSON_FENCE',
                              planned=len(rr),admitted=len(pairs),metric=metric(pairs),distinct_from_frozen=True))
    ledger=read(out/'ledger.json');usage=dict(attempts=len(ledger),known_tokens=sum(r['known_tokens'] for r in ledger.values()),
                                            charged_tokens=sum(r['charged_tokens'] for r in ledger.values()),seconds=sum(read(out/'raw'/(k+'.json')).get('seconds',0) for k in ledger))
    save(out/'controlled_scores.json',dict(inference_http=0,strict_groups=report,format_diagnostic_groups=alternate,
        usage=usage,semantic_failure_rule='Null technical decisions remain unscored; full-subset F1 is null if any technical failure. Conditional admitted F1 always displays its denominator. UNKNOWN=0 only for admitted semantic UNKNOWN.',
        earlier_scores_note='Frozen score.py groups all I4 cases together and uses zero for empty conditional F1. Do not compare that four-case I4 aggregate with two-case factorial cells. This report separates EXTRA_I4 and marks undefined/partly unmeasured metrics null. Frozen code and predictions remain unchanged.'))
    return report


if __name__=='__main__':main()
