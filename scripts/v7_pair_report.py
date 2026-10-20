"""CPU-only complete base/new comparison, published before the optional old control."""
import argparse
import json
from pathlib import Path
import sys
import tarfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write
from scripts.v5_valid46_pipeline import metrics
from scripts.v7_evaluate import keep_accusation,bootstrap
from guardian_truth.judge.decision import decide

def analyse(data,out,lab):
    prepared=json.loads((data/'PREPARED.json').read_bytes());protocol=json.loads((data/'EVAL_PROTOCOL.json').read_bytes())
    if sha(data/'EVAL_INDEX.json')!=prepared['eval_index_sha256']:raise ValueError('GOLD_INDEX_DRIFT')
    selected=set(protocol['ids']);rows=[r for r in json.loads((data/'EVAL_INDEX.json').read_bytes())['rows'] if r['id'] in selected]
    gold={r['id']:r['label'] for r in rows};arms={};receipts={}
    if len(rows)!=757:raise ValueError('PRIMARY_ROW_COUNT')
    for arm in ('base','new'):
        folder=out/arm;receipt=json.loads((folder/'DONE.json').read_bytes());receipts[arm]=receipt
        if not receipt['complete'] or receipt['rows']!=len(rows) or receipt['input_sha256']!=prepared['eval_tokens_sha256']:
            raise ValueError('INCOMPLETE_OR_DIFFERENT_ARM')
        values=read(folder/'scores.jsonl')
        if sha(folder/'scores.jsonl')!=receipt['scores_sha256'] or sha(folder/'repeat_scores.jsonl')!=receipt['repeat_scores_sha256']:
            raise ValueError('SCORE_FILE_DRIFT')
        arms[arm]={r['id']:r for r in values}
        if len(values)!=len(rows) or set(arms[arm])!=set(gold) or any(r['admitted'] and not r['exact'] for r in values):raise ValueError('SCORE_COVERAGE_OR_EXACT')
        if arm=='new':
            proof=json.loads((folder/'ADAPTER_BINDING.json').read_bytes())
            if len(proof)!=1 or not proof[0]['complete'] or proof[0]['covered_modules']!=receipt['source_modules']:raise ValueError('GPU_BINDING')
    oldroot=lab/'v5-35b-20261019/finish-v6/paired-native';oldreceipt=json.loads((oldroot/'WORKER_DONE.json').read_bytes())
    if sha(oldroot/'scores.jsonl')!=oldreceipt['scores_sha256']:raise ValueError('ORIGINAL_BASE_SCORE_DRIFT')
    original={r['id']:r for r in read(oldroot/'scores.jsonl') if r['arm']=='base'}
    result=dict(complete=True,scope='complete base/new comparison; old LoRA control reported separately',
        status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',independent_validation=False,private_improvement_measured=False,
        production_promoted=False,threshold=0,threshold_search=False,quota_refill=False,cohorts={},stability={},
        source_sha256=sha(Path(__file__)),input_sha256=prepared['eval_tokens_sha256'],
        base_done_sha256=sha(out/'base/DONE.json'),new_done_sha256=sha(out/'new/DONE.json'))
    for arm in arms:
        repeat=read(out/arm/'repeat_scores.jsonl')
        if len(repeat)!=92:raise ValueError('REPEATS_INCOMPLETE')
        result['stability'][arm]=dict(measurements=3,comparisons=92,
            decision_flips=sum(keep_accusation(r)!=keep_accusation(arms[arm][r['id']]) for r in repeat),
            changed_review=sum(r['review']!=arms[arm][r['id']]['review'] for r in repeat),apc=True)
    for cohort in ('real191','dev520','valid46'):
        subset=[r for r in rows if cohort in r['cohorts']];hard={i for i,r in enumerate(subset) if r['hard']}
        original_labels=decide(len(subset),hard,{i:original[r['id']]['score'] for i,r in enumerate(subset)},.4)
        decisions={arm:[int(i in hard or keep_accusation(arms[arm][r['id']])) for i,r in enumerate(subset)] for arm in arms}
        b=decisions['base'];n=decisions['new']
        item=dict(rows=len(subset),baseline_scope='historical overall-only pool40; not best-ZIP MAX',
            original_pool40=metrics(subset,gold,original_labels),arms={})
        for arm,labels in decisions.items():
            filtered=[int(x and y) for x,y in zip(original_labels,labels)]
            item['arms'][arm]=dict(verifier=metrics(subset,gold,labels),
                admitted=sum(arms[arm][r['id']]['admitted'] for r in subset),
                unknown=sum(not arms[arm][r['id']]['admitted'] for r in subset),
                original_pool40_after_verifier=metrics(subset,gold,filtered),
                pool40_removed_fp=sum(x and not y and gold[r['id']]==0 for r,x,y in zip(subset,original_labels,filtered)),
                pool40_lost_tp=sum(x and not y and gold[r['id']]==1 for r,x,y in zip(subset,original_labels,filtered)))
        item.update(removed_fp_vs_base=sum(x and not y and gold[r['id']]==0 for r,x,y in zip(subset,b,n)),
            lost_tp_vs_base=sum(x and not y and gold[r['id']]==1 for r,x,y in zip(subset,b,n)),
            added_fp_vs_base=sum(y and not x and gold[r['id']]==0 for r,x,y in zip(subset,b,n)),
            gained_tp_vs_base=sum(y and not x and gold[r['id']]==1 for r,x,y in zip(subset,b,n)),
            paired_group_bootstrap=bootstrap(subset,gold,b,n))
        result['cohorts'][cohort]=item
    best=read(lab/'v5-35b-20261019/pipeline-valid46-v4/base/work/decisions.jsonl')
    hard={r['key'] for r in best if r['hard']};p70=decide(46,hard,{r['key']:r['ranked_by'] for r in best},.7)
    lookup={r['original_id']:r for r in rows if 'valid46' in r['cohorts']};bestrows=[dict(id=lookup[r['id']]['id']) for r in best]
    result['best_pipeline_valid46_pool70']=dict(before=metrics(bestrows,gold,p70),arms={})
    for arm in arms:
        labels=[int(z and (b['key'] in hard or keep_accusation(arms[arm][r['id']]))) for b,r,z in zip(best,bestrows,p70)]
        result['best_pipeline_valid46_pool70']['arms'][arm]=dict(metrics=metrics(bestrows,gold,labels),
            removed_fp=sum(z and not y and gold[r['id']]==0 for r,z,y in zip(bestrows,p70,labels)),
            lost_tp=sum(z and not y and gold[r['id']]==1 for r,z,y in zip(bestrows,p70,labels)))
    tests={}
    for c in ('real191','dev520'):
        item=result['cohorts'][c];new=item['arms']['new']
        tests[c+'_vs_base']=new['verifier']['fp']<item['arms']['base']['verifier']['fp'] and item['lost_tp_vs_base']==0
        tests[c+'_original_pool40_no_tp_loss']=new['pool40_lost_tp']==0
        tests[c+'_original_pool40_fewer_fp']=new['pool40_removed_fp']>0
    tests['valid46_no_new_tp_loss']=result['cohorts']['valid46']['lost_tp_vs_base']==0
    tests['best_pipeline_valid46_pool70_no_tp_loss']=result['best_pipeline_valid46_pool70']['arms']['new']['lost_tp']==0
    result['offline_gate']=dict(tests=tests,passed=all(tests.values()),promotion_approved=False)
    write(out/'PAIR_RESULTS.json',result);return result

def run(a):
    started=time.monotonic()
    while not (a.out/'new/DONE.json').exists():
        if (a.out/'FAIL.json').exists():raise RuntimeError('EVALUATION_FAILED_BEFORE_NEW_COMPLETED')
        if time.time()>a.deadline:raise TimeoutError('PAIR_REPORT_WAIT_LIMIT')
        time.sleep(10)
    analyse(a.root/'prepared-v1',a.out,a.lab)
    archive=a.root/(a.out.name+'-pair-export.tar.gz')
    with tarfile.open(archive,'w:gz',compresslevel=3) as tar:
        for name in ('base','new','PAIR_RESULTS.json','START.json','EVAL_CODE_FROZEN.json'):tar.add(a.out/name,arcname=a.out.name+'/'+name)
    write(a.root/(a.out.name+'-pair-export.INDEX.json'),dict(name=archive.name,bytes=archive.stat().st_size,
        sha256=sha(archive),complete=True,scope='complete base/new only',seconds=time.monotonic()-started))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lab','root','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--deadline',type=float,required=True);run(p.parse_args())
