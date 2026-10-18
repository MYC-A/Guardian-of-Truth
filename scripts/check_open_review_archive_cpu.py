"""Extracted predict -> supervisor -> stage -> MAX .40 -> Parquet; fake model only.

Usage: python check_open_review_archive_cpu.py EXTRACTED_ROOT FIXTURE_REPO
Linux bootstrap and POSIX process transport are bypassed on the CPU host. No
weights, model quality or target-GPU runtime are exercised by this harness.
"""
import contextlib
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import sys
from unittest.mock import patch

root,repo=map(Path,sys.argv[1:3])
sys.path[:0]=[str(root/'src'),str(root)]
spec=importlib.util.spec_from_file_location('archive_predict',root/'scripts/predict.py')
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
entry.bootstrap=lambda *args:None
import scripts.judge_submission as supervisor
import scripts.judge_stage as stage
from guardian_truth.judge import blind_review as br
assert Path(supervisor.__file__).resolve().is_relative_to(root)
assert Path(stage.__file__).resolve().is_relative_to(root)
spec=importlib.util.spec_from_file_location('cpu_fixture_helpers',repo/'tests/test_judge_v3.py')
fixtures=importlib.util.module_from_spec(spec);sys.modules[spec.name]=fixtures;spec.loader.exec_module(fixtures)
source=root/'open40_input.csv'
ids=[' 001','duplicate','duplicate','a,b']+['row_'+str(i) for i in range(4,20)]
with source.open('w',encoding='utf-8',newline='') as f:
    w=csv.writer(f);w.writerow(['id','prompt','response','label','explanation'])
    for i,ident in enumerate(ids):
        w.writerow([ident,fixtures.CATALOG+'\nROW_AUDIT_%d \u2028 \u2029 \u0085'%i,
                    fixtures.GOOD+'\nCURRENT_RESPONSE_'+str(i),'GOLD_SECRET','GOLD_REASON'])


def run(case):
    sent={};mods=fixtures.fake_vllm(sent);Base=mods['vllm'].LLM
    work=root/case; output=root/(case+'.parquet')
    class Engine(Base):
        def generate(self,prompts,params,use_tqdm=False):
            if params.max_tokens!=1:
                assert not hasattr(params,'allowed_token_ids') and params.temperature==0 and params.max_tokens==384
                records=stage.read_jsonl(work/'scores.jsonl')
                sent.setdefault('durable_primary_at_audit',[]).append(sum('score' in r and not r.get('review') for r in records))
                note=json.dumps(dict(checks=[],unknowns=['fixture only']))
                return [fixtures.SimpleNamespace(prompt=p,prompt_token_ids=p.split(),outputs=[
                    fixtures.SimpleNamespace(text='broken' if case=='bad_notes' else note,
                                             token_ids=[7,8],finish_reason='stop')]) for p in prompts]
            result=super().generate(prompts,params,use_tqdm)
            for text,out in zip(prompts,result):
                match=re.search(r'ROW_AUDIT_(\d+)',text)
                if not match:continue
                assert 'GOLD_SECRET' not in text and 'GOLD_REASON' not in text
                i=int(match[1]); isfinal=br.CHECKLIST in text
                score=(i*.2 if isfinal else -i*.2)
                if case=='low_final' and isfinal:score=-20.
                probability=1/(1+math.exp(-score))
                entries={1:fixtures.SimpleNamespace(logprob=math.log(probability)),
                         4:fixtures.SimpleNamespace(logprob=math.log(1-probability))}
                if ((isfinal and (case=='no_final' or (case=='partial' and i!=19))) or
                    (not isfinal and case=='primary_error' and i==19)):
                    del entries[4]
                out.outputs[0].logprobs=[entries]
            return result
    mods['vllm'].LLM=Engine
    def start(command,**kwargs):
        with contextlib.redirect_stdout(kwargs['stdout']),contextlib.redirect_stderr(kwargs['stdout']):
            stage.main(command[command.index('--model'):])
        return fixtures.SimpleNamespace(pid=999999,poll=lambda:0)
    captured=io.StringIO()
    saved={name:sys.modules.get(name) for name in mods}
    try:
        sys.modules.update(mods)
        with patch.object(supervisor.subprocess,'Popen',side_effect=start), \
             patch.object(supervisor,'kill_group',return_value=True),patch.object(supervisor,'start_watchdog'), \
             contextlib.redirect_stdout(captured),contextlib.redirect_stderr(io.StringIO()):
            assert entry.main(['--input',str(source),'--output',str(output),'--work-dir',str(work)])==0
    finally:
        for name,value in saved.items():
            if value is None:sys.modules.pop(name,None)
            else:sys.modules[name]=value
    import pyarrow.parquet as pq
    table=pq.read_table(output).to_pydict()
    assert table['id']==ids and all(type(v)is int and v in (0,1) for v in table['label'])
    selected=([*range(8)] if case in ('no_final','low_final') else
              [*range(7),19] if case=='partial' else [*range(12,20)])
    assert table['label']==[int(i in selected) for i in range(20)],(case,table,captured.getvalue())
    cfg=json.loads((work/'judge_config.json').read_text())
    assert cfg['review_ranking']=='max_exact' and cfg['positive_rate']==.4
    assert sent['durable_primary_at_audit']==[16,20]
    assert 'GOLD_SECRET' not in (work/'stage_input.jsonl').read_text()
    event=next(json.loads(line[len('GUARDIAN_JUDGE '):]) for line in reversed(captured.getvalue().split('\n'))
               if line.startswith('GUARDIAN_JUDGE ') and json.loads(line[len('GUARDIAN_JUDGE '):]).get('event')=='final')
    assert event['aggregate']=='max_exact_overall_final'
    expected_exact=0 if case=='no_final' else 1 if case=='partial' else 20
    assert event['review_exact_rows']==expected_exact
    delivery=event['stage_review']['delivery'].get('DELIVERED',0)
    assert delivery==(0 if case=='bad_notes' else 20 if case not in ('no_final','partial') else 20)
    return dict(positive_positions=selected,rows=20,final_exact=expected_exact,
                notes_delivered=delivery,aggregate=event['aggregate'],review_wins=event['review_wins'])


cases={case:run(case) for case in ('full','low_final','partial','no_final','bad_notes','primary_error')}
assert cases['partial']['positive_positions']!=cases['no_final']['positive_positions']
print(json.dumps(dict(mode='EXTRACTED_REAL_PIPELINE_FAKE_MODEL',gpu_tested=False,
                     bootstrap_bypassed=True,posix_transport_replaced=True,cases=cases)))
