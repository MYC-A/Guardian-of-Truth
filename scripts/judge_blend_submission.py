"""Sequential GPU workers: Qwen4B+LoRA, unchanged 35B review, fixed rank blend.

Always publish durable 35B/mechanical fallbacks. Blend only with N/N exact
coverage of BOTH scorers; one missing auxiliary score falls back globally.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge.ensemble import blend,read_secondary,validate
from guardian_truth.judge.decision import decide
from guardian_truth.judge.mechanical import analyze
from guardian_truth.judge.blind_review import select_ranking
from scripts import judge_submission as primary


def run(root,input_path,output,*,python=None,work=None,started_wall=None,config=None,watchdog=True):
    root=Path(root).resolve();cfg=primary.load_config(root,config);e=validate(cfg);clock=primary.Clock(started_wall)
    if watchdog:primary.start_watchdog(clock,output,float(cfg['watchdog_seconds']))
    rows=primary.read_input(input_path);ids=[r['id'] for r in rows];n=len(rows)
    findings=[analyze(r['prompt'],r['response'],bool(cfg.get('hard_unknown_identifier',False)),
        bounded_turn_shape=bool(cfg.get('bounded_turn_shape',False))) for r in rows]
    hard={i for i,f in enumerate(findings) if f.hard};primary.write_labels(output,ids,decide(n,hard,{},cfg['positive_rate']))
    if not n:return 0
    work=Path(work or tempfile.mkdtemp(prefix='guardian-blend-')).resolve();work.mkdir(parents=True,exist_ok=True)
    secondary_work=work/'secondary';secondary_work.mkdir(exist_ok=True)
    sec=dict(cfg,model_dir=e['model_dir'],review_mode='off',review_content='state_notes',review_ranking='complete',
        max_model_len=int(e.get('max_model_len',98304)),gpu_memory_utilization=float(e.get('gpu_memory_utilization',.85)),
        dtype='bfloat16',multimodal=False,max_num_seqs=16,max_num_batched_tokens=16384,
        engine_overrides={'enforce_eager':True},questions=['overall'],hint_modes=['off'],aggregate='primary')
    sec.pop('ensemble',None)
    command,env,scores_path,_=primary.prepare_stage(root,sec,rows,findings,clock,secondary_work,python)
    command[1]=str(root/'scripts/judge_lora_stage.py')
    stop_at=clock.wall_at(float(e['seconds']))
    command[command.index('--stop-at')+1]=repr(stop_at)
    adapter=Path(e['adapter_dir']);adapter=adapter if adapter.is_absolute() else root/adapter
    command+=['--adapter',str(adapter)]
    process=None;secondary_error=None;secondary_exit=None
    primary.log(clock,'secondary_start',rows=n,stop_at=stop_at,adapter_sha256=e['adapter_sha256'])
    try:
        if time.time()>=stop_at:raise TimeoutError('SECONDARY_BUDGET_ALREADY_EXPIRED')
        with (secondary_work/'stage.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env,cwd=secondary_work,start_new_session=True)
            while process.poll() is None and time.time()<stop_at:time.sleep(.2)
            secondary_exit=process.poll()
            if secondary_exit is None:secondary_error='SECONDARY_DEADLINE'
            elif secondary_exit!=0:secondary_error='SECONDARY_EXIT_'+str(secondary_exit)
    except Exception as error:secondary_error=type(error).__name__+':'+str(error)
    finally:
        gone=primary.kill_group(process,grace=3) if process is not None else True
    secondary=read_secondary(scores_path,n)
    primary.log(clock,'secondary_end',exact_rows=len(secondary),rows=n,group_gone=gone,error=secondary_error,exit_code=secondary_exit)
    secondary_log=secondary_work/'stage.log'
    if secondary_error and secondary_log.is_file():
        print('GUARDIAN SECONDARY LOG TAIL\n'+secondary_log.read_text(encoding='utf-8',errors='replace')[-2500:],file=sys.stderr,flush=True)
    # Retain the original primary supervisor's atomic checkpoints and deadline.
    main_work=work/'primary';main_cfg=dict(cfg);main_cfg.pop('ensemble',None)
    main_cfg_file=work/'primary-config.json';main_cfg_file.write_text(json.dumps(main_cfg),encoding='utf-8')
    primary_error=None
    try:
        primary.run(root,input_path,output,python=python,work=main_work,started_wall=clock.started_wall,
            config=main_cfg_file,watchdog=False)
    except Exception as error:primary_error=type(error).__name__+':'+str(error)
    main_path=main_work/'scores.jsonl'
    base=primary.read_scores(main_path,exact_only=True)[0]
    final=primary.read_review_scores(main_path,isolate_duplicates=True)
    base,_,_=select_ranking(base,final,list(range(n)),'max_exact')
    used,mode=blend(base,secondary,n);labels=decide(n,hard,used,float(cfg['positive_rate']))
    primary.write_labels(output,ids,labels)
    with (work/'decisions.jsonl').open('w',encoding='utf-8') as stream:
        for i in range(n):
            stream.write(json.dumps(dict(key=i,id=ids[i],label=labels[i],primary_score=base.get(i),
                secondary_score=secondary.get(i),ranked_by=used.get(i),hard=findings[i].hard,ranking=mode),ensure_ascii=False)+'\n')
    receipt=dict(rows=n,primary_exact_rows=len(base),secondary_exact_rows=len(secondary),ranking=mode,
        hard_rows=len(hard),positive_rate=cfg['positive_rate'],positives=sum(labels),seconds=clock.elapsed(),
        secondary_error=secondary_error,secondary_exit=secondary_exit,primary_error=primary_error,secondary_group_gone=gone)
    (work/'BLEND_DONE.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    primary.log(clock,'ensemble_final',**receipt)
    return 0


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--work-dir',type=Path);parser.add_argument('--config',type=Path)
    args=parser.parse_args();started=os.environ.get('GUARDIAN_STARTED_AT',repr(time.time()))
    code=run(ROOT,args.input,args.output,work=args.work_dir,config=args.config,started_wall=started)
    sys.stdout.flush();sys.stderr.flush();os._exit(code or 0)
