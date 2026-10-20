import csv
import json
from types import SimpleNamespace
import pytest
from scripts import v9_full_pipeline_dev520 as v9
from scripts import judge_submission as primary


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


def lines(path,values):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r)+'\n' for r in values),encoding='utf-8')


def csvfile(path,values):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(values[0]));w.writeheader();w.writerows(values)


def fixture(tmp_path,monkeypatch):
    lab=tmp_path/'lab';out=tmp_path/'out';a=SimpleNamespace(lab=lab,out=out)
    values=[dict(id=str(i),prompt='Frozen policy and transcript '+str(i),response='Current turn') for i in range(520)]
    csvfile(out/'inputs.csv',values)
    source=lab/'data/guardian-judge-eval-data-v1/compli_dev/inputs.csv';csvfile(source,values)
    csvfile(out/'predictions.csv',[dict(id=str(i),label=int(i<208)) for i in range(520)])
    decisions=[dict(id=str(i),hard=['mechanical finding'] if i==0 else [],ranking='max_exact_overall_final') for i in range(520)]
    lines(out/'work/decisions.jsonl',decisions);lines(out/'work/scores.jsonl',[dict(event='test-placeholder')])
    lines(out/'generation_audit.jsonl',[dict(adapter_applied=False,max_tokens=192)])
    monkeypatch.setattr(primary,'read_scores',lambda *args,**kwargs:({i:1 for i in range(520)},[],[],{'done':{}}))
    monkeypatch.setattr(primary,'read_review_scores',lambda *args,**kwargs:{i:1 for i in range(520)})
    rows=[dict(id='compli_dev::'+str(i),original_id=str(i),label=int(i%2==0),cohorts=['dev520']) for i in range(520)]
    data=lab/'v8-json-quote-replay-20261020/prepared-v1'
    put(data/'EVAL_INDEX.json',dict(rows=rows));put(data/'PREPARED.json',dict(eval_index_sha256=v9.sha(data/'EVAL_INDEX.json')))
    put(data/'REPLAY_PROTOCOL.json',dict(frozen=True))
    original=lab/'v5-35b-20261019/eval-inputs-v1'
    put(original/'INDEX.json',dict(source_sha256={str(source):v9.sha(source)}))
    put(original/'PREPARED.json',dict(index_sha256=v9.sha(original/'INDEX.json')))
    for arm in ('base','new'):
        folder=lab/'v8-json-quote-replay-20261020/evaluation-v8'/arm
        # Both veto hard TP0 and FP1; new additionally vetoes TP2.
        records=[dict(id=r['id'],admitted=True,score=-1 if i in ({0,1,2} if arm=='new' else {0,1}) else 1) for i,r in enumerate(rows)]
        lines(folder/'scores.jsonl',records)
        put(folder/'DONE.json',dict(complete=True,replay_protocol_sha256=v9.sha(data/'REPLAY_PROTOCOL.json'),scores_sha256=v9.sha(folder/'scores.jsonl')))
    return a


def test_veto_preserves_mechanical_hard_positive_and_reports_actual_tp_loss(tmp_path,monkeypatch):
    a=fixture(tmp_path,monkeypatch);v9.analyse(a)
    result=json.loads((a.out/'RESULTS.json').read_bytes())
    assert result['baseline']['tp']==104 and result['baseline']['fp']==104
    assert result['arms']['base']['removed_fp']==1 and result['arms']['base']['lost_tp']==0
    assert result['arms']['new']['removed_fp']==1 and result['arms']['new']['lost_tp']==1
    assert result['arms']['base']['metrics']['tp']==104


def test_final_score_gap_cannot_be_reported_as_full_max_pipeline(tmp_path,monkeypatch):
    a=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(primary,'read_review_scores',lambda *args,**kwargs:{i:1 for i in range(519)})
    with pytest.raises(ValueError,match='FULL_EXACT_COVERAGE_REQUIRED'):v9.analyse(a)
