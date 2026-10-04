"""Controller / cost statistics from run jsonl (zero inference). usage: python -m experiments.multipacket_v1.stats <runs_dir> [out.json]"""
import json,collections,statistics as st,sys,glob,os
base=sys.argv[1]
out={}
for f in sorted(glob.glob(base+'/*.jsonl')):
    a=os.path.basename(f)[:-6]
    R=[json.loads(l) for l in open(f)]
    d={'n':len(R)}
    calls=[sum(1 for s in r.get('steps',[]) if not s.get('cached')) for r in R]
    allsteps=[len(r.get('steps',[])) for r in R]
    pt=[sum((s.get('usage') or {}).get('prompt_tokens',0) for s in r.get('steps',[])) for r in R]
    d['steps_mean']=round(st.mean(allsteps),2); d['prompt_tok_mean']=round(st.mean(pt)); d['sec_mean']=round(st.mean([r.get('seconds') or 0 for r in R]),1)
    C=[r['controller'] for r in R if 'controller' in r]
    if C:
        d['hops_mean']=round(st.mean(c['hops'] for c in C),2)
        d['chars_mean']=round(st.mean(c['chars'] for c in C))
        d['stop']=dict(collections.Counter(c['stop'] for c in C))
        d['questions_mean']=round(st.mean(c['questions'] for c in C),2)
        d['loops_prevented']=sum(c['loops_prevented'] for c in C)
        d['units_mean']=round(st.mean(len(c['selected_units']) for c in C),1)
    for k in ['answered','established','depth','qa_rounds','flagged','new_units']:
        v=[r[k] for r in R if k in r and r[k] is not None]
        if v: d[k+'_mean']=round(st.mean(v),2); d[k+'_sum']=sum(v)
    if any('scan_ok' in r for r in R): d['scan_ok']=sum(1 for r in R if r.get('scan_ok'))
    deg=collections.Counter(r.get('degenerate') for r in R if r.get('degenerate')); 
    if deg: d['degenerate']=dict(deg)
    out[a]=d
txt=json.dumps(out,indent=1)
if len(sys.argv)>2: open(sys.argv[2],'w').write(txt)
print(txt)
