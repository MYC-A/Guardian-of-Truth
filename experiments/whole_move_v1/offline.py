"""All46 declaration-only diagnostic and frozen historical OR replay, no API.

Original labels are evaluation data only. UNKNOWN maps to0 explicitly; schema
passes are not whole-move NO_ERROR. Historical baselines stay unchanged.
"""
from collections import defaultdict
import json
from pathlib import Path

from experiments.evidence_packer_v2.llm_eval import rows
from experiments.hybrid_mechanisms.transport import save
from .mechanical import check

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/whole_move_v1'


def metrics(gold,pred):
    tp=sum(gold[i]==1 and pred[i]==1 for i in gold)
    fp=sum(gold[i]==0 and pred[i]==1 for i in gold)
    fn=sum(gold[i]==1 and pred[i]==0 for i in gold)
    tn=sum(gold[i]==0 and pred[i]==0 for i in gold)
    return dict(n=len(gold),tp=tp,fp=fp,fn=fn,tn=tn,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)


def run():
    original=rows()
    records=[dict(id=r['id'],**check({k:r[k] for k in ('prompt','response')})) for r in original]
    # Materialize predictions before labels or old decisions are evaluated.
    save(OUT/'all46_mechanical.json',records)
    flags={r['id']:int(r['mechanically_established_error']) for r in records}
    gold={r['id']:r['label'] for r in original}
    baseline=ROOT/'outputs/evidence_packer_v2/llm/decisions.jsonl'
    groups=defaultdict(list)
    for line in baseline.read_text(encoding='utf-8').splitlines():
        r=json.loads(line);groups[r['run'],r['arm']].append(r)
    comparisons=[]
    for (run,arm),group in sorted(groups.items()):
        if len(group)!=46 or {r['id'] for r in group}!=set(gold):
            raise ValueError('INCOMPLETE_OR_DUPLICATE_HISTORICAL_BASELINE')
        before={r['id']:int(r['admission']=='ADMITTED' and r['decision']=='ERROR') for r in group}
        after={i:before[i]|flags[i] for i in gold}
        comparisons.append(dict(run=run,arm=arm,before=metrics(gold,before),after=metrics(gold,after),
            newly_flagged=[dict(id=i,label=gold[i]) for i in gold if flags[i] and not before[i]]))
    save(OUT/'all46_offline_summary.json',dict(new_http=0,mechanical_only=metrics(gold,flags),
        internal_unknown=sum(not f for f in flags.values()),unknown_binary_mapping=0,
        mechanical_claim='Source-declaration positive constraints only; no whole-move absence proof.',
        flagged_eval_only=[dict(id=i,label=gold[i]) for i in gold if flags[i]],
        frozen_historical_or_replay=comparisons,
        interpretation='Known valid46 development diagnostic. Adding mechanical findings to saved baseline decisions is offline OR replay, not a new comparable LLM architecture or hidden test result.'))
    print(json.dumps(dict(mechanical=metrics(gold,flags),historical_comparisons=len(comparisons),new_http=0)))


if __name__=='__main__':run()
