"""Matched N0/RF reading-aid pilot; no S1 quote-as-proof or hidden retries."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path('/workspace/guardian/pilot_20261010')
CODE = BASE/'code'
ROOT = Path('/workspace/guardian/runtime')
PHASE = BASE/'rf_c290c178'
SHA_INPUT = '8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba'
sys.path[:0] = [str(CODE/'src'),str(CODE)]
os.environ['PYTHONPATH'] = os.pathsep.join([str(CODE/'src'),str(CODE)])
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['PYTHONUTF8'] = '1'

from guardian_truth.submission import primary, cli
from guardian_truth.submission.recovery import recover_output
from guardian_truth.integrated.transport import wire_body
from experiments.guardian_semantic.variants import _parse

module_path = BASE/'retrieval_c290c178.py'
EXPECTED_MODULE_SHA = 'd4f7fbf2a54ae2a778fc7b97e90adbe8c115850859e9e6e2f4b85a89ec6ea9f6'
if hashlib.sha256(module_path.read_bytes()).hexdigest()!=EXPECTED_MODULE_SHA:
    raise ValueError('PINNED_RETRIEVAL_SHA_MISMATCH')
spec = importlib.util.spec_from_file_location('rf_pinned',module_path)
rf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rf)
OriginalHook = primary.PrimaryReviewHook


class NoLayers:
    def findings(self, row):return dict(findings=[],status='NOT_ENABLED_MATCHED_N0_RF')


def arm(mode, fast, threads):
    class Hook(OriginalHook):
        def inject(self, request, attempt):
            if mode == 'N0':
                self.log.append(dict(tag='no_pre_control',injected=False,authority='NONE'))
                return request
            try:
                packet=json.loads(request['messages'][1]['content'])
                policy=' \n'.join(s['text'] for s in packet.get('normative_sources',[]))
                focus=rf.rank(policy,rf.move_text(packet),8)
                q=deepcopy(request)
                q['messages'][0]['content'] += (
                    '\nrule_focus is a lexical retrieval reading aid, not evidence or a judgment. '
                    'Read these excerpts against the actual action; full original policies, scope and exceptions still apply. '
                    'Similarity does not establish applicability, identity or a violation. Cite ordinary original sources only.')
                q['messages'][1]['content']=json.dumps(dict(packet,rule_focus=focus),ensure_ascii=False,separators=(',',':'))
                self.log.append(dict(tag='rule_focus',injected=True,n=len(focus),authority='MODEL_READING_AID_ONLY',
                    source_coverage='FULL_ORIGINAL_PACKET_RETAINED',wire_bytes=len(wire_body(q))))
                return q
            except Exception as e:
                self.log.append(dict(tag='rule_focus_failure',injected=False,error_type=type(e).__name__))
                return request
    primary.PrimaryReviewHook=Hook
    out=PHASE/mode/'rep1'
    out.mkdir(parents=True,exist_ok=False)
    work=out/'receipts'
    work.mkdir()
    rows=cli.read_rows(CODE/'valid.parquet')
    traces={}
    start=time.monotonic()
    with cli.ModelServer(ROOT,work,8,32768,fast=fast) as server:
        client=cli.LocalClient(server.port,32768,api_key=server.api_key)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures={pool.submit(cli.predict_one,row,client,NoLayers()):row['id'] for row in rows}
            for future in as_completed(futures):
                identifier=futures[future]
                try:trace=future.result()
                except Exception as e:
                    source=next(row for row in rows if row['id']==identifier)
                    trace=dict(id=identifier,binary=None,error=type(e).__name__,input_row_sha256=cli.row_fingerprint(source))
                trace=recover_output(trace)
                trace.update(pre_profile=mode,experiment_profile='matched_R_fix_only_'+mode)
                traces[identifier]=trace
                with (work/'traces.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps(trace,ensure_ascii=False,default=str)+'\n')
                print(mode,len(traces),'/',len(rows),flush=True)
    primary.PrimaryReviewHook=OriginalHook
    cli.write_predictions(out/'predictions.parquet',[dict(id=row['id'],label=traces[row['id']]['binary']) for row in rows])
    (work/'calls.json').write_text(json.dumps(client.calls,ensure_ascii=False))
    report=dict(rows=len(rows),profile=mode,seconds=time.monotonic()-start,calls=len(client.calls),
        output_tokens=sum((c.get('usage')or{}).get('completion_tokens',0) for c in client.calls),
        input_tokens=sum((c.get('usage')or{}).get('prompt_tokens',0) for c in client.calls),
        input_sha256=SHA_INPUT,explicit_flash=fast,threads=threads,
        default_zero_fallbacks=sum((t.get('output_recovery')or{}).get('mode')=='DEFAULT_ZERO' for t in traces.values()),
        raw_model_recoveries=sum((t.get('output_recovery')or{}).get('mode')=='RAW_MODEL_DECISION' for t in traces.values()))
    (work/'run.json').write_text(json.dumps(report,indent=2))
    subprocess.run([sys.executable,str(CODE/'scripts/qwen_submission_reproject.py'),
        '--input',str(CODE/'valid.parquet'),'--traces',str(work/'traces.jsonl'),
        '--output-dir',str(out/'score'),'--expected-input-sha256',SHA_INPUT,
        '--output-recovery','fallback-zero'],cwd=CODE,check=True)


if PHASE.exists():raise ValueError('RF_PHASE_EXISTS')
if hashlib.sha256((CODE/'valid.parquet').read_bytes()).hexdigest()!=SHA_INPUT:
    raise ValueError('INPUT_HASH_MISMATCH')
first=BASE/'matched_8911b35f'
deadline=time.monotonic()+10800
while not (first/'done.json').exists():
    if time.monotonic()>deadline:raise TimeoutError('FIRST_PHASE_NOT_COMPLETE')
    time.sleep(20)
config=json.loads((first/'freeze.json').read_text())
done=json.loads((first/'done.json').read_text())
if done.get('status') != 'COMPLETE' or done.get('profiles') != ['legacy','compact']:
    raise ValueError('FIRST_PHASE_NOT_COMPLETE')
expected=dict(code_sha='8911b35f8ca895aad5c68bbe1fca7d1721f7f867',input_sha=SHA_INPUT,
    native_commit='f498f864fbc0472004ee1c3616c1188c68eb157f',workers=8,context=32768)
if any(config.get(k)!=v for k,v in expected.items()):raise ValueError('FIRST_PHASE_FREEZE_MISMATCH')
if hashlib.sha256(module_path.read_bytes()).hexdigest()!=EXPECTED_MODULE_SHA:
    raise ValueError('MODULE_CHANGED_DURING_WAIT')
threads=config['threads']
for k in ('OMP_NUM_THREADS','LLAMA_ARG_THREADS','LLAMA_ARG_THREADS_BATCH'):os.environ[k]=str(threads)
PHASE.mkdir()
(PHASE/'freeze.json').write_text(json.dumps(dict(code=config['code_sha'],rf_source_ref='c290c178',
    rf_source_sha256=hashlib.sha256(module_path.read_bytes()).hexdigest(),profiles=['N0','RF'],
    operator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    retrieval_limitations='historical min_len25/max_len700/CUEEnglish; original full policy retained',
    input_sha=SHA_INPUT,explicit_flash=config['explicit_flash'],threads=threads,workers=8,context=32768,
    scope='matched lexical hint, no blind pre or F layers in either arm; not LSH, not S1'),indent=2))
for mode in ('N0','RF'):arm(mode,config['explicit_flash'],threads)
(PHASE/'done.json').write_text(json.dumps(dict(status='COMPLETE')))
