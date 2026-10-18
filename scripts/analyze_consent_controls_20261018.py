"""Compare standard exact judge on the synthetic consent controls; no fitting."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.analyze_judge_dependencies_20261018 import metrics,rank_metrics


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--controls',type=Path,required=True)
    a=p.parse_args();summary=json.loads((a.run/'summary.json').read_bytes())
    assert summary['stage_exit']==0 and summary['scored']==98 and summary['inexact']==0
    assert summary['input_file_sha256']==hashlib.sha256((a.controls/'inputs.csv').read_bytes()).hexdigest()
    assert summary['labels_sidecar_sha256']==hashlib.sha256((a.controls/'labels.jsonl').read_bytes()).hexdigest()
    with (a.run/'rows.csv').open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
    gold=[json.loads(l) for l in (a.controls/'labels.jsonl').read_text().splitlines()]
    assert len(gold)==len(rows)==98
    assert all(g['id']==r['id'] and g['label']==int(r['label']) for g,r in zip(gold,rows))
    y=[int(r['label']) for r in rows];scores=[float(r['primary_score']) for r in rows]
    preds=[int(score>0 or bool(row['hard'])) for score,row in zip(scores,rows)]
    result=dict(rows=98,exact_score_coverage=98,zero_logodds_diagnostic=metrics(y,preds),ranking=rank_metrics(y,scores),
        by_variant={v:dict(metrics=metrics([y[i] for i in range(98) if gold[i]['variant']==v],
                                          [preds[i] for i in range(98) if gold[i]['variant']==v]),
                            scores=[scores[i] for i in range(98) if gold[i]['variant']==v])
                    for v in sorted({g['variant'] for g in gold})},
        errors=[dict(id=r['id'],gold=label,score=score,prediction=q) for r,label,score,q in zip(rows,y,scores,preds) if label!=q],
        scope='SYNTHETIC_DIAGNOSTIC_NOT_PRODUCTION_THRESHOLD_SELECTION',
        runtime=dict(total_seconds=summary['total_wall_seconds'],model_seconds=summary['stage_done']['primary']['wall_seconds']))
    (a.run/'CONTROL_DIAGNOSTIC.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='by_variant'},indent=2))


if __name__=='__main__':main()
