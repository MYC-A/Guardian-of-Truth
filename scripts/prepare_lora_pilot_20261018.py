"""Construct a small audited training mix; protected dev/eval/seen never train."""
import argparse,csv,hashlib,json,sys,zipfile
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.prepare_judge_eval_data_20261018 import compli_rows
from scripts.prepare_consent_seed_data_20261018 import case,DOMAINS,VARIANTS
from scripts.analyze_consent_verifier_v2_20261018 import authorized

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def write(path,x):path.write_bytes((json.dumps(x,indent=2)+'\n').encode())
def lines(path,rs):path.write_bytes(b''.join((json.dumps(r,ensure_ascii=True)+'\n').encode() for r in rs))
def csvrows(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    a.out.mkdir(exist_ok=False);csv.field_size_limit(2**31-1)
    lock=json.loads((a.data/'SOURCE_LOCK.json').read_bytes());splits=json.loads((a.data/'SPLITS.json').read_bytes())
    assert hashlib.sha256(a.archive.read_bytes()).hexdigest()==lock['compli']['sha256']
    technical=[json.loads(l) for l in (a.data/'compli_pilot/labels.jsonl').read_bytes().splitlines()]
    seen_convs={r['conversation'] for r in technical}
    natural=[]
    with zipfile.ZipFile(a.archive) as z:
        prefix=z.namelist()[0].split('/')[0]+'/'
        for path,group in sorted(splits['conversations'].items()):
            if splits['assignments'][group]!='pilot':continue
            raw=z.read(prefix+path);doc=json.loads(raw)
            natural.extend(compli_rows(doc,path,hashlib.sha256(raw).hexdigest(),group))
    assert len(natural)==300
    # Validation conversations are chosen without labels or model scores and have
    # not appeared among the 24 technical examples. No protected family moves.
    val_convs=set()
    for domain in ('airlines','healthcare','insurance'):
        eligible=sorted({r['conversation'] for r in natural if r['domain']==domain}-seen_convs,key=lambda s:digest(['lora-v1-val',s]))
        val_convs.update(eligible[:2])
    train=[];validation=[]
    for r in natural:
        out=dict(id='lora-natural:'+r['id'],prompt=r['prompt'],response=r['response'],label=r['label'],
                 task='whole_turn',group=r['group'],conversation=r['conversation'],origin='compli_pilot_partition')
        (validation if r['conversation'] in val_convs else train).append(out)
    natural_train=len(train)
    # Deliberately small synthetic part. Other domains/scenarios remain diagnostic.
    for domain in ('telecom','hotel','retail','banking','university'):
        for n in range(1,5):
            for variant in VARIANTS:
                r=case(domain,n,variant)
                item=dict(id=r['id'],prompt=r['prompt'],response=r['response'],label=r['label'],task='whole_turn',
                          group=r['group'],conversation=r['group'],origin='controlled_synthetic')
                train.append(item)
                if n<=2:
                    train.append(dict(item,id=r['id']+':authorization',task='authorization',label=authorized(r['oracle'])))
    val_prompts={digest(r['prompt']) for r in validation}
    purged=[r for r in train if digest(r['prompt']) in val_prompts]
    train=[r for r in train if digest(r['prompt']) not in val_prompts]
    natural_train=sum(r['origin']=='compli_pilot_partition' for r in train)
    assert not ({digest(r['prompt']) for r in train}&val_prompts)
    protected={}
    for name in ('compli_dev','compli_eval','regression_seen'):
        rows=csvrows(a.data/name/'inputs.csv');pairs={digest([r['prompt'],r['response']]) for r in rows}
        prompts={digest(r['prompt']) for r in rows}
        assert not any(digest([r['prompt'],r['response']]) in pairs or digest(r['prompt']) in prompts for r in train+validation),name
        protected[name]=dict(rows=len(rows),inputs_sha256=hashlib.sha256((a.data/name/'inputs.csv').read_bytes()).hexdigest())
    assert not ({r['conversation'] for r in train}&{r['conversation'] for r in validation})
    assert all(splits['assignments'][r['group']]=='pilot' for r in train+validation if r['origin']=='compli_pilot_partition')
    evalsets={'natural_validation':validation}
    syn=[]
    for domain in ('fitness','clinic'):
        for n in range(8,16):
            for v in VARIANTS:
                r=case(domain,n,v)
                item=dict(id=r['id'],prompt=r['prompt'],response=r['response'],label=r['label'],task='whole_turn',
                          group=r['group'],origin='domain_disjoint_synthetic')
                syn.append(item);syn.append(dict(item,id=r['id']+':authorization',task='authorization',label=authorized(r['oracle'])))
    evalsets['synthetic_diagnostic']=syn
    # The protected dev inputs, not their labels, enter the inference package.
    dev=csvrows(a.data/'compli_dev/inputs.csv')
    evalsets['dev520']=[dict(r,task='whole_turn') for r in dev]
    lines(a.out/'train.jsonl',train)
    for name,rows in evalsets.items():
        lines(a.out/(name+'_inputs.jsonl'),[{k:v for k,v in r.items() if k!='label'} for r in rows])
        if name!='dev520':lines(a.out/(name+'_gold.jsonl'),[dict(id=r['id'],label=r['label'],task=r['task']) for r in rows])
    m=dict(schema='lora-pilot-training-mix-v1',status='EXPERIMENTAL_TRAINING_PILOT_NOT_PRODUCTION',
        train_rows=len(train),natural_train_rows=natural_train,natural_validation_rows=len(validation),
        synthetic_train_whole=280,synthetic_train_authorization=140,train_labels=dict(Counter(str(r['label']) for r in train)),
        tasks=dict(Counter(r['task'] for r in train)),protected=protected,
        training_partition='Old technical pilot families reclassified as training; never reuse them as independent evaluation',
        validation_conversations=sorted(val_convs),technical_seen_conversations_forced_train=sorted(seen_convs),
        exact_pair_overlap=0,exact_prompt_overlap=0,natural_family_overlap_with_dev_eval=0,
        train_validation_prompt_overlap=0,purged_training_prefix_ids=[r['id'] for r in purged],
        purge_rule='Drop training rows whose exact prompt occurs in natural validation; no label or model score selection',
        limitations=['Compli prefix gold is upstream synthetic and not full Guardian materiality gold',
                     'Synthetic language is templated; cannot establish competition generalization',
                     'Natural validation shares policy families with training, but conversations are disjoint',
                     'Existing source grouping uses near-dialogue components; no method proves semantic independence'],
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        files={q.name:dict(bytes=q.stat().st_size,sha256=hashlib.sha256(q.read_bytes()).hexdigest()) for q in a.out.iterdir()})
    write(a.out/'MANIFEST.json',m);print(json.dumps({k:v for k,v in m.items() if k not in ('files','technical_seen_conversations_forced_train','protected')},indent=2))
if __name__=='__main__':main()
