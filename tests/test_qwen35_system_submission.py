import csv
import json
from pathlib import Path
import time

import pandas as pd
import pytest

from scripts import qwen35_b2_runner as runner
from scripts import qwen35_system_adapter as adapter

def inputs(path):
    rows=[dict(id=i,prompt='policy\n'+('x'*140000 if n==2 else 'context'),response=str(n),label=99)
          for n,i in enumerate([' same ',' same ','1.0','a,"b'])]
    pd.DataFrame(rows).to_csv(path,index=False)
    return rows

class Client:
    completion_http=preflight_http=0
    model=adapter.MODEL

def predictor(row,client,layers,**kwargs):
    assert set(row)=={'id','prompt','response'}
    assert row['id'].startswith('row') and kwargs['model']==adapter.MODEL
    # Completion order differs deliberately from input order.
    time.sleep(.01*(3-int(row['response'])))
    return dict(id=row['id'],binary=int(row['response'])%2,owner='A_adm2')

@pytest.mark.parametrize('suffix',['.csv','.parquet'])
def test_order_duplicates_large_fields_no_gold(suffix,tmp_path):
    path=tmp_path/'in.csv';rows=inputs(path);out=tmp_path/('out'+suffix)
    summary=runner.run(tmp_path/'archive',path,out,work_dir=tmp_path/'work',client=Client(),predictor=predictor)
    actual=pd.read_parquet(out) if suffix=='.parquet' else pd.read_csv(out,dtype={'id':str},keep_default_na=False)
    assert actual['id'].tolist()==[r['id'] for r in rows]
    assert actual['label'].tolist()==[0,1,0,1]
    assert summary['completed']==4 and summary['default_zero_rows']==0
    assert Path(str(out)+'.run-manifest.json').is_file()

def test_initial_binary_file_exists_before_server_failure(tmp_path):
    path=tmp_path/'in.csv';inputs(path);out=tmp_path/'out.csv'
    class Dead:
        def __init__(self,*a,**kw):pass
        def __enter__(self):
            assert pd.read_csv(out)['label'].tolist()==[0,0,0,0]
            raise RuntimeError('controlled server failure')
        def __exit__(self,*a):pass
    summary=runner.run(tmp_path/'archive',path,out,work_dir=tmp_path/'work',server_class=Dead)
    assert summary['default_zero_rows']==4 and summary['unprocessed']==4
    assert (tmp_path/'work/INFERENCE_FAILURE.json').is_file()

def test_expired_budget_still_outputs_every_row(tmp_path):
    path=tmp_path/'in.csv';inputs(path);out=tmp_path/'out.csv'
    summary=runner.run(tmp_path/'archive',path,out,work_dir=tmp_path/'work',duration=.01,client=Client(),predictor=predictor)
    assert len(pd.read_csv(out))==4 and summary['unprocessed']==4

def test_bad_row_does_not_erase_other_results(tmp_path):
    path=tmp_path/'in.csv';inputs(path);out=tmp_path/'out.csv'
    def one_failure(row,*args,**kw):
        if row['response']=='0':raise ValueError('controlled row exception')
        return predictor(row,*args,**kw)
    summary=runner.run(tmp_path/'archive',path,out,work_dir=tmp_path/'work',client=Client(),predictor=one_failure)
    assert pd.read_csv(out)['label'].tolist()==[0,1,0,1]
    assert summary['default_zero_rows']==1

def test_output_checkpoint_cannot_overwrite_foreign_file(tmp_path):
    rows=[dict(id='same')];out=tmp_path/'out.csv'
    checksum=runner.publish(out,rows,[0]);out.write_text('foreign',encoding='utf-8')
    with pytest.raises(ValueError,match='ANOTHER_WRITER'):runner.publish(out,rows,[1],checksum)
    assert out.read_text()=='foreign'
    with pytest.raises(FileExistsError):runner.publish(out,rows,[1])

def test_empty_input_does_not_start_gpu(tmp_path):
    path=tmp_path/'in.csv';pd.DataFrame(columns=['id','prompt','response']).to_csv(path,index=False)
    class Forbidden:
        def __init__(self,*a,**kw):pytest.fail('empty input must not start server')
    summary=runner.run(tmp_path/'archive',path,tmp_path/'out.csv',work_dir=tmp_path/'work',server_class=Forbidden)
    assert summary['rows']==0

def test_command_keeps_host_runtime_and_safe_cache_dtype(tmp_path):
    server=adapter.OwnedVllmServer('/host/conda/bin/python',tmp_path/adapter.REVISION,tmp_path,32768,32,
        deadline=time.monotonic()+60,asset_manifest=tmp_path/'manifest.json')
    command=server.command()
    assert command[0]=='/host/conda/bin/python'
    assert '--language-model-only' in command and '--enforce-eager' not in command
    assert command[command.index('--max-num-batched-tokens')+1]=='8192'
    assert command[command.index('--max-num-seqs')+1]=='32'
    assert command[command.index('--kv-cache-dtype')+1]=='auto'
    assert json.loads(command[command.index('--structured-outputs-config')+1])==dict(backend='xgrammar',disable_any_whitespace=True)

def test_native_request_schema_is_unchanged_except_model():
    from scripts.qwen_vllm_adapter import prepare_wire,MODEL
    original=dict(model=MODEL,messages=[dict(role='system',content='policy'),dict(role='user',content='input')],
                  temperature=0,max_tokens=700,response_format=dict(type='json_object'))
    before,_=prepare_wire(original,MODEL)
    request=dict(original,model=adapter.MODEL)
    after,_=adapter.prepare_wire(request,adapter.MODEL)
    after['model']=MODEL
    assert before==after

def test_cleanup_restores_handlers_even_when_child_cleanup_fails(tmp_path,monkeypatch):
    server=adapter.OwnedVllmServer('python',tmp_path/adapter.REVISION,tmp_path,32768,32,
        deadline=time.monotonic()+60,asset_manifest=tmp_path/'manifest.json')
    server.process=object();server.cleanup_mode='unreaped_leader'
    monkeypatch.setattr(adapter,'cleanup_child',lambda *a:(_ for _ in ()).throw(RuntimeError('controlled cleanup')))
    with pytest.raises(RuntimeError,match='controlled cleanup'):server.__exit__()
    assert json.loads((tmp_path/'cleanup.json').read_text())['error']=='RuntimeError'
