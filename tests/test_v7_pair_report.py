import json
from pathlib import Path
import pytest
from scripts.v5_35b_common import sha
from scripts.v7_pair_report import analyse
from scripts.v7_evaluate import analyse as analyse_three
from scripts.v7_evaluation_continue import verify_base

def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')

def jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(map(json.dumps,rows))+'\n',encoding='utf-8')

def make_fixture(tmp_path):
    data=tmp_path/'data';out=tmp_path/'out';lab=tmp_path/'lab';rows=[]
    for cohort,count in [('real191',191),('dev520',520),('valid46',46)]:
        for i in range(count):
            rows.append(dict(id=cohort+':'+str(i),original_id=cohort+'_'+str(i//3)+'::t'+str(i),
                group=cohort+'_'+str(i//3),label=int(i%3==0),cohorts=[cohort],hard=False))
    put(data/'EVAL_INDEX.json',dict(rows=rows))
    prepared=dict(eval_tokens_sha256='frozen-input',eval_index_sha256=sha(data/'EVAL_INDEX.json'))
    put(data/'PREPARED.json',prepared)
    put(data/'EVAL_PROTOCOL.json',dict(ids=[r['id'] for r in rows]))
    for arm in ('base','old','new'):
        folder=out/arm;values=[]
        for r in rows:
            i=int(r['id'].rsplit(':',1)[1]);positive=(i%2==0)
            if arm=='new' and i%4==2:positive=False
            admitted=i%17!=0
            values.append(dict(id=r['id'],arm=arm,repeat=0,admitted=admitted,score=(1 if positive else -1) if admitted else None,
                exact=admitted,review='same source review',score_input_sha256=r['id']))
        repeated=[dict(r,repeat=k) for k in (1,2) for r in values if r['id'].startswith('valid46:')]
        jsonl(folder/'scores.jsonl',values);jsonl(folder/'repeat_scores.jsonl',repeated)
        put(folder/'DONE.json',dict(complete=True,rows=757,arm=arm,input_sha256='frozen-input',
            eval_protocol_sha256=sha(data/'EVAL_PROTOCOL.json'),scores_sha256=sha(folder/'scores.jsonl'),
            repeat_scores_sha256=sha(folder/'repeat_scores.jsonl'),source_modules=100 if arm=='new' else 50,
            all_admitted_scores_exact=True,valid46_measurements=3))
        if arm!='base':put(folder/'ADAPTER_BINDING.json',[dict(complete=True,covered_modules=100 if arm=='new' else 50)])
    oldroot=lab/'v5-35b-20261019/finish-v6/paired-native'
    historical=[dict(id=r['id'],arm='base',score=float(1000-int(r['id'].rsplit(':',1)[1]))) for r in rows]
    jsonl(oldroot/'scores.jsonl',historical);put(oldroot/'WORKER_DONE.json',dict(scores_sha256=sha(oldroot/'scores.jsonl')))
    valid=[r for r in rows if 'valid46' in r['cohorts']]
    jsonl(lab/'v5-35b-20261019/pipeline-valid46-v4/base/work/decisions.jsonl',[
        dict(key=i,id=r['original_id'],hard=False,ranked_by=float(100-i)) for i,r in enumerate(valid)])
    return data,out,lab,prepared

def test_pair_report_agrees_with_three_arm_primary_metrics(tmp_path):
    data,out,lab,_=make_fixture(tmp_path)
    pair=analyse(data,out,lab)
    # The existing evaluator exposes analyse(data, out, lab), independently aggregating all three arms.
    three=analyse_three(data,out,lab)
    for c in ('real191','dev520','valid46'):
        for arm in ('base','new'):
            for metric in ('verifier','original_pool40_after_verifier','pool40_removed_fp','pool40_lost_tp'):
                assert pair['cohorts'][c]['arms'][arm][metric]==three['cohorts'][c]['arms'][arm][metric]
        assert pair['cohorts'][c]['lost_tp_vs_base']==three['cohorts'][c]['arms']['new']['lost_tp_vs_base']
        assert pair['cohorts'][c]['removed_fp_vs_base']==three['cohorts'][c]['arms']['new']['removed_fp_vs_base']
    assert pair['best_pipeline_valid46_pool70']['arms']['new']==three['best_pipeline_valid46_pool70']['arms']['new']
    assert pair['offline_gate']['passed']==three['offline_gate']['passed']
    assert pair['cohorts']['real191']['lost_tp_vs_base']>0
    assert pair['cohorts']['real191']['removed_fp_vs_base']>0

def test_completed_control_reuse_requires_matching_input_and_untouched_scores(tmp_path):
    data,out,_,prepared=make_fixture(tmp_path)
    verify_base(out/'base',prepared,sha(data/'EVAL_PROTOCOL.json'))
    with pytest.raises(ValueError,match='DIFFERENT_BASE'):
        verify_base(out/'base',dict(prepared,eval_tokens_sha256='other'),sha(data/'EVAL_PROTOCOL.json'))
    (out/'base/scores.jsonl').write_text('changed')
    with pytest.raises(ValueError,match='FILE_DRIFT'):verify_base(out/'base',prepared,sha(data/'EVAL_PROTOCOL.json'))
