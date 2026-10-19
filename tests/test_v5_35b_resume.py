import copy
import random
import pytest
from scripts.v5_35b_common import BASE_REVISION
from scripts.v5_35b_resume import validate_resume, admit_speed_probe, interrupted_resume_source


def fixture():
    order=list(range(1458));random.Random(20261019).shuffle(order)
    meta=dict(base_revision=BASE_REVISION,gate_sha256='gate',train_tokens_sha256='tokens',layers=8,shared=True,
        backend='AWQ_TORCH',rank=16,alpha=32,dropout=.05,learning_rate=2e-5,effective_batch=16,rows_done=480,steps=30)
    state=dict(order=order,rows_done=480,steps=30,optimizer=dict(state={i:dict(step=30) for i in range(100)}))
    return meta,state


def test_committed_resume_position_and_optimizer_are_required():
    meta,state=fixture()
    validate_resume(meta,dict(train_tokens_sha256='tokens'),state,'gate')
    for mutation in ('order','optimizer','step','recipe'):
        m,s=copy.deepcopy(meta),copy.deepcopy(state)
        if mutation=='order':s['order'][0],s['order'][1]=s['order'][1],s['order'][0]
        elif mutation=='optimizer':s['optimizer']['state'].pop(0)
        elif mutation=='step':s['optimizer']['state'][0]['step']=0
        else:m['learning_rate']=1e-4
        with pytest.raises(ValueError):validate_resume(m,dict(train_tokens_sha256='tokens'),s,'gate')


def test_numeric_admission_requires_reference_control_hard_caps_and_same_rng():
    control=dict(post_dropout_rng_equal=True,score_abs_delta=0.,loss_abs_delta=0.,gradient_relative_l2=.001,
                 worst_tensor_gradient_relative_l2=.001,max_gradient_abs_delta=1e-5)
    probe=dict(baseline_repeat_control=control,compiled_comparison=copy.deepcopy(control))
    assert admit_speed_probe(probe)
    for field,value in [('post_dropout_rng_equal',False),('score_abs_delta',.01),('gradient_relative_l2',.006),
                        ('worst_tensor_gradient_relative_l2',.03),('max_gradient_abs_delta',1e-3)]:
        bad=copy.deepcopy(probe);bad['compiled_comparison'][field]=value
        assert not admit_speed_probe(bad)
    bad=copy.deepcopy(probe);bad['baseline_repeat_control']['gradient_relative_l2']=0.
    assert not admit_speed_probe(bad)


def test_interruption_recovery_binds_checkpoint_log_and_spent_time(tmp_path):
    import json
    from scripts.v5_35b_common import sha
    parent=tmp_path/'interrupted';cp=parent/'checkpoint-0070';cp.mkdir(parents=True)
    (cp/'state.pt').write_bytes(b'own checkpoint bytes')
    logs=[dict(step=70,rows_done=1120,seconds=41000.),dict(step=72,rows_done=1152,seconds=42000.)]
    log=parent/'training.jsonl';log.write_text(''.join(json.dumps(x)+'\n' for x in logs))
    gate=parent/'SPEED_GATE.json';gate.write_text(json.dumps(dict(compiled_accepted=True)))
    meta=dict(steps=70,rows_done=1120,adapter_sha256='adapter',compiled_awq_dequant=True,speed_gate_sha256=sha(gate))
    rec=dict(kind='INTERRUPTED_VERIFIED_CHECKPOINT',complete=False,checkpoint_complete=True,source_checkpoint=str(cp),
        adapter_sha256='adapter',state_sha256=sha(cp/'state.pt'),training_log_sha256=sha(log),steps=70,rows_done=1120,
        latest_logged_progress=logs[-1],interrupted_batch_allowance_seconds=600,accounted_training_seconds=42600.)
    record=tmp_path/'recovery.json';record.write_text(json.dumps(rec))
    got=interrupted_resume_source(cp,record,meta)
    assert got['rows_done']==1120 and got['training_seconds']==42600. and not got['epoch_complete']
    assert not (parent/'TRAINED.json').exists()
    rec['accounted_training_seconds']=0;record.write_text(json.dumps(rec))
    with pytest.raises(ValueError,match='TIME_DRIFT'):interrupted_resume_source(cp,record,meta)
    rec['accounted_training_seconds']=42600.;record.write_text(json.dumps(rec));log.write_text('{}\n')
    with pytest.raises(ValueError,match='LOG_DRIFT'):interrupted_resume_source(cp,record,meta)
