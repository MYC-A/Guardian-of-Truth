import pytest
from scripts.judge35_submission import apply_complete


def test_complete_veto_protects_hard_unknown_and_does_not_refill():
    values=[dict(position=0,admitted=True,exact=True,score=-2),
            dict(position=1,admitted=True,exact=True,score=-2),
            dict(position=2,admitted=False,exact=False,score=None)]
    assert apply_complete([1,1,1,0],{0},values)==[1,0,1,0]


@pytest.mark.parametrize('values',[
    [dict(position=0,admitted=True,exact=True,score=-1)],
    [dict(position=0,admitted=False),dict(position=0,admitted=False)],
    [dict(position=0,admitted=True,exact=False,score=-1),dict(position=1,admitted=False)],
    [dict(position=0,admitted=True,exact=True,score=float('nan')),dict(position=1,admitted=False)]])
def test_partial_duplicate_or_inexact_cannot_change_baseline(values):
    with pytest.raises(ValueError,match='GLOBAL_BASELINE_FALLBACK'):
        apply_complete([1,1],set(),values)


@pytest.mark.parametrize('complete',[True,False])
def test_supervisor_publishes_only_complete_verification_preserving_duplicate_ids(tmp_path,monkeypatch,complete):
    import csv
    import hashlib
    import json
    from scripts import judge35_submission as m
    root=tmp_path/'root';root.mkdir();work=tmp_path/'work';output=tmp_path/'answer.csv'
    cfg=dict(m.primary.DEFAULTS,lora35_verifier=dict(adapter_dir='model/lora35_v7',stop_seconds=1560),review_mode='open')
    (root/'JUDGE_CONFIG.json').write_text(json.dumps(cfg))
    rows=[dict(id=x,prompt='source',response='turn') for x in ['duplicate','duplicate','last']]
    monkeypatch.setattr(m.primary,'read_input',lambda _:rows)
    monkeypatch.setattr(m,'system_block',lambda _:'explicit source policy sentence')
    def baseline(*args,**kwargs):
        w=kwargs['work'];w.mkdir(parents=True)
        d=[dict(key=i,id=r['id'],label=[1,0,1][i],hard=['rule'] if i==0 else [],ranking='max_exact_overall_final') for i,r in enumerate(rows)]
        (w/'decisions.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in d))
        text='<transcript>\nSYSTEM: policy\n</transcript>'
        (w/'primary-inputs-fixture.jsonl').write_text(''.join(json.dumps(dict(key=i,text=text,model_input_sha256=hashlib.sha256(text.encode()).hexdigest()))+'\n' for i in range(3)))
        m.primary.write_labels(output,[r['id'] for r in rows],[1,0,1])
    monkeypatch.setattr(m.primary,'run',baseline)
    monkeypatch.setattr(m.primary,'read_scores',lambda *a,**k:({0:1,1:0,2:2},0,0,{'done':{}}))
    monkeypatch.setattr(m.primary,'read_review_scores',lambda *a,**k:{0:1,1:0,2:2})
    class Process:
        def __init__(self,command,**kwargs):
            w=m.Path(command[command.index('--work')+1])
            rr=[dict(position=i,admitted=True,exact=True,score=-1) for i in ([0,2] if complete else [0])]
            raw=''.join(json.dumps(x)+'\n' for x in rr).encode();(w/'scores.jsonl').write_bytes(raw)
            (w/'DONE.json').write_text(json.dumps(dict(complete=True,rows=len(rr),scores_sha256=hashlib.sha256(raw).hexdigest())))
        def wait(self,timeout=None):return 0
    monkeypatch.setattr(m.subprocess,'Popen',Process)
    monkeypatch.setattr(m.primary,'kill_group',lambda *a,**k:True)
    assert m.run(root,tmp_path/'input.csv',output,work=work,watchdog=False)==0
    with output.open() as f:actual=list(csv.DictReader(f))
    assert [r['id'] for r in actual]==['duplicate','duplicate','last']
    assert [int(r['label']) for r in actual]==([1,0,0] if complete else [1,0,1])
    receipt=json.loads((work/'LORA35_DONE.json').read_bytes());assert receipt['applied'] is complete
