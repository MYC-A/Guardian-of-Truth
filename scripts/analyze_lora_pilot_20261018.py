"""Offline gold-reading analysis for one frozen LoRA pilot; never train on dev."""
import argparse,csv,hashlib,json,math,random,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge.decision import decide
from scripts.analyze_judge_dependencies_20261018 import metrics,rank_metrics,ranks

def read(p):return [json.loads(l) for l in p.read_bytes().splitlines() if l.strip()]
def csvrows(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def assess(y,scores):
    return dict(ranking=rank_metrics(y,scores),zero=metrics(y,[int(s>0) for s in scores]),
        quotas={str(q):metrics(y,decide(len(y),set(),dict(enumerate(scores)),q)) for q in (.3,.4,.5,.6)})

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--data',type=Path,required=True);p.add_argument('--protected',type=Path,required=True);p.add_argument('--saved',type=Path,required=True);a=p.parse_args();csv.field_size_limit(2**31-1)
    done=json.loads((a.run/'DONE.json').read_bytes());assert done['complete'] and done['training_steps']==math.ceil(done['train_rows']/16)
    manifest=json.loads((a.data/'MANIFEST.json').read_bytes());assert done['data_manifest_sha256']==sha(a.data/'MANIFEST.json')
    for name,rec in done['adapter_files'].items():assert sha(a.run/'adapter'/name)==rec['sha256']
    records=read(a.run/'scores.jsonl');requests=read(a.run/'requests.jsonl')
    rk=lambda r:(r['partition'],r['id'])
    req={rk(r):r for r in requests};by={(r['arm'],*rk(r)):r for r in records}
    assert len(req)==len(requests) and len(by)==len(records)
    assert all(hashlib.sha256(r['text'].encode('utf-8','surrogatepass')).hexdigest()==r['input_sha256'] for r in requests)
    results={};goldmap={};inputsmap={}
    for partition in ('natural_validation','synthetic_diagnostic','dev520'):
        inputs=read(a.data/(partition+'_inputs.jsonl'))
        gold=read(a.protected/'compli_dev/labels.jsonl') if partition=='dev520' else read(a.data/(partition+'_gold.jsonl'))
        assert [r['id'] for r in inputs]==[g['id'] for g in gold]
        assert len(inputs)==done['evaluation_rows'][partition]
        goldmap[partition]=gold;inputsmap[partition]=inputs
        for row in inputs:
            key=(partition,row['id']);request=req[key]
            source=hashlib.sha256((row['prompt']+'\0'+row['response']).encode()).hexdigest()
            assert source==request['row_sha256']
            for arm in ('base','adapter'):
                r=by[(arm,*key)]
                assert r['exact'] and math.isfinite(r['score']) and r['row_sha256']==source and r['input_sha256']==request['input_sha256']
        results[partition]={}
        for task in sorted({r['task'] for r in inputs}):
            selected=[i for i,r in enumerate(inputs) if r['task']==task];y=[gold[i]['label'] for i in selected]
            results[partition][task]=dict(rows=len(selected),positives=sum(y),arms={arm:assess(y,[by[arm,partition,inputs[i]['id']]['score'] for i in selected]) for arm in ('base','adapter')})
    expected=2*sum(done['evaluation_rows'].values());assert len(records)==expected
    ref=csvrows(a.saved/'dev_r1b/rows.csv');inp=inputsmap['dev520'];gold=goldmap['dev520']
    assert len(ref)==len(inp)==len(gold)==520
    assert all(r['id']==i['id']==g['id'] and int(r['label'])==g['label'] for r,i,g in zip(ref,inp,gold))
    y=[g['label'] for g in gold];primary=[float(r['primary_score']) for r in ref];rr=ranks(primary)
    ensembles={}
    for arm in ('base','adapter'):
        scores=[by[arm,'dev520',r['id']]['score'] for r in inp];ar=ranks(scores)
        ensembles[arm]=assess(y,[(x+z)/(2*len(y)) for x,z in zip(rr,ar)])
    dev=results['dev520']['whole_turn']['arms'];bd=dev['base'];ad=dev['adapter']
    reference=assess(y,primary);q='.4' if '.4' in ad['quotas'] else '0.4'
    conditions=dict(full_coverage=len(records)==expected,
        dev_f1_gain_at_least_02=ad['quotas'][q]['f1']-bd['quotas'][q]['f1']>=.02,
        dev_auc_gain_at_least_01=ad['ranking']['roc_auc']-bd['ranking']['roc_auc']>=.01,
        reaches_35b_overall=max(ad['quotas'][q]['f1'],ensembles['adapter']['quotas'][q]['f1'])>=reference['quotas'][q]['f1'])
    # Paired conversation bootstrap of FIXED quota decisions, not re-tuning quotas.
    bpred=decide(520,set(),{i:by['base','dev520',r['id']]['score'] for i,r in enumerate(inp)},.4)
    apred=decide(520,set(),{i:by['adapter','dev520',r['id']]['score'] for i,r in enumerate(inp)},.4)
    groups={}
    for i,g in enumerate(gold):groups.setdefault(g['conversation'],[]).append(i)
    names=sorted(groups);rng=random.Random(20261018);deltas=[]
    for _ in range(1000):
        ids=[i for name in rng.choices(names,k=len(names)) for i in groups[name]]
        deltas.append(metrics([y[i] for i in ids],[apred[i] for i in ids])['f1']-metrics([y[i] for i in ids],[bpred[i] for i in ids])['f1'])
    deltas.sort()
    result=dict(schema='classification-lora-pilot-analysis-v1',scope='EXPLORATORY_DEV_AND_TEMPLATE_DIAGNOSTICS_NOT_PRIVATE_TEST',
        scores=len(records),datasets=results,dev_reference_35b=reference,dev_fixed_rank_ensembles=ensembles,
        dev_paired_f1_bootstrap=dict(groups=len(groups),resamples=1000,ci95=[deltas[24],deltas[974]],fixed_decisions=True),
        gate=dict(conditions=conditions,passes=all(conditions.values()),production_accepted=False),
        training=dict(rows=done['train_rows'],steps=done['training_steps'],seconds=done['training_seconds'],trainable_parameters=done['trainable_parameters']),
        wall_seconds=done['wall_seconds'],evaluation_seconds=done['evaluation_seconds'],
        caveats=['One epoch/seed, no optimization on evaluation gold','Natural validation shares policy families but exact prompt/pair overlap is zero',
                 'Compli prefix labels differ from full Guardian task','No fresh eval1893/seen397/valid46 inference in this pilot'])
    (a.run/'ANALYSIS.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
