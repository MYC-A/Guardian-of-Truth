import json, glob, csv, pandas as pd, collections, re
from pathlib import Path
G={r.id:int(r.label) for r in pd.read_parquet('experiments/searh_23/three_architectures/data/valid.parquet').itertuples()}
S={}
def add(name,d):
    S[name]={i:d.get(i) for i in G}
def L(f): return [json.loads(x) for x in open(f) if x.strip()]
for f in glob.glob('outputs/guardian_local_a100/*/*/runs/valid46/*.jsonl'):
    m=f.split('/')[3].split('@')[0]; arm=Path(f).stem.split('_')[0]
    rows=L(f)
    def ok(r): return not r.get('error') and not (r.get('technical') or r.get('failed'))
    add(f'{m}:{arm}',{r['id']:r.get('binary') for r in rows})
    if arm=='AM': add(f'{m}:A',{r['id']:r.get('binary_rfix') for r in rows})
for k in '123':
    add(f'v6fix:{k}',{r['id']:r['v6'][k] for r in L('outputs/guardian_v6_fix/runs/valid46.jsonl')})
for f in glob.glob('outputs/universal_repair*/runs*/valid46/*.jsonl'):
    n='UR:'+f.split('/')[1].replace('universal_repair','')+f.split('/')[2].replace('runs','')+':'+Path(f).stem
    add(n,{r['id']:int(r['A_adm2']['decision']=='ERROR') for r in L(f) if 'A_adm2' in r})
for f in glob.glob('outputs/multipacket_v1/runs/valid46/run1/*.jsonl'):
    if 'ORACLE' in f: continue
    add('MP:'+Path(f).stem,{r['id']:int(r['decision']=='ERROR') for r in L(f)})
for f in glob.glob('outputs/integrated_v1/phase_valid46/*/*/rep1.jsonl'):
    add('INT:'+f.split('/')[3]+':'+f.split('/')[4],{r['id']:r['binary'] for r in L(f)})
for f in glob.glob('outputs/verification_v2/runs/valid46/*.jsonl'):
    rows=L(f)
    add('VER:'+Path(f).stem,{r['id']:int((r.get('Av') or r.get('A_adm2') or {}).get('decision')=='ERROR') for r in rows})
for r in csv.DictReader(open('outputs/searh_23/baseline_frozen/control_repro_percase.csv')):
    pass
g={r['id']:r for r in csv.DictReader(open('outputs/searh_23/baseline_frozen/control_repro_percase.csv'))}
add('granite:flash',{i:int(r['granite_flash']) for i,r in g.items()}); add('granite:repro',{i:int(r['granite_repro']) for i,r in g.items()})
def sc(p):
    tp=sum(1 for i in G if G[i] and p.get(i)==1); fp=sum(1 for i in G if not G[i] and p.get(i)==1); fn=sum(G.values())-tp
    return tp,fp,fn,round(2*tp/(2*tp+fp+fn),3) if tp else 0
res={n:sc(p) for n,p in S.items()}
json.dump(dict(gold=G,systems=S),open('outputs/guardian_complementarity/valid46_matrix.json','w'))
for n,v in sorted(res.items(),key=lambda x:-x[1][3]): print(n,v)
