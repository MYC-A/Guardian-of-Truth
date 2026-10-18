"""Independent sklearn counts and upstream-data audit; no Guardian scorer imports."""
import argparse,csv,hashlib,json,math,re,unicodedata,zipfile
from pathlib import Path
from sklearn.metrics import confusion_matrix,f1_score,precision_score,recall_score,roc_auc_score,average_precision_score
import sklearn

def read(p):return [json.loads(l) for l in p.read_bytes().splitlines() if l.strip()]
def table(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def normalize(r):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',r).casefold()).strip()
def quota(scores,rate,hard=()):
    # Independent reconstruction: hard rows occupy places, then sorted model scores fill the quota.
    selected=set(hard);target=round(rate*len(scores))
    ordered=sorted(range(len(scores)),key=lambda i:(-scores[i],i))
    for i in ordered:
        if len(selected)>=target:break
        selected.add(i)
    return [int(i in selected) for i in range(len(scores))]
def compare(y,scores,ref,hard):
    checked=0
    for rate in (.3,.4,.5,.6):
        pred=quota(scores,rate,hard);tn,fp,fn,tp=map(int,confusion_matrix(y,pred,labels=[0,1]).ravel())
        vals=dict(tp=tp,fp=fp,fn=fn,tn=tn,f1=float(f1_score(y,pred,zero_division=0)),precision=float(precision_score(y,pred,zero_division=0)),recall=float(recall_score(y,pred,zero_division=0)))
        for k,v in vals.items():assert math.isclose(v,ref['quotas'][str(rate)][k],abs_tol=1e-12),(rate,k,v,ref['quotas'][str(rate)][k])
        checked+=1
    for name,calc in [('roc_auc',roc_auc_score),('average_precision',average_precision_score)]:
        assert math.isclose(float(calc(y,scores)),ref['ranking'][name],abs_tol=1e-12),(name,float(calc(y,scores)),ref['ranking'][name])
    return checked

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True);p.add_argument('--protected',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--saved',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();csv.field_size_limit(2**31-1)
    pilot=json.loads((a.study/'run/ANALYSIS.json').read_bytes());transfer=json.loads((a.study/'transfer/ANALYSIS.json').read_bytes());pr=read(a.study/'run/scores.jsonl');tr=read(a.study/'transfer/scores.jsonl');checks=0
    for partition,name in [('dev520','compli_dev'),('compli_eval','compli_eval'),('regression_seen','regression_seen')]:
        gold=read(a.protected/name/'labels.jsonl');inputs=table(a.protected/name/'inputs.csv');assert [r['id'] for r in gold]==[r['id'] for r in inputs]
        y=[g['label'] for g in gold];rows=pr if partition=='dev520' else tr
        by={(r['arm'],r['id']):r for r in rows if r.get('partition',r.get('dataset'))==partition}
        ref=pilot['datasets']['dev520']['whole_turn']['arms'] if partition=='dev520' else transfer['datasets'][partition]['arms']
        hard={i for i,r in enumerate(table(a.saved/'regression_r1/rows.csv')) if r['hard']} if partition=='regression_seen' else set()
        for arm in ('base','adapter'):
            ss=[]
            for r in inputs:
                receipt=by[arm,r['id']];assert receipt['row_sha256']==hashlib.sha256((r['prompt']+'\0'+r['response']).encode()).hexdigest()
                ss.append(receipt['score'])
            checks+=compare(y,ss,ref[arm],hard)
    valid=table(a.saved/'valid46_r1/rows.csv');y=[int(r['label']) for r in valid];hard={i for i,r in enumerate(valid) if r['hard']}
    by={(r['arm'],r['id']):r for r in tr if r['dataset']=='regression_seen'}
    for arm in ('base','adapter'):
        checks+=compare(y,[by[arm,r['id']]['score'] for r in valid],transfer['datasets']['regression_seen']['valid46_subset']['arms'][arm],hard)
    # Independent raw source reconstruction, based on read-only upstream build_truth contract.
    z=zipfile.ZipFile(a.archive);prefix=z.namelist()[0].split('/')[0]+'/'
    upstream_checked=0
    sources=[]
    for name in ('compli_dev','compli_eval'):
        rows=table(a.protected/name/'inputs.csv');gg=read(a.protected/name/'labels.jsonl');sources.extend((r,g['label'],g['source_path'],g['turn_index']) for r,g in zip(rows,gg))
    train=read(a.study/'train.jsonl')
    for r in train:
        if r['origin']=='compli_pilot_partition':
            path,turn=r['id'].split('compli:',1)[1].rsplit(':t',1);sources.append((r,r['label'],path,int(turn)))
    for row,label,path,turn in sources:
        doc=json.loads(z.read(prefix+path));message=next(m for m in doc['message_list'] if m['turn_index']==turn)
        assert message['role']=='assistant' and bool(message.get('category')) and bool(message.get('key'))
        expected=int(any(m['turn_index']==turn for m in doc['mistakes']));assert label==expected,(row['id'],'UPSTREAM_LABEL')
        policy={k:v for k,v in doc['assistant_guidelines'].items() if k.lower().startswith(('category 2','category 3'))}
        system='You are a customer-service assistant. Follow the operational policy below.\n<policy>\n'+json.dumps(policy,ensure_ascii=False,indent=2)+'\n</policy>'
        history='\u27e6SYSTEM\u27e7\n'+system+'\n'
        for m in doc['message_list']:
            if m['turn_index']==turn:break
            history+='\u27e6'+m['role'].upper()+'\u27e7\n'+m['content']+'\n'
        response='\u27e6ASSISTANT\u27e7\n'+message['content']+'\n'
        assert row['prompt']==history and row['response']==response,(row['id'],'SOURCE_OR_ANNOTATION_LEAK')
        upstream_checked+=1
    normalized_train={(normalize(r['prompt']),normalize(r['response'])) for r in train}
    overlap={}
    for name in ('compli_dev','compli_eval','regression_seen'):
        rows=table(a.protected/name/'inputs.csv');n=sum((normalize(r['prompt']),normalize(r['response'])) in normalized_train for r in rows);assert n==0;overlap[name]=n
    result=dict(schema='lora-independent-cpu-audit-v1',complete=True,sklearn_version=sklearn.__version__,metric_tables_recomputed=checks,
        rank_metric_pairs_recomputed=8,upstream_source_and_label_rows_verified=upstream_checked,
        annotations_in_rendered_inputs=False,normalized_exact_train_pair_overlap=overlap,
        training_rows=len(train),training_labels_from_dev_or_eval=False,source_archive_sha256=hashlib.sha256(a.archive.read_bytes()).hexdigest(),
        limitations=['Exact normalized overlap excludes neither shared benchmark templates nor semantic similarity',
                     'Upstream gold is checked for faithful extraction, not independently adjudicated correctness',
                     'GPU vanilla vs disabled/active audit is separate'])
    a.out.write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps(result,indent=2))
if __name__=='__main__':main()
