"""Descriptive quota sensitivity on frozen scores; no fitting or GPU calls."""
import argparse,csv,json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge.decision import decide
from scripts.analyze_judge_dependencies_20261018 import metrics

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--saved',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    result=dict(status='SEEN_DESCRIPTIVE_NOT_THRESHOLD_SELECTION',gpu_calls=0,private_test_prediction=False,datasets={})
    for name in ('dev_r1b','regression_r1','valid46_r1'):
        source=a.saved/name/'rows.csv'
        with source.open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
        y=[int(r['label']) for r in rows];hard={i for i,r in enumerate(rows) if r['hard']}
        methods={}
        for method in ('overall','final','max'):
            scores={i:float(r['primary_score']) if method=='overall' else float(r['final_score']) if method=='final' else max(float(r['primary_score']),float(r['final_score'])) for i,r in enumerate(rows)}
            methods[method]={str(round(k/100,2)):metrics(y,decide(len(rows),hard,scores,k/100)) for k in range(20,81,5)}
        result['datasets'][name]=dict(rows=len(y),positive=sum(y),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),methods=methods)
    a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({n:{m:{q:{k:r[k] for k in ('f1','precision','recall')} for q,r in v.items() if q in ('0.3','0.4','0.5','0.6')} for m,v in d['methods'].items()} for n,d in result['datasets'].items()},indent=2))
if __name__=='__main__':main()
