"""Evaluation-only E1/E2 per-item errors and family breakdown; no inference."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

HERE=Path(__file__).parent
OUT=HERE/"outputs"


def run():
    eventgold=json.loads((HERE/"frozen/eventness_gold.json").read_text(encoding="utf-8"))
    identitygold=json.loads((HERE/"frozen/identity_gold.json").read_text(encoding="utf-8"))
    identityinputs={r["id"]:r for r in json.loads((HERE/"frozen/identity_inputs.json").read_text(encoding="utf-8"))}
    e1={}
    for arm in ("A1_ud","A3_amr","A4_llm","A5_hybrid"):
        rows=[]
        for path in sorted((OUT/"E1").glob("*.json")):
            r=json.loads(path.read_text(encoding="utf-8")); gold=eventgold[r["id"]]
            if gold=="AMBIGUOUS" or gold==r[arm]: continue
            rows.append({"id":r["id"],"input":r["input"],"gold":gold,"pred":r[arm]})
        e1[arm]=rows
    e2={}
    for folder in sorted((OUT/"E2").iterdir()):
        if not folder.is_dir(): continue
        errors=[]; by_family={}
        for path in sorted(folder.glob("*.json")):
            r=json.loads(path.read_text(encoding="utf-8")); g=identitygold[r["id"]]; inp=identityinputs[r["id"]]
            count=by_family.setdefault(inp["family"]+" / "+inp["variant"],Counter())
            count["n"]+=1
            count["exact"]+=g==r["label"]
            count["same_tp"]+=g==r["label"]=="SAME_EVENT"
            count["same_fp"]+=g!="SAME_EVENT" and r["label"]=="SAME_EVENT"
            count["same_fn"]+=g=="SAME_EVENT" and r["label"]!="SAME_EVENT"
            if g!=r["label"]:
                errors.append({"id":r["id"],"gold":g,"pred":r["label"],"family":inp["family"],
                               "variant":inp["variant"],"span_a":inp["a"]["span"],
                               "span_b":inp["b"]["span"],"reason":r.get("reason","")})
        e2[folder.name]={"families":{k:dict(v) for k,v in by_family.items()},"errors":errors}
    for name in ("CE_GUARDIAN","CE_BINARY"):
        path=OUT/name/"sealed_test_predictions.json"
        if not path.exists(): continue
        rows=json.loads(path.read_text(encoding="utf-8"))
        e2[name]={"errors":[{**r,"gold":identitygold[r["id"]],
                             "span_a":identityinputs[r["id"]]["a"]["span"],
                             "span_b":identityinputs[r["id"]]["b"]["span"]}
                            for r in rows if r["label"]!=identitygold[r["id"]]]}
    data={"E1_errors":e1,"E2":e2}
    (HERE/"per_item_errors.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print('Saved E1/E2 errors for',len(e1),'and',len(e2),'arms')


if __name__=="__main__": run()
