"""Post-hoc human causal annotations, separate from gold-free inference."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'src'))
from experiments.telecom_causal_recovery.transport import read,save
from experiments.telecom_causal_recovery.runner import INPUT
from experiments.telecom_causal_recovery.packets import variants,extract

CRITERIA=['target_correct','policy_correct','modality_correct','entity_binding_correct',
          'temporal_relation_correct','exception_scope_correct','source_grounding_correct','cause_correct']


def main(out):
    import pandas as pd
    original=read(INPUT)
    gold=pd.read_parquet(ROOT/'valid.parquet',columns=['id','label'])
    selected=gold[gold.id==original['id']]
    assert len(selected)==1
    label=int(selected.iloc[0].label)
    rows=read(out/'predictions.json')
    if (out/'automatic_predictions.json').exists():
        rows+=read(out/'automatic_predictions.json')
    annotations=read(out/'causal_annotations.json')
    assert annotations['stage']=='POST_HOC_CAUSAL_AUDIT' and annotations['human_source_audit'] is True
    copies=variants(original)
    ledger=read(out/'ledger.json');reports=[]
    for row in rows:
        a=annotations['rows'][row['name']]
        assert a['request_sha256']==row['request_sha256']
        variant=row.get('variant','original')
        g,_,norms=extract(copies[variant]['row'])
        allowed=set(g.store.sources)|set(g.store.quotes)|set(g.refs)
        entry=dict(name=row['name'],variant=variant,decision=row['decision'],failure=row['failure'],
            request_sha256=row['request_sha256'],fully_admitted=row['fully_admitted'],
            binary_correct=(int(row['decision']=='ERROR')==label if row['decision'] is not None and variant=='original' and row['name']!='AUTO_plan' else None),
            binary_reason='Official original 0/1 label with UNKNOWN->0; synthetic controls and selection plans have no official binary gold.',
            original_gold=label if variant=='original' else None)
        for criterion in CRITERIA:
            assessment=a['assessments'][criterion]
            assert set(assessment)=={'value','reason','source_ids'}
            assert assessment['value'] is None or type(assessment['value']) is bool
            assert assessment['reason'] and set(assessment['source_ids'])<=allowed
            if row['reply'] is None:assert assessment['value'] is None
            entry[criterion]=assessment['value']
        entry['assessments']=a['assessments']
        entry['audit_note']=a['note']
        entry['decision_reason_consistent']=a['decision_reason_consistent']
        entry['complete_original_cause_recovery']=bool(variant=='original' and row['name']!='AUTO_plan' and row['fully_admitted']
            and entry['binary_correct'] and all(entry[c] is True for c in CRITERIA))
        item=ledger.get(row['request_sha256'])
        entry['cost']=dict(http=int(item is not None),known_tokens=item['known_tokens'] if item else 0,
                           charged_tokens=item['charged_tokens'] if item else 0)
        reports.append(entry)
    report=dict(stage='POST_HOC_CAUSAL_AUDIT',human_semantic_annotations=True,rows=reports,
        budget=dict(http=len(ledger),known_tokens=sum(v['known_tokens'] for v in ledger.values()),
                    charged_tokens=sum(v['charged_tokens'] for v in ledger.values()),unknown_usage=sum(v['unknown_usage'] for v in ledger.values())),
        oracle_source_success=[r['name'] for r in reports if r['name'] in ('A','B','C') and r['complete_original_cause_recovery']],
        automatic_source_and_semantic_success=any(r['name']=='AUTO_final' and r['complete_original_cause_recovery'] for r in reports),
        gold_sha256=hashlib.sha256((ROOT/'valid.parquet').read_bytes()).hexdigest(),
        valid46_F1_measured=False,independent_holdout=False,new_http=0)
    save(out/'causal_score.json',report)
    print(str(out/'causal_score.json'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    main(p.parse_args().out)
