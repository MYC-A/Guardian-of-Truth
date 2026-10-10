import json,sys
sys.path[:0]=['src','.']
import os; os.environ.setdefault('GUARDIAN_DATA_ROOT','/data/got')
from experiments.guardian_local_a100.score_local import gold_for
gold={k:int(v['label']) if isinstance(v,dict) else int(v) for k,v in gold_for('valid46').items()}
def load(p):
    d={}
    for l in open(p):
        r=json.loads(l); d[r['id']]=int(r['binary'])
    return d
runs={n:load(p) for n,p in [(a.split('=')[0],a.split('=')[1]) for a in sys.argv[1:]]}
def f1(pred):
    tp=sum(1 for k,g in gold.items() if g and pred.get(k)==1);fp=sum(1 for k,g in gold.items() if not g and pred.get(k)==1);fn=sum(1 for k,g in gold.items() if g and pred.get(k)!=1)
    return round(2*tp/(2*tp+fp+fn),4),tp,fp,fn
for n,p in runs.items(): print(n,f1(p))
ids=sorted(gold)
if len(runs)>=3:
    maj={k:int(sum(r[k] for r in runs.values())*2>len(runs)) for k in ids}
    print('majority',f1(maj))
    anyv={k:int(any(r[k] for r in runs.values())) for k in ids}; print('any',f1(anyv))
dis=[k for k in ids if len({r[k] for r in runs.values()})>1]
print('disagree',len(dis))
for k in dis: print(' ',k,'gold',gold[k],[r[k] for r in runs.values()])
