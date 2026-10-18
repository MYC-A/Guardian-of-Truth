"""Inventory observed FP/FN and rank effects; no semantic labels inferred."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge.decision import decide
from scripts.analyze_judge_dependencies_20261018 import metrics


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    csv.field_size_limit(2**31-1)
    with (a.run/'rows.csv').open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f))
    with (a.data/'inputs.csv').open(encoding='utf-8',newline='') as f: sources=list(csv.DictReader(f))
    gold=[json.loads(l) for l in (a.data/'labels.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rows)==len(sources)==len(gold)
    for i,(r,s,g) in enumerate(zip(rows,sources,gold)):
        assert r['id']==s['id']==g['id'] and int(r['label'])==g['label'] and g['position']==i
        pair=json.dumps([s['prompt'],s['response']],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        assert hashlib.sha256(pair).hexdigest()==g['source_pair_sha256']
    recs=[json.loads(l) for l in (a.run/'scores.jsonl').read_text(encoding='utf-8').splitlines()]
    pre={int(r['key']):r for r in recs if r.get('review')=='prepass'}
    final={int(r['key']):r for r in recs if r.get('review')=='final'}
    y=[g['label'] for g in gold]; hard={i for i,r in enumerate(rows) if r['hard']}
    fs={i:float(r['final_score']) for i,r in enumerate(rows)}
    ps={i:float(r['primary_score']) for i,r in enumerate(rows)}
    fpred=decide(len(y),hard,fs,.4); ppred=decide(len(y),hard,ps,.4)
    inventory=[]
    for i,(r,g) in enumerate(zip(rows,gold)):
        state=('TP' if y[i] else 'FP') if fpred[i] else ('FN' if y[i] else 'TN')
        if state in ('FP','FN') or fpred[i]!=ppred[i]:
            n=pre.get(i,{}); f=final.get(i,{})
            inventory.append(dict(position=i,id=r['id'],gold=y[i],group=g['group'],
                source_pair_sha256=g['source_pair_sha256'],state=state,overall_at_40=ppred[i],
                final_at_40=fpred[i],primary_score=ps[i],final_score=fs[i],hard=i in hard,
                prepass_status=n.get('status'),delivery=f.get('delivery'),
                notes=n.get('notes'),raw_note_sha256=hashlib.sha256(n.get('raw','').encode()).hexdigest(),
                changed=fpred[i]!=ppred[i],semantic_error_category='UNANNOTATED'))
    result=dict(run=a.run.name,rows=len(rows),positive=sum(y),hard=len(hard),
        overall_at_40=metrics(y,ppred),final_at_40=metrics(y,fpred),
        observed_zero_logodds_reference_only=metrics(y,[int(fs[i]>0 or i in hard) for i in range(len(y))]),
        final_false_negatives_with_score_above_zero=sum(y[i] and not fpred[i] and fs[i]>0 for i in range(len(y))),
        cutoff_min_selected_nonhard=min(fs[i] for i in range(len(y)) if fpred[i] and i not in hard),
        transitions=dict(Counter(('corrected_' if fpred[i]==y[i] else 'broken_')+
                                  ('positive' if y[i] else 'negative') for i in range(len(y)) if fpred[i]!=ppred[i])),
        fp_delivery=dict(Counter(final[i].get('delivery') for i in range(len(y)) if not y[i] and fpred[i])),
        fn_delivery=dict(Counter(final[i].get('delivery') for i in range(len(y)) if y[i] and not fpred[i])),
        fitted_thresholds=0,model_calls_added=0,inventory=inventory,
        limitations=['Zero log-odds is descriptive, not calibrated or a chosen production threshold.',
                    'A score below quota cutoff is not proof that the model failed to notice a violation.',
                    'Delivered notes can contain false claims; undelivered notes cannot explain final content.',
                    'Paired score/rank changes do not establish causal effects of notes.'])
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='inventory'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
