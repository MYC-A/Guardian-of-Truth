"""Paired gold-reading analysis; never imported by the verifier."""
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
    p.add_argument('--saved',type=Path,required=True)
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--controls',type=Path,required=True)
    a=p.parse_args();csv.field_size_limit(2**31-1)
    start=json.loads((a.run/'START.json').read_bytes());done=json.loads((a.run/'DONE.json').read_bytes())
    assert done['complete']
    rec=[json.loads(l) for l in (a.run/'predictions.jsonl').read_text().splitlines()]
    assert len(rec)==done['rows'] and len({(r['run'],r['key']) for r in rec})==len(rec)
    result=dict(runtime=done,admission=dict(Counter(r['reason'] for r in rec)),datasets={})
    for name,ds in [('dev_r1b','compli_dev'),('regression_r1','regression_seen')]:
        with (a.saved/name/'rows.csv').open(encoding='utf-8',newline='') as f: base=list(csv.DictReader(f))
        with (a.data/ds/'inputs.csv').open(encoding='utf-8',newline='') as f: inp=list(csv.DictReader(f))
        g=[json.loads(l) for l in (a.data/ds/'labels.jsonl').read_text().splitlines()]
        assert len(base)==len(inp)==len(g)
        for b,i,gg in zip(base,inp,g):assert b['id']==i['id']==gg['id'] and int(b['label'])==gg['label']
        predictions=[r for r in rec if r['run']==name]
        for r in predictions:
            i=inp[r['key']];assert r['row_sha256']==hashlib.sha256((i['prompt']+'\0'+i['response']).encode()).hexdigest()
        y=[gg['label'] for gg in g];hard={i for i,b in enumerate(base) if b['hard']}
        veto={r['key'] for r in predictions if r['veto']} - hard
        methods={}
        for method in ['overall','final','available_max']:
            scores={i:float(b['primary_score']) if method=='overall' else float(b['final_score']) if method=='final' else max(float(b['primary_score']),float(b['final_score'])) for i,b in enumerate(base)}
            methods[method]={}
            for rate in [.3,.4]:
                before=decide(len(y),hard,scores,rate);after=[int(v and i not in veto) for i,v in enumerate(before)]
                changed=[i for i,(x,z) in enumerate(zip(before,after)) if x!=z]
                methods[method][str(rate)]=dict(before=metrics(y,before),after=metrics(y,after),
                    fp_cleared=sum(not y[i] for i in changed),tp_lost=sum(y[i] for i in changed),
                    final_positive_fraction=sum(after)/len(y),refill=False,
                    changed=[dict(position=i,id=g[i]['id'],label=y[i],group=g[i]['group']) for i in changed])
        result['datasets'][ds]=dict(rows=len(y),model_eligible=len(predictions),model_refutations=len(veto),methods=methods)
    controls=[json.loads(l) for l in (a.controls/'labels.jsonl').read_text().splitlines()]
    with (a.controls/'inputs.csv').open(encoding='utf-8',newline='') as f:ci=list(csv.DictReader(f))
    assert len(ci)==len(controls)
    cr={r['key']:r for r in rec if r['run']=='synthetic_controls'}
    for key,r in cr.items():
        assert r['id']==ci[key]['id']==controls[key]['id']
        assert r['row_sha256']==hashlib.sha256((ci[key]['prompt']+'\0'+ci[key]['response']).encode()).hexdigest()
    cy=[r['label'] for r in controls];cp=[int(not cr.get(i,{}).get('veto',False)) for i in range(len(cy))]
    result['synthetic_controls']=dict(rows=len(cy),model_eligible=len(cr),artificial_all_positive_baseline=True,
        after=metrics(cy,cp),tp_lost=sum(y and not p for y,p in zip(cy,cp)),
        tp_lost_cases=[c['id'] for c,y,p in zip(controls,cy,cp) if y and not p],
        correct_calls_cleared=sum(not y and not p for y,p in zip(cy,cp)),
        by_variant={v:dict(rows=sum(c['variant']==v for c in controls),
            cleared=sum(c['variant']==v and not pred for c,pred in zip(controls,cp))) for v in sorted({c['variant'] for c in controls})})
    dev=result['datasets']['compli_dev']['methods']['final']['0.4']
    result['acceptance']=dict(dev_zero_tp_loss=dev['tp_lost']==0,
        dev_fp_corrections=dev['fp_cleared'],dev_coverage=result['datasets']['compli_dev']['model_eligible'],
        accepted=False,reason='NO_DEV_TOOL_CALL_COVERAGE; zero loss there is vacuous, cannot establish the requested acceptance criterion')
    (a.run/'ANALYSIS.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='runtime'},indent=2))


if __name__=='__main__':main()
