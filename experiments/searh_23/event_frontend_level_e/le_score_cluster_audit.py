"""Evaluation-only cluster audit with standard CEAF-E phi4 similarity.

The legacy scorer uses intersection size (CEAF-M) under a CEAF-E label and
averages precision/recall including empty-positive cases as 1. Preserve its
files, but report genuine CEAF-E and micro merge counts separately. Cluster
scores use retained mentions; dropped real mentions and missed merge pairs
over the full initial inventory are explicit independent counters.
"""
from __future__ import annotations

import json
from collections import Counter
from itertools import combinations
from pathlib import Path

HERE=Path(__file__).parent


def f1(p,r):
    return 2*p*r/(p+r) if p+r else 0.0


def optimum(weights):
    if not weights or not weights[0]: return 0.0
    # Match the smaller side to the larger side. Small E3 policies permit
    # exact dynamic programming without installing a solver on Windows.
    if len(weights)>len(weights[0]): weights=[list(x) for x in zip(*weights)]
    state={0:0.0}
    for row in weights:
        nxt={}
        for used,total in state.items():
            for j,w in enumerate(row):
                if not used&(1<<j):
                    key=used|(1<<j)
                    nxt[key]=max(nxt.get(key,-1.0),total+w)
        state=nxt
    return max(state.values(),default=0.0)


def coref(gold,pred):
    if not gold or not pred: return {"muc_f":0.0,"b3_f":0.0,"ceaf_e_f":0.0,"conll_f":0.0}
    def muc_side(left,right):
        numerator=denominator=0
        for a in left:
            if len(a)<2: continue
            numerator+=len(a)-sum(bool(a&b) for b in right)
            denominator+=len(a)-1
        return numerator/denominator if denominator else 0.0
    mp,mr=muc_side(pred,gold),muc_side(gold,pred)
    universe=set().union(*gold)
    assert universe==set().union(*pred)
    bp=br=0.0
    for mid in universe:
        g=next(x for x in gold if mid in x); p=next(x for x in pred if mid in x)
        bp+=len(g&p)/len(p); br+=len(g&p)/len(g)
    bp/=len(universe); br/=len(universe)
    weights=[[2*len(g&p)/(len(g)+len(p)) for p in pred] for g in gold]
    similarity=optimum(weights)
    cp,cr=similarity/len(pred),similarity/len(gold)
    vals={"muc_f":f1(mp,mr),"b3_f":f1(bp,br),"ceaf_e_f":f1(cp,cr)}
    vals["conll_f"]=sum(vals.values())/3
    return vals


def score_case(data,labels):
    mids={m for n in data["nodes"] for m in n["members"]}
    pred=[set(n["members"]) for n in data["nodes"] if n["members"]]
    assert sum(map(len,pred))==len(mids)
    gold_by={}
    for mid in mids:
        lab=labels[mid] if labels[mid]!="NON_EVENT" else f"junk_{mid}"
        gold_by.setdefault(lab,set()).add(mid)
    metrics=coref(list(gold_by.values()),pred)
    merged={tuple(sorted(pair)) for node in pred for pair in combinations(node,2)}
    expected={tuple(sorted((a,b))) for a,b in combinations(labels,2)
              if labels[a]==labels[b] and labels[a]!="NON_EVENT"}
    c=Counter({"tp":len(merged&expected),"fp":len(merged-expected),"fn_full_inventory":len(expected-merged),
               "real_mentions_dropped":sum(lab!="NON_EVENT" and mid not in mids for mid,lab in labels.items()),
               "junk_mentions_retained":sum(labels[mid]=="NON_EVENT" for mid in mids),
               "retained_mentions":len(mids)})
    return {"counts":dict(c),"coref_retained":metrics}


def run():
    result={}
    case_ids={c["case_id"] for c in json.loads((HERE/"frozen/frozen_cases.json").read_text(encoding="utf-8"))}
    for rootname in ("outputs","outputs_fixed","outputs_rescue"):
        root=HERE/rootname; arms={}
        for folder in sorted(root.glob("TRACKB_*")):
            total=Counter(); rows={}
            for path in folder.glob("*.json"):
                if path.stem not in case_ids: continue
                a=json.loads((root/"ALIGNMENT"/path.name).read_text(encoding="utf-8"))["alignments"]
                labels={f"P{r['i']:02d}":r["label"] for r in a}
                row=score_case(json.loads(path.read_text(encoding="utf-8")),labels)
                rows[path.stem]=row; total.update(row["counts"])
            if not rows: continue
            tp,fp,fn=total["tp"],total["fp"],total["fn_full_inventory"]
            arms[folder.name]={"n_cases":len(rows),"counts":dict(total),
                "micro_merge_precision":tp/(tp+fp) if tp+fp else None,
                "micro_merge_recall_full":tp/(tp+fn) if tp+fn else None,
                "coref_retained_macro":{k:sum(r["coref_retained"][k] for r in rows.values())/len(rows)
                                         for k in ("muc_f","b3_f","ceaf_e_f","conll_f")},"cases":rows}
            print(rootname,folder.name,"TP/FP/FN",tp,fp,fn,"real_dropped",total["real_mentions_dropped"])
        result[rootname]=arms
    (HERE/"cluster_metric_audit.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")


if __name__=="__main__":
    run()
