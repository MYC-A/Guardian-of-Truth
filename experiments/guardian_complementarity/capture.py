import sys, json, hashlib
root=sys.argv[1]; sys.path[:0]=[root, root+'/src']
import pandas as pd
from guardian_truth.repair.v5 import ARMS, run_v5
rows={r.id:dict(id=r.id,prompt=r.prompt,response=r.response) for r in pd.read_parquet('experiments/searh_23/three_architectures/data/valid.parquet').itertuples()}
class Cap:
    def __init__(s): s.reqs=[]
    def call(s, request, attempt=0, tag=''):
        s.reqs.append((tag,request)); return dict(content=None, usage=None, cached=False, transport=dict(status='CAPTURE'))
    def __getattr__(s,k): return lambda *a,**k: None
out={}
for i,row in rows.items():
    c=Cap()
    try: run_v5(row, c, flags=ARMS['R_fix'])
    except Exception as e: out[i]=dict(err=repr(e)[:200]); 
    rv=[r for t,r in c.reqs if t=='review']
    if rv: out[i]=dict(sys=rv[0]['messages'][0]['content'], user=rv[0]['messages'][1]['content'], rf=json.dumps(rv[0].get('response_format'),sort_keys=True), mt=rv[0].get('max_tokens'), model=rv[0].get('model'))
json.dump(out,open(sys.argv[2],'w'))
print(len(out), sum('err' in v for v in out.values()))
