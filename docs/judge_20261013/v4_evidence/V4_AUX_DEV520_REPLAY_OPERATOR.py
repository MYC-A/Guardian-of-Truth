
import csv,json,sys,pathlib,hashlib
root=pathlib.Path('/workspace/guardian-lab-20261018/blend-20261019/code');sys.path[:0]=[str(root),str(root/'src')]
from scripts import judge_submission as p
from guardian_truth.judge.ensemble import blend,read_secondary
from guardian_truth.judge.decision import decide
from guardian_truth.judge.mechanical import analyze
lab=root.parents[1];aux=root.parent/'aux-dev520-budget-v1';csv.field_size_limit(2**31-1)
rows=p.read_input(lab/'data/guardian-judge-eval-data-v1/compli_dev/inputs.csv')
refpath=lab/'runs/dev_r1b/rows.csv'
with refpath.open(newline='') as f:ref=list(csv.DictReader(f))
assert len(ref)==len(rows)==520 and all(a['id']==b['id'] for a,b in zip(rows,ref))
primary={i:float(r['score']) for i,r in enumerate(ref)};secondary=read_secondary(aux/'scores.jsonl',520)
assert len(secondary)==520
hard={i for i,r in enumerate(rows) if analyze(r['prompt'],r['response'],False,bounded_turn_shape=True).hard}
combined,mode=blend(primary,secondary,520);assert mode=='rank_50_50'
metrics={}
for name,scores in [('saved35b',primary),('native4b_lora',secondary),('blend',combined)]:
 pred=decide(520,hard,scores,.4);gold=[int(r['label']) for r in ref]
 tp=sum(y==1 and g==1 for y,g in zip(pred,gold));fp=sum(y==1 and g==0 for y,g in zip(pred,gold));fn=sum(y==0 and g==1 for y,g in zip(pred,gold));tn=520-tp-fp-fn
 metrics[name]=dict(tp=tp,fp=fp,fn=fn,tn=tn,f1=2*tp/(2*tp+fp+fn))
print(json.dumps(dict(scope='CPU replay: fresh native-vLLM auxiliary dev520 plus historical saved35B; primary not rerun',rows=520,hard_rows=len(hard),positive_rate=.4,ranking=mode,metrics=metrics,primary_rows_sha256=hashlib.sha256(refpath.read_bytes()).hexdigest(),secondary_scores_sha256=hashlib.sha256((aux/'scores.jsonl').read_bytes()).hexdigest(),parameters_changed=False,private_improvement_measured=False),indent=2))
