"""Frozen-review technical replay. Only source admission changes; gold stays on CPU."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write,BASE_REVISION,verify_model
from scripts.v5_valid46_pipeline import bound_llm
from scripts.v8_quote_contract import admit_review

def dump(path,rows):
    with path.open('w',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=True)+'\n')

def prepare(a):
    a.out.mkdir(exist_ok=False);v7=a.lab/'v7-workflow-20261020';olddata=v7/'prepared-v1';source=v7/'evaluation-v3'
    original=json.loads((olddata/'PREPARED.json').read_bytes());protocol=json.loads((olddata/'EVAL_PROTOCOL.json').read_bytes())
    if sha(olddata/'eval_tokens.jsonl')!=original['eval_tokens_sha256']:raise ValueError('ORIGINAL_INPUT_DRIFT')
    if sha(olddata/'EVAL_INDEX.json')!=original['eval_index_sha256']:raise ValueError('GOLD_FILE_DRIFT')
    # Gold is copied unchanged for later CPU analysis, never parsed during preparation.
    for name in ('PREPARED.json','EVAL_INDEX.json','EVAL_PROTOCOL.json'):shutil.copy2(olddata/name,a.out/name)
    from transformers import AutoTokenizer
    tok=AutoTokenizer.from_pretrained(a.lab/'models/qwen36-awq',local_files_only=True)
    selection=set(protocol['ids']);inputs=[r for r in read(olddata/'eval_tokens.jsonl') if r['id'] in selection]
    if len(inputs)!=757:raise ValueError('REPLAY_ROW_SELECTION')
    receipts={};counts={};files={}
    for arm in ('base','new'):
        receipt=json.loads((source/arm/'DONE.json').read_bytes())
        if not receipt['complete'] or receipt['rows']!=757 or receipt['input_sha256']!=original['eval_tokens_sha256']:
            raise ValueError('SOURCE_ARM_INCOMPLETE')
        if sha(source/arm/'scores.jsonl')!=receipt['scores_sha256']:raise ValueError('SAVED_REVIEW_DRIFT')
        saved={r['id']:r for r in read(source/arm/'scores.jsonl')};rows=[]
        if set(saved)!=selection:raise ValueError('SAVED_REVIEW_IDS')
        for r in inputs:
            old=saved[r['id']]
            if old['input_sha256']!=r['text_sha256']:raise ValueError('REVIEW_SOURCE_PREFIX_DRIFT')
            admitted,status,support=admit_review(old['review'],r['source_policy'],old['status']=='TRUNCATED')
            if old['admitted'] and not admitted:raise ValueError('EXISTING_SOURCE_SUPPORT_WAS_LOST')
            ids=[]
            if admitted:
                text=tok.decode(r['ids'],skip_special_tokens=False)+old['review'].strip()+'\nVerdict:'
                ids=tok.encode(text,add_special_tokens=False)
                if ids[:len(r['ids'])]!=r['ids'] or len(ids)>=49152:raise ValueError('REPLAY_PREFIX_OR_CAP')
            rows.append(dict(id=r['id'],ids=ids,tokens=len(ids),review=old['review'],admitted=admitted,
                status=status,source_support=support,old_status=old['status'],input_sha256=r['text_sha256'],
                score_input_sha256=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest() if ids else None))
        dump(a.out/(arm+'_tokens.jsonl'),rows);files[arm]=sha(a.out/(arm+'_tokens.jsonl'));receipts[arm]=receipt
        counts[arm]=dict(rows=len(rows),previously_admitted=sum(saved[r['id']]['admitted'] for r in rows),
            admitted=sum(r['admitted'] for r in rows),statuses=dict(Counter(r['status'] for r in rows)))
    write(a.out/'REPLAY_PROTOCOL.json',dict(complete=True,rows=757,source_prefix_sha256=original['eval_tokens_sha256'],
        arm_tokens_sha256=files,source_arm_done_sha256={arm:sha(source/arm/'DONE.json') for arm in receipts},
        source_review_scores_sha256={arm:r['scores_sha256'] for arm,r in receipts.items()},
        quote_contract_sha256=sha(ROOT/'scripts/v8_quote_contract.py'),worker_sha256=sha(Path(__file__)),
        source_revision='technical correction after initial quality results; exploratory only',counts=counts,
        reviews_frozen=True,review_regenerated=False,all_admitted_scores_recomputed=True,
        no_score_result_cache=True,threshold=0,threshold_search=False,quota_refill=False,
        fixed_review_valid46_exact_score_measurements=3,original_generation_stability_not_remeasured=True,
        human_reviewed=False,source_support_not_semantic_proof=True,gold_parsed_during_preparation=False))

def worker(a):
    protocol=json.loads((a.data/'REPLAY_PROTOCOL.json').read_bytes());original=json.loads((a.data/'PREPARED.json').read_bytes())
    if sha(a.data/(a.arm+'_tokens.jsonl'))!=protocol['arm_tokens_sha256'][a.arm]:raise ValueError('REPLAY_INPUT_DRIFT')
    if sha(Path(__file__))!=protocol['worker_sha256'] or sha(ROOT/'scripts/v8_quote_contract.py')!=protocol['quote_contract_sha256']:
        raise ValueError('FROZEN_REPLAY_CODE_DRIFT')
    rows=read(a.data/(a.arm+'_tokens.jsonl'))
    allowed={'id','ids','tokens','review','admitted','status','source_support','old_status','input_sha256','score_input_sha256'}
    if len(rows)!=757 or any(set(r)!=allowed for r in rows):raise ValueError('WORKER_SCHEMA_OR_GOLD_LEAK')
    adapter=None;expected=50
    if a.arm=='new':
        source=a.lab/'v7-workflow-20261020/training-v2/layers16';meta=json.loads((source/'TRAINED.json').read_bytes());adapter=source/'adapter'
        if not meta['epoch_complete'] or meta['rows_done']!=224 or meta['base_revision']!=BASE_REVISION or sha(adapter/'adapter_model.safetensors')!=meta['adapter_sha256']:
            raise ValueError('TRAINED_ADAPTER_DRIFT')
        expected=meta['source_modules']
    verify_model(a.lab/'models/qwen36-awq',a.lab/'v5-35b-20261019/BASE_MODEL_MANIFEST.json')
    from vllm import LLM,SamplingParams
    from vllm.lora.request import LoRARequest
    from scripts.judge_stage import answer_ids,answer_score,engine_kwargs,probe
    cfg=json.loads((ROOT/'submission/JUDGE_OPEN_REVIEW40.json').read_bytes())
    cfg.update(max_model_len=49152,gpu_memory_utilization=.85,max_num_seqs=16,max_num_batched_tokens=8192,
        dtype='bfloat16',multimodal=True,enable_prefix_caching=True,engine_overrides=dict(enforce_eager=True,async_scheduling=False))
    kwargs,_=engine_kwargs(str(a.lab/'models/qwen36-awq'),cfg)
    request=None if adapter is None else LoRARequest('v8-fixed-review-new',1,str(adapter))
    llm=bound_llm(LLM,request,a.out/'generation_audit.jsonl',binding_adapter=adapter,expected_source_modules=expected)(**kwargs)
    yes,no=answer_ids(llm.get_tokenizer())
    if sorted(yes)!=original['answer_ids']['yes'] or sorted(no)!=original['answer_ids']['no']:raise ValueError('ANSWER_TOKEN_DRIFT')
    params=SamplingParams(temperature=1,top_p=1,max_tokens=1,logprobs=20,seed=0,allowed_token_ids=sorted(yes|no))
    exact,info=probe(llm,llm.get_tokenizer(),params,yes,no)
    if exact is not True:raise ValueError('EXACT_SCORE_PROBE')
    write(a.out/'PROBE.json',dict(exact=True,info=info))
    started=time.monotonic()
    def score_batch(batch,rep):
        if time.time()>a.deadline:raise TimeoutError('GPU_REPLAY_DEADLINE')
        accepted=[r for r in batch if r['admitted']]
        outputs=llm.generate([dict(prompt_token_ids=r['ids']) for r in accepted],params,use_tqdm=False) if accepted else []
        if len(outputs)!=len(accepted):raise ValueError('FINAL_SCORE_COUNT')
        scores={}
        for r,o in zip(accepted,outputs):
            value,exact=answer_score(o,yes,no)
            if not exact or value is None or not math.isfinite(value) or list(o.prompt_token_ids)!=r['ids']:raise ValueError('INEXACT_OR_TOKEN_DRIFT')
            scores[r['id']]=value
        return [dict(id=r['id'],arm=a.arm,repeat=rep,admitted=r['admitted'],status=r['status'],review=r['review'],
            source_support=r['source_support'],old_status=r['old_status'],score=scores.get(r['id']),exact=r['id'] in scores,
            input_sha256=r['input_sha256'],score_input_sha256=r['score_input_sha256']) for r in batch]
    try:
        with (a.out/'scores.jsonl').open('w',buffering=1) as f:
            for offset in range(0,len(rows),16):
                for r in score_batch(rows[offset:offset+16],0):f.write(json.dumps(r)+'\n')
                write(a.out/'PROGRESS.json',dict(rows_done=min(offset+16,len(rows)),rows_total=len(rows),arm=a.arm,seconds=time.monotonic()-started))
        valid=set(json.loads((a.data/'EVAL_PROTOCOL.json').read_bytes())['valid46_ids']);repeated=[r for r in rows if r['id'] in valid]
        if len(repeated)!=46:raise ValueError('REPEAT_IDENTITY')
        with (a.out/'repeat_scores.jsonl').open('w',buffering=1) as f:
            for rep in (1,2):
                for offset in range(0,len(repeated),16):
                    for r in score_batch(repeated[offset:offset+16],rep):f.write(json.dumps(r)+'\n')
        write(a.out/'DONE.json',dict(complete=True,rows=len(rows),arm=a.arm,input_sha256=protocol['source_prefix_sha256'],
            scores_sha256=sha(a.out/'scores.jsonl'),repeat_scores_sha256=sha(a.out/'repeat_scores.jsonl'),source_modules=expected,
            adapter_sha256=sha(adapter/'adapter_model.safetensors') if adapter else None,seconds=time.monotonic()-started,
            all_admitted_scores_exact=True,valid46_measurements=3,apc=True,result_cache=False,
            review_frozen=True,scope='fixed-review source-admission correction, exact final rescoring only',
            replay_protocol_sha256=sha(a.data/'REPLAY_PROTOCOL.json')))
    finally:llm.llm_engine.engine_core.shutdown()
    sys.stdout.flush();sys.stderr.flush();os._exit(0)

def parent(a):
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.mkdir(exist_ok=False);active=None;started=time.monotonic()
    from scripts.v7_control import export
    def stop(_sig,_frame):
        if active is not None and active.poll() is None:
            os.killpg(active.pid,signal.SIGTERM)
            try:active.wait(timeout=90)
            except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
        raise RuntimeError('REPLAY_SUPERVISED_STOP')
    signal.signal(signal.SIGTERM,stop)
    try:
        old=a.lab/'v7-workflow-20261020/evaluation-v3'
        while not ((old/'DONE.json').exists() or (old/'FAIL.json').exists()):
            if time.time()>a.deadline-900:raise TimeoutError('PRIOR_GPU_WORK_WAIT')
            time.sleep(10)
        # A finished/failed predecessor may leave its native engine behind.
        # Ownership is proven by its own log PID, exact cwd and process name.
        released=[];oldcode=a.lab/'v7-workflow-20261020/code-eval-extended-v3'
        for name in ('new.log','old.log'):
            logfile=old/name
            if not logfile.exists():continue
            for pid in set(map(int,re.findall(r'EngineCore pid=(\d+)',logfile.read_text()))):
                proc=Path('/proc')/str(pid)
                if not proc.exists():continue
                try:
                    owned=(proc/'cwd').resolve()==oldcode and (proc/'comm').read_text().strip().startswith('VLLM::Engine')
                except (OSError,FileNotFoundError):continue
                if owned:os.kill(pid,signal.SIGTERM);released.append(pid)
        write(a.out/'PREDECESSOR_RELEASE.json',dict(predecessor_finished=True,own_engine_term_pids=released))
        while subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()!='0':
            if time.time()>a.deadline-900:raise TimeoutError('GPU_RELEASE_WAIT')
            time.sleep(3)
        data=a.out.parent/'prepared-v1'
        prepare(type('PrepareArgs',(),dict(out=data,lab=a.lab))())
        write(a.out/'START.json',dict(source_sha256=sha(Path(__file__)),gpu_deadline=a.deadline,
            replay_protocol_sha256=sha(data/'REPLAY_PROTOCOL.json'),reviews_frozen=True,arm_order=['base','new'],
            labels_not_used_to_choose_correction=True,scope='technical replay after initial failed quality experiment'))
        for arm in ('base','new'):
            folder=a.out/arm;folder.mkdir()
            command=[sys.executable,str(Path(__file__)),'worker','--lab',str(a.lab),'--data',str(data),
                '--out',str(folder),'--arm',arm,'--deadline',str(a.deadline-180)]
            with (a.out/(arm+'.log')).open('w',buffering=1) as log:
                active=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT,
                    env=dict(os.environ,VLLM_ALLOW_INSECURE_SERIALIZATION='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUNBUFFERED='1'))
                try:code=active.wait(timeout=max(1,a.deadline-180-time.time())+90)
                except subprocess.TimeoutExpired:stop(None,None)
                process_id=active.pid;active=None
            if code:
                try:os.killpg(process_id,signal.SIGTERM)
                except ProcessLookupError:pass
                raise RuntimeError('REPLAY_ARM_FAILED:'+arm+':'+str(code))
        from scripts.v7_pair_report import analyse
        result=analyse(data,a.out,a.lab)
        result.update(scope='fixed saved reviews; JSON-source validation correction and exact rescoring',
            new_generation_run=False,review_generation_noise_remeasured=False,
            replay_protocol_sha256=sha(data/'REPLAY_PROTOCOL.json'),
            correction_selected_by_source_format_not_quality_threshold=True)
        write(a.out/'PAIR_RESULTS.json',result)
        write(a.out/'DONE.json',dict(complete=True,seconds=time.monotonic()-started,results_sha256=sha(a.out/'PAIR_RESULTS.json'),gate_passed=result['offline_gate']['passed']))
    except Exception as e:
        write(a.out/'FAIL.json',dict(error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started));raise
    finally:
        export(a.out)
        data=a.out.parent/'prepared-v1'
        if data.exists():
            archive=a.out.parent/'data-export.tar.gz'
            with tarfile.open(archive,'w:gz',compresslevel=3) as t:t.add(data,arcname='prepared-v1')
            write(a.out.parent/'data-export.INDEX.json',dict(name=archive.name,bytes=archive.stat().st_size,sha256=sha(archive)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['worker','parent'])
    p.add_argument('--lab',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--data',type=Path);p.add_argument('--arm',choices=['base','new']);p.add_argument('--deadline',type=float,required=True)
    a=p.parse_args();worker(a) if a.mode=='worker' else parent(a)
