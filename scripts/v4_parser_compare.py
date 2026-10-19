"""Compare parser inventories and replay fixed production scores on explored sets."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from guardian_truth.judge.decision import decide


def read(path):return [json.loads(line) for line in path.read_bytes().splitlines()]
def table(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def compare(old,new,saved,probe,out):
    csv.field_size_limit(2**31-1)
    report=dict(cohorts={},decision_replay={},format_probe={},source_files={})
    for name in ('regression_seen','compli_dev','compli_eval','train','dev','holdout'):
        aa=read(old/(name+'.jsonl'));bb=read(new/(name+'.jsonl'))
        assert [r['id'] for r in aa]==[r['id'] for r in bb]
        item=dict(rows=len(aa),old={},new={})
        for version,rows in [('old',aa),('new',bb)]:
            item[version]=dict(catalog_complete=sum(r['catalog_complete'] for r in rows),
                hard_rows=sum(bool(r['hard']) for r in rows),shape_hard_rows=sum(bool(r['shape_hard']) for r in rows),
                hard_on_gold0=sum(r['label']==0 and bool(r['hard']) for r in rows),
                shape_hard_on_gold0=sum(r['label']==0 and bool(r['shape_hard']) for r in rows),
                labels_used=any(r['label'] is not None for r in rows),
                prompt_diagnostic_rows=sum(bool(r['prompt_diagnostics']) for r in rows),
                response_diagnostic_rows=sum(bool(r['response_diagnostics']) for r in rows))
        report['cohorts'][name]=item
        for path in (old/(name+'.jsonl'),new/(name+'.jsonl')):
            report['source_files'][str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    aa=read(old/'regression_seen.jsonl');bb=read(new/'regression_seen.jsonl')
    scores={r['id']:float(r['score']) for r in table(saved/'regression_r1/rows.csv')}
    valid={r['id'] for r in table(saved/'valid46_r1/rows.csv')}
    for name,select in [('seen397',lambda r:True),('real191',lambda r:r.get('domain') in
            {'ext_tau2','hold_tau2h','hold_holdout2'}),('valid46',lambda r:r['id'] in valid)]:
        a=[r for r in aa if select(r)];b=[r for r in bb if select(r)]
        s={i:scores[r['id']] for i,r in enumerate(a)};item=dict(rows=len(a),modes={})
        for mode in ('hard','shape_hard'):
            item['modes'][mode]={}
            for q in (.3,.4,.5):
                hard=lambda rs:{i for i,r in enumerate(rs) if r[mode]}
                x=decide(len(a),hard(a),s,q);y=decide(len(b),hard(b),s,q)
                item['modes'][mode][str(q)]=dict(changed=sum(v!=w for v,w in zip(x,y)),
                    tp_delta=sum((w-v)*r['label'] for v,w,r in zip(x,y,a)),
                    fp_delta=sum((w-v)*(1-r['label']) for v,w,r in zip(x,y,a)))
        report['decision_replay'][name]=item
    if probe:
        report['format_probe']={k:v['counts'] for k,v in json.loads(probe.read_bytes()).items()}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('old','new','saved','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--probe',type=Path);a=p.parse_args();compare(a.old,a.new,a.saved,a.probe,a.out)
