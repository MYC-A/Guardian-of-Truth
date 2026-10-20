import json
from types import SimpleNamespace
from scripts import v11_candidate_fresh as v11


def put(path,value,lines=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r)+'\n' for r in value) if lines else json.dumps(value),encoding='utf-8')


def test_fresh_tp_loss_is_visible_and_hard_cannot_be_vetoed(tmp_path):
    lab=tmp_path/'lab';source=tmp_path/'source';pred=[dict(id=str(i),label=int(i<208)) for i in range(520)]
    metadata=[dict(id='compli_dev::'+str(i),original_id=str(i),label=int(i%2==0),cohorts=['dev520']) for i in range(520)]
    put(source/'EVAL_INDEX.json',dict(rows=metadata))
    put(lab/'v10-full-profile-batch64-20261020/evaluation-v10/work/decisions.jsonl',
        [dict(id=str(i),hard=['proof'] if i==0 else []) for i in range(520)],True)
    cached=[dict(id=r['id'],admitted=True,score=-1 if i in {0,1} else 1) for i,r in enumerate(metadata)]
    put(lab/'v8-json-quote-replay-20261020/evaluation-v8/new/scores.jsonl',cached,True)
    first=cached[:208];second=[dict(r,score=-1 if i==2 else r['score']) for i,r in enumerate(first)]
    result=v11.analyse(SimpleNamespace(lab=lab),source,pred,[first,second,first])
    assert result['passes'][0]['lost_tp']==0 and result['passes'][0]['removed_fp']==1
    assert result['passes'][1]['lost_tp']==1 and result['passes'][1]['decisions_changed_vs_first']==1
    assert result['fresh_vs_cached_decision_changes']==[0,1,0]
