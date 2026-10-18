"""Gold-reading analysis for frozen external and real transfer scores."""
import argparse,csv,hashlib,json,math,random,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge.decision import decide
from scripts.analyze_judge_dependencies_20261018 import metrics,rank_metrics

def read(p):return [json.loads(l) for l in p.read_bytes().splitlines() if l.strip()]
def csvrows(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def assess(y,scores,hard):
    return dict(ranking=rank_metrics(y,scores),zero=metrics(y,[int(s>0 or i in hard) for i,s in enumerate(scores)]),
        quotas={str(q):metrics(y,decide(len(y),hard,dict(enumerate(scores)),q)) for q in (.3,.4,.5,.6)})
def bootstrap(y,b,a,groups):
    by={}
    for i,g in enumerate(groups):by.setdefault(g,[]).append(i)
    names=sorted(by);rng=random.Random(20261018);d=[]
    for _ in range(1000):
        ix=[i for g in rng.choices(names,k=len(names)) for i in by[g]]
        d.append(metrics([y[i] for i in ix],[a[i] for i in ix])['f1']-metrics([y[i] for i in ix],[b[i] for i in ix])['f1'])
    d.sort();return dict(groups=len(by),resamples=1000,fixed_decisions=True,ci95=[d[24],d[974]])

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--run',type=Path,required=True);ap.add_argument('--data',type=Path,required=True);ap.add_argument('--saved',type=Path,required=True);a=ap.parse_args();csv.field_size_limit(2**31-1)
    done=json.loads((a.run/'DONE.json').read_bytes());assert done['complete'] and done['training_steps_added']==0 and not done['over_cap']
    records=read(a.run/'scores.jsonl');requests=read(a.run/'requests.jsonl')
    by={(r['dataset'],r['arm'],r['key']):r for r in records};rq={(r['dataset'],r['key']):r for r in requests}
    assert len(records)==len(by)==4580 and len(requests)==len(rq)==2290
    assert all(hashlib.sha256(r['text'].encode('utf-8','surrogatepass')).hexdigest()==r['input_sha256'] for r in requests)
    out={};real_detail=None
    for name,count in [('compli_eval',1893),('regression_seen',397)]:
        inputs=csvrows(a.data/name/'inputs.csv');gold=read(a.data/name/'labels.jsonl')
        assert len(inputs)==len(gold)==count and sha(a.data/name/'inputs.csv')==done['sources'][name]
        for k,(r,g) in enumerate(zip(inputs,gold)):
            assert r['id']==g['id']
            pair=hashlib.sha256((r['prompt']+'\0'+r['response']).encode()).hexdigest()
            assert rq[name,k]['row_sha256']==pair
            for arm in ('base','adapter'):
                v=by[name,arm,k];assert v['exact'] and math.isfinite(v['score']) and v['row_sha256']==pair and v['input_sha256']==rq[name,k]['input_sha256']
        y=[g['label'] for g in gold];hard=set();ref=None
        if name=='regression_seen':
            ref=csvrows(a.saved/'regression_r1/rows.csv');assert [r['id'] for r in ref]==[r['id'] for r in inputs]
            assert all(int(r['label'])==g['label'] for r,g in zip(ref,gold));hard={i for i,r in enumerate(ref) if r['hard']}
        sc={arm:[by[name,arm,k]['score'] for k in range(count)] for arm in ('base','adapter')}
        b=decide(count,hard,dict(enumerate(sc['base'])),.4);p=decide(count,hard,dict(enumerate(sc['adapter'])),.4)
        result=dict(rows=count,positives=sum(y),hard=len(hard),arms={arm:assess(y,ss,hard) for arm,ss in sc.items()},
            changed_at40=dict(tp_lost=sum(t and x and not z for t,x,z in zip(y,b,p)),tp_gained=sum(t and not x and z for t,x,z in zip(y,b,p)),
                fp_removed=sum(not t and x and not z for t,x,z in zip(y,b,p)),fp_added=sum(not t and not x and z for t,x,z in zip(y,b,p))),
            paired_f1_bootstrap=bootstrap(y,b,p,[g['conversation'] for g in gold]),
            by_domain={d:{arm:assess([y[i] for i,g in enumerate(gold) if g['domain']==d],
                [s for s,g in zip(ss,gold) if g['domain']==d],set()) for arm,ss in sc.items()} for d in sorted({g['domain'] for g in gold})})
        if ref:
            result['saved_35b_reference']={arm:assess(y,[float(r[col]) for r in ref],hard) for arm,col in [('overall','primary_score'),('final','final_score')]}
            valid=csvrows(a.saved/'valid46_r1/rows.csv');ix={r['id']:i for i,r in enumerate(inputs)};keys=[ix[r['id']] for r in valid]
            assert all(int(v['label'])==y[k] for v,k in zip(valid,keys))
            result['valid46_subset']=dict(independent=False,rows=46,arms={arm:assess([y[k] for k in keys],[ss[k] for k in keys],{i for i,k in enumerate(keys) if k in hard}) for arm,ss in sc.items()})
            real_detail=[dict(id=r['id'],key=k,label=y[k],base=sc['base'][k],adapter=sc['adapter'][k],before=b[k],after=p[k]) for k,r in enumerate(inputs)]
        out[name]=result
    fresh=out['compli_eval']['arms'];real=out['regression_seen']['arms']
    conditions=dict(full_coverage=True,fresh_f1_improves=fresh['adapter']['quotas']['0.4']['f1']>fresh['base']['quotas']['0.4']['f1'],
        fresh_auc_improves=fresh['adapter']['ranking']['roc_auc']>fresh['base']['ranking']['roc_auc'],
        real_f1_drop_at_most_02=real['adapter']['quotas']['0.4']['f1']>=real['base']['quotas']['0.4']['f1']-.02)
    result=dict(schema='frozen-lora-transfer-analysis-v1',datasets=out,gate=dict(conditions=conditions,passes=all(conditions.values()),production_accepted=False),
        usage=done['usage'],wall_seconds=done['wall_seconds'],peak_gpu_bytes=done['peak_gpu_bytes'],
        scope='FRESH_EXTERNAL_FAMILY_TRANSFER_PLUS_SEEN_GUARDIAN; NOT_PRIVATE_TEST_OR_RUNTIME_ACCEPTANCE',real_rows=real_detail)
    (a.run/'ANALYSIS.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
    print(json.dumps({k:v for k,v in result.items() if k!='real_rows'},indent=2))
if __name__=='__main__':main()
