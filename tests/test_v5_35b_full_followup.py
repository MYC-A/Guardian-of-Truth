import json
import sys
import pytest
from scripts import v5_35b_full_followup as follow
from scripts import v5_35b_finish as finish
from scripts.v5_35b_common import BASE_REVISION


def test_already_complete_segment_never_starts_another_epoch(tmp_path,monkeypatch):
    prior=tmp_path/'resume-v2';prior.mkdir()
    (prior/'TRAINED.json').write_text(json.dumps(dict(epoch_complete=True,rows_done=1458)))
    for name in ('adapter','final'):
        (prior/name).mkdir();(prior/name/'proof.txt').write_text(name)
    monkeypatch.setattr(sys,'argv',['follow','--root',str(tmp_path)])
    monkeypatch.setattr(follow.subprocess,'check_output',lambda *a,**k:'0\n')
    monkeypatch.setattr(follow.os,'execv',lambda *a:pytest.fail('second epoch attempted'))
    follow.main()
    assert json.loads((tmp_path/'full-followup-v1/DONE.json').read_text())['no_second_epoch']
    assert (tmp_path/'train-full-v1/final/proof.txt').read_text()=='final'


def test_partial_segment_continues_saved_position_in_same_supervised_process(tmp_path,monkeypatch):
    prior=tmp_path/'resume-v2';prior.mkdir()
    (prior/'TRAINED.json').write_text(json.dumps(dict(epoch_complete=False,rows_done=832,optimizer_updates=52)))
    monkeypatch.setattr(sys,'argv',['follow','--root',str(tmp_path)])
    monkeypatch.setattr(follow.subprocess,'check_output',lambda *a,**k:'0\n')
    captured=[]
    def execv(py,args):
        captured.extend(args)
        raise RuntimeError('EXEC_REPLACED_FOR_TEST')
    monkeypatch.setattr(follow.os,'execv',execv)
    with pytest.raises(RuntimeError,match='EXEC_REPLACED_FOR_TEST'):follow.main()
    assert captured[captured.index('--resume')+1]==str(prior/'final')
    assert captured[captured.index('--total-budget-seconds')+1]=='57600'
    assert '--require-full-epoch' in captured


def test_full_evaluation_rejects_partial_training_before_any_gpu_call(tmp_path,monkeypatch):
    training=tmp_path/'training';training.mkdir();data=tmp_path/'data';data.mkdir()
    (training/'TRAINED.json').write_text(json.dumps(dict(complete=True,optimizer_updates=52,base_revision=BASE_REVISION,
        epoch_complete=False,rows_done=832)))
    for n in ('PREPARED.json','INDEX.json'):(data/n).write_text('{}')
    monkeypatch.setattr(sys,'argv',['finish','--training',str(training),'--data',str(data),'--model',str(tmp_path/'model'),
        '--manifest',str(tmp_path/'manifest'),'--runtime-python',sys.executable,'--out',str(tmp_path/'out'),
        '--training-program','own-full-program','--require-full-epoch'])
    monkeypatch.setattr(finish.subprocess,'run',lambda *a,**k:pytest.fail('unexpected GPU/subprocess call'))
    with pytest.raises(ValueError,match='FULL_EPOCH_REQUIRED'):finish.main()
    assert (tmp_path/'out/FAIL.json').exists()
