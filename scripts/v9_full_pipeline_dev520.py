"""Frozen best-profile control on dev520, then CPU-only application of V8 vetoes."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write,verify_model
from scripts.v5_valid46_pipeline import pipeline_config,bound_llm,metrics,BASELINE_CONFIG_SHA


def stage():
    import vllm
    from scripts import judge_stage
    original=bound_llm(vllm.LLM,None,os.environ['V9_GENERATION_AUDIT']);instances=[]
    class Captured(original):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);instances.append(self)
    vllm.LLM=Captured
    try:judge_stage.main()
    finally:
        for llm in instances:llm.llm_engine.engine_core.shutdown()
    sys.stdout.flush();sys.stderr.flush();os._exit(0)


def arm(a):
    from scripts import judge_submission as primary
    original=primary.prepare_stage
    def prepare(*args,**kwargs):
        command,env,scores,model=original(*args,**kwargs)
        command[1]=str(Path(__file__).resolve())
        env.update(V9_STAGE='1',V9_GENERATION_AUDIT=str(a.out/'generation_audit.jsonl'),
            VLLM_ALLOW_INSECURE_SERIALIZATION='1')
        return command,env,scores,model
    primary.prepare_stage=prepare
    code=primary.run(ROOT,a.out/'inputs.csv',a.out/'predictions.csv',work=a.out/'work',
        config=a.out/'config.json',started_wall=time.time(),watchdog=False)
    if code:raise RuntimeError('PRIMARY_EXIT:'+str(code))


def analyse(a):
    from scripts import judge_submission as primary
    from scripts.v7_evaluate import keep_accusation
    work=a.out/'work';scores,missing,inexact,events=primary.read_scores(work/'scores.jsonl',exact_only=True)
    final=primary.read_review_scores(work/'scores.jsonl',isolate_duplicates=True)
    decisions=read(work/'decisions.jsonl')
    if set(scores)!=set(range(520)) or set(final)!=set(range(520)) or missing or inexact:
        raise ValueError('FULL_EXACT_COVERAGE_REQUIRED_NO_FALLBACK_ACCEPTANCE')
    if len(decisions)!=520 or any(r['ranking']!='max_exact_overall_final' for r in decisions) or events.get('failed') or 'done' not in events:
        raise ValueError('BEST_PROFILE_MAX_DID_NOT_COMPLETE')
    audit=read(a.out/'generation_audit.jsonl')
    if not audit or any(r['adapter_applied'] for r in audit) or not any(r['max_tokens']>1 for r in audit):
        raise ValueError('CONTROL_OR_REVIEW_CALL_DRIFT')
    v8=a.lab/'v8-json-quote-replay-20261020';data=v8/'prepared-v1'
    frozen=json.loads((data/'PREPARED.json').read_bytes())
    if sha(data/'EVAL_INDEX.json')!=frozen['eval_index_sha256']:raise ValueError('GOLD_INDEX_DRIFT')
    metadata=[r for r in json.loads((data/'EVAL_INDEX.json').read_bytes())['rows'] if 'dev520' in r['cohorts']]
    original=a.lab/'v5-35b-20261019/eval-inputs-v1'
    original_meta=json.loads((original/'PREPARED.json').read_bytes())
    if sha(original/'INDEX.json')!=original_meta['index_sha256']:raise ValueError('ORIGINAL_SOURCE_INDEX_DRIFT')
    source=a.lab/'data/guardian-judge-eval-data-v1/compli_dev/inputs.csv'
    if json.loads((original/'INDEX.json').read_bytes())['source_sha256'][str(source)]!=sha(source):
        raise ValueError('ORIGINAL_DEV520_SOURCE_DRIFT')
    lookup={r['original_id']:r for r in metadata};gold={r['id']:r['label'] for r in metadata}
    inputs=list(csv.DictReader((a.out/'inputs.csv').open(encoding='utf-8',newline='')))
    rows=[lookup[r['id']] for r in inputs]
    if len(rows)!=520 or len(lookup)!=520 or any(d['id']!=r['id'] for d,r in zip(decisions,inputs)):
        raise ValueError('DECISION_OR_GOLD_JOIN')
    with (a.out/'predictions.csv').open(encoding='utf-8',newline='') as f:pred=list(csv.DictReader(f))
    if [r['id'] for r in pred]!=[r['id'] for r in inputs]:raise ValueError('PREDICTION_ORDER')
    before=[int(r['label']) for r in pred]
    result=dict(complete=True,rows=520,scope='best-profile 35B control plus fixed V8 verifier; no retraining',
        baseline=metrics(rows,gold,before),arms={},quota=.4,quota_refill=False,threshold=0,
        baseline_config_canonical_sha256=BASELINE_CONFIG_SHA,
        runtime_deviation='eager synchronous scheduling and LoRA-capable engine without active adapter',
        source_sha256=sha(Path(__file__)),inputs_sha256=sha(a.out/'inputs.csv'),scores_sha256=sha(work/'scores.jsonl'),
        independent_validation=False,human_reviewed=False,private_improvement_measured=False,production_promoted=False)
    protocol=sha(data/'REPLAY_PROTOCOL.json')
    for arm in ('base','new'):
        folder=v8/'evaluation-v8'/arm;receipt=json.loads((folder/'DONE.json').read_bytes())
        if not receipt['complete'] or receipt['replay_protocol_sha256']!=protocol or sha(folder/'scores.jsonl')!=receipt['scores_sha256']:
            raise ValueError('V8_FROZEN_SCORE_DRIFT')
        values={r['id']:r for r in read(folder/'scores.jsonl')}
        after=[int(bool(y) and (bool(d['hard']) or keep_accusation(values[r['id']]))) for y,d,r in zip(before,decisions,rows)]
        result['arms'][arm]=dict(metrics=metrics(rows,gold,after),
            removed_fp=sum(x and not y and gold[r['id']]==0 for r,x,y in zip(rows,before,after)),
            lost_tp=sum(x and not y and gold[r['id']]==1 for r,x,y in zip(rows,before,after)),
            v8_scores_sha256=receipt['scores_sha256'])
    write(a.out/'RESULTS.json',result)


def run(a):
    from scripts.v7_control import export
    a.out.mkdir(parents=True,exist_ok=False);active=None;started=time.monotonic()
    try:
        if time.time()>a.deadline-1600:raise TimeoutError('INSUFFICIENT_FULL_PROFILE_BUDGET')
        if subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()!='0':raise ValueError('GPU_BUSY')
        source=a.lab/'data/guardian-judge-eval-data-v1/compli_dev/inputs.csv'
        csv.field_size_limit(2**31-1)
        with source.open(encoding='utf-8',newline='') as f:rows=[{k:r[k] for k in ('id','prompt','response')} for r in csv.DictReader(f)]
        if len(rows)!=520 or len({r['id'] for r in rows})!=520:raise ValueError('DEV520_ID_COVERAGE')
        with (a.out/'inputs.csv').open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['id','prompt','response']);w.writeheader();w.writerows(rows)
        write(a.out/'config.json',pipeline_config(a.lab/'models/qwen36-awq'))
        write(a.out/'START.json',dict(before_inference=True,labels_read=False,rows=520,
            inputs_sha256=sha(a.out/'inputs.csv'),source_inputs_sha256=sha(source),
            config_sha256=sha(a.out/'config.json'),source_sha256=sha(Path(__file__)),gpu_deadline=a.deadline,
            baseline_profile='JUDGE_OPEN_REVIEW40',bounded_turn_shape=True,threshold=0,quota_refill=False,
            v8_pair_results_sha256=sha(a.lab/'v8-json-quote-replay-20261020/evaluation-v8/PAIR_RESULTS.json'),
            purpose='Check verifier value on actual open-review/MAX instead of overall-only pool',
            promotion=False,quality_retries=0))
        verify_model(a.lab/'models/qwen36-awq',a.lab/'v5-35b-20261019/BASE_MODEL_MANIFEST.json')
        command=[sys.executable,str(Path(__file__)),'arm','--lab',str(a.lab),'--out',str(a.out),'--deadline',str(a.deadline)]
        with (a.out/'pipeline.log').open('w',buffering=1) as log:
            active=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT,
                env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHON_DOTENV_DISABLED='1',PYTHONUNBUFFERED='1'))
            code=active.wait(timeout=max(1,a.deadline-90-time.time()))
        if code:raise RuntimeError('PIPELINE_FAILED:'+str(code))
        analyse(a)
        write(a.out/'DONE.json',dict(complete=True,seconds=time.monotonic()-started,results_sha256=sha(a.out/'RESULTS.json')))
    except Exception as e:
        write(a.out/'FAIL.json',dict(error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started));raise
    finally:
        if active is not None:
            try:os.killpg(active.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        export(a.out)


if __name__=='__main__':
    if os.environ.get('V9_STAGE')=='1':stage()
    else:
        p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','arm'])
        p.add_argument('--lab',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
        p.add_argument('--deadline',type=float,required=True);a=p.parse_args()
        run(a) if a.mode=='run' else arm(a)
