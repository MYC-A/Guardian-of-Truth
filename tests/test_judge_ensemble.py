import csv
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import zipfile
import pytest
from guardian_truth.judge.ensemble import blend,percentiles,read_secondary,validate
from guardian_truth.judge.decision import decide
from scripts import judge_blend_submission as wrapper
from scripts import judge_lora_stage
from scripts.build_judge_submission import build,REQUIRED
from scripts.build_platform_startup_probe import file_info
from guardian_truth.judge import ensemble

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'submission/JUDGE_BLEND40.json').read_bytes())


def test_midrank_blend_and_global_incomplete_fallback():
    assert percentiles({0:0,1:0,2:1,3:2},4)=={0:.375,1:.375,2:.75,3:1.0}
    p={0:5.,1:4.,2:3.,3:2.,4:1.};s={0:-8.,1:-9.,2:10.,3:9.,4:0.}
    used,mode=blend(p,s,5)
    assert mode=='rank_50_50' and decide(5,set(),used,.4)==[1,0,1,0,0]
    for missing in ({},{k:v for k,v in s.items() if k!=4},{**s,4:float('nan')}):
        assert blend(p,missing,5)==(p,'global_primary_fallback')
    assert decide(5,{2,3,4},p,.4)==[0,0,1,1,1]


def test_secondary_duplicate_invalid_and_torn_receipts(tmp_path):
    p=tmp_path/'scores.jsonl'
    p.write_text('\n'.join(json.dumps(r) for r in [dict(key=0,score=2,exact=True),
        dict(key=1,score=3,exact=True),dict(key=1,score=4,exact=True),
        dict(key=2,score=9,exact=False),dict(key=True,score=8,exact=True)])+'\n{"key":',encoding='utf8')
    assert read_secondary(p,3)=={0:2.}


def test_lora_worker_passes_adapter_on_probe_and_scores_without_hints(tmp_path):
    adapter=tmp_path/'adapter';adapter.mkdir();(adapter/'adapter_model.safetensors').write_bytes(b'fixture')
    source=tmp_path/'input.jsonl';target=tmp_path/'scores.jsonl';config=tmp_path/'cfg.json'
    source.write_text(json.dumps(dict(key=0,prompt='SOURCE',response='CURRENT',hints=['HINT_MUST_NOT_BE_USED']))+'\n')
    config.write_text(json.dumps(dict(max_model_len=98304,chunk=16)))
    class Tok:
        def encode(self,text,**kwargs):
            if text.strip().upper()=='YES':return [10]
            if text.strip().upper()=='NO':return [11]
            return list(text.encode())
        def apply_chat_template(self,messages,**kwargs):return '\n'.join(m['content'] for m in messages)+'\nASSISTANT'
    request=object();calls=[]
    class LLM:
        def __init__(self,**kwargs):assert kwargs['enable_lora'] and kwargs['max_lora_rank']==16
        def get_tokenizer(self):return Tok()
        def generate(self,prompts,params,**kwargs):
            assert kwargs['lora_request'] is request;calls.extend(prompts)
            out=[]
            for prompt in prompts:
                ids=prompt['prompt_token_ids'] if isinstance(prompt,dict) else Tok().encode(prompt)
                sample=SimpleNamespace(token_ids=[10],logprobs=[{10:SimpleNamespace(logprob=math.log(.8)),11:SimpleNamespace(logprob=math.log(.2))}])
                out.append(SimpleNamespace(prompt_token_ids=ids,outputs=[sample]))
            return out
    args=['worker','--model',str(tmp_path),'--adapter',str(adapter),'--input',str(source),'--output',str(target),'--config',str(config),'--stop-at','9999999999']
    fake={'vllm':SimpleNamespace(LLM=LLM,SamplingParams=lambda **kw:kw),
        'vllm.lora.request':SimpleNamespace(LoRARequest=lambda *a:request)}
    with patch.object(sys,'argv',args),patch.dict(sys.modules,fake),patch.object(judge_lora_stage,'engine_kwargs',return_value=({},[])),\
         patch.object(judge_lora_stage,'ADAPTER_SHA256',hashlib.sha256(b'fixture').hexdigest()):
        assert judge_lora_stage.main()==0
    assert len(calls)==2
    assert b'HINT_MUST_NOT_BE_USED' not in bytes(calls[1]['prompt_token_ids'])
    assert abs(read_secondary(target,1)[0]-math.log(4))<1e-12


def test_pins_and_exact_contract_are_mandatory():
    validate(CONFIG)
    for cfg in [{**CONFIG,'require_exact_scores':False},{**CONFIG,'review_ranking':'complete'},
                {**CONFIG,'ensemble':{**CONFIG['ensemble'],'base_revision':'other'}}]:
        with pytest.raises(ValueError):validate(cfg)


def test_public_entrypoint_dispatches_ensemble_config(tmp_path):
    (tmp_path/'scripts').mkdir();entry=tmp_path/'scripts/predict.py'
    entry.write_bytes((ROOT/'submission/predict_judge.py').read_bytes())
    (tmp_path/'JUDGE_CONFIG.json').write_text(json.dumps(CONFIG))
    spec=importlib.util.spec_from_file_location('blend_archive_predict',entry);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with patch.object(module,'bootstrap'),patch.object(wrapper,'run',return_value=0) as selected,\
         patch.object(wrapper.primary,'run',side_effect=AssertionError('WRONG_ENTRYPOINT')):
        assert module.main(['--input',str(tmp_path/'in.csv'),'--output',str(tmp_path/'out.csv')])==0
    assert selected.call_args.args[0]==tmp_path


def test_two_model_archive_contains_verified_adapter_and_runtime_code(tmp_path):
    model=tmp_path/'primary';model.mkdir();base=tmp_path/'base';base.mkdir();adapter=tmp_path/'adapter';adapter.mkdir()
    for root in (model,base):
        (root/'config.json').write_bytes(b'{}');(root/'model.safetensors').write_bytes(b'fixture weights')
    manifest=lambda root:[dict(path=f.name,size=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in sorted(root.iterdir())]
    primary_manifest=dict(repository=ensemble.PRIMARY_ID,revision=ensemble.PRIMARY_REVISION,files=manifest(model))
    hf=dict(repository=ensemble.BASE_ID,revision=ensemble.BASE_REVISION,files=[dict(path=r['path'],bytes=r['size'],algorithm='sha256',digest=r['sha256']) for r in manifest(base)])
    (base/'VERIFIED.json').write_text(json.dumps(hf))
    (adapter/'adapter_config.json').write_text(json.dumps(dict(r=16,lora_alpha=32,peft_type='LORA')))
    (adapter/'adapter_model.safetensors').write_bytes(b'fixture adapter')
    digest=hashlib.sha256(b'fixture adapter').hexdigest();cfg=json.loads(json.dumps(CONFIG));cfg['ensemble']['adapter_sha256']=digest
    config=tmp_path/'config.json';config.write_text(json.dumps(cfg));source=tmp_path/'source.zip';records={}
    with zipfile.ZipFile(source,'w') as z:
        for name in (*REQUIRED,'JUDGE_MANIFEST.json'):
            raw=json.dumps(primary_manifest).encode() if name=='JUDGE_MANIFEST.json' else b'fixture runtime'
            mode=0o644 if name.endswith('.json') else 0o755;z.writestr(file_info(name,mode),raw)
            records[name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),mode=mode)
        z.writestr(file_info('MANIFEST.json'),json.dumps(dict(files=records)).encode())
    with patch.object(ensemble,'ADAPTER_SHA256',digest),contextlib.redirect_stdout(io.StringIO()):
        result=build(source,hashlib.sha256(source.read_bytes()).hexdigest(),model,ensemble.PRIMARY_ID,ensemble.PRIMARY_REVISION,
            tmp_path/'blend.zip',judge_config=config,secondary_model_dir=base,adapter_dir=adapter,source_revision='f'*40)
    assert result['all_members_verified']
    with zipfile.ZipFile(tmp_path/'blend.zip') as z:
        assert z.read('model/judge4b-adapter/adapter_model.safetensors')==b'fixture adapter'
        assert 'src/guardian_truth/judge/ensemble.py' in z.namelist()
        assert 'scripts/judge_lora_stage.py' in z.namelist()
        assert json.loads(z.read('JUDGE_MANIFEST.json'))['secondary']['adapter']['sha256']==digest
        assert json.loads(z.read('JUDGE_CONFIG.json'))['bounded_turn_shape'] is True


@pytest.mark.parametrize('complete',[True,False])
@pytest.mark.parametrize('file_format',['csv','parquet'])
def test_sequential_wrapper_uses_actual_auxiliary_scores_and_preserves_ids(tmp_path,complete,file_format):
    p=tmp_path/'input.csv';out=tmp_path/('output.'+file_format);cfg=tmp_path/'cfg.json';cfg.write_text(json.dumps(CONFIG))
    ids=['duplicate','duplicate','quote"id','unicode\u2028id','last']
    with p.open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['id','prompt','response','label']);w.writeheader()
        for key in ids:w.writerow(dict(id=key,prompt='\u27e6SYSTEM\u27e7\nBe helpful.\n\u27e6USER\u27e7\nHi',
            response='\u27e6ASSISTANT\u27e7\nHi',label='MUST_NOT_ENTER_STAGE'))
    if file_format=='parquet':
        import pandas as pd
        frame=pd.read_csv(p,keep_default_na=False);p=tmp_path/'input.parquet';frame.to_parquet(p,index=False)
    auxiliary=[-8.,-9.,10.,9.,0.]
    def child(command,**kwargs):
        source=Path(command[command.index('--input')+1]).read_text(encoding='utf8')
        assert 'MUST_NOT_ENTER_STAGE' not in source
        assert command[1].endswith('judge_lora_stage.py') and '--adapter' in command
        scores=Path(command[command.index('--output')+1]);scores.write_text(''.join(json.dumps(dict(key=i,score=s,exact=True))+'\n'
            for i,s in enumerate(auxiliary) if complete or i!=4),encoding='utf8')
        return SimpleNamespace(poll=lambda:0)
    def main_run(root,input_path,output,**kwargs):
        work=Path(kwargs['work']);work.mkdir();(work/'scores.jsonl').write_text(''.join(json.dumps(dict(key=i,score=5.-i,exact=True))+'\n' for i in range(5)))
        assert kwargs['watchdog'] is False
        wrapper.primary.write_labels(output,ids,[1,1,0,0,0])
    with patch.object(wrapper.subprocess,'Popen',side_effect=child),patch.object(wrapper.primary,'kill_group',return_value=True),\
         patch.object(wrapper.primary,'run',side_effect=main_run):
        wrapper.run(tmp_path,p,out,work=tmp_path/'work',config=cfg,watchdog=False)
    if file_format=='parquet':rows=pd.read_parquet(out).to_dict('records')
    else:
        with out.open(encoding='utf8',newline='') as f:rows=list(csv.DictReader(f))
    assert [r['id'] for r in rows]==ids
    assert [int(r['label']) for r in rows]==([1,0,1,0,0] if complete else [1,1,0,0,0])
    done=json.loads((tmp_path/'work/BLEND_DONE.json').read_bytes())
    assert done['ranking']==('rank_50_50' if complete else 'global_primary_fallback')
