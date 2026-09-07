"""Run one frozen B/C architecture variant; labels never cross inference boundary."""
import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import time

from guardian_truth.benchmarking import metrics
from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.decision import decide
from guardian_truth.language import LanguageAnalyzer, LanguageConfig, RunBudget
from guardian_truth.llm_client import ChatClient, ClientConfig, HTTPResponse, _http_transport
from guardian_truth.pipeline import Detector
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file


def safe_json(value):
    return json.dumps(value,ensure_ascii=True,allow_nan=False,sort_keys=True)


class PacedTransport:
    """Pace and record every HTTP attempt without retaining headers/bodies."""
    def __init__(self,stream,interval,budget,transport=None):
        if type(interval) not in (int,float) or not math.isfinite(interval) or interval < 0:
            raise ValueError('Invalid pacing interval')
        self.stream,self.interval,self.budget=stream,interval,budget
        self.transport=transport or _http_transport
        self.last_start=None
        self.row_id=None
        self.attempt=0

    def __call__(self,request,timeout):
        while self.last_start is not None:
            remaining=self.interval-(time.monotonic()-self.last_start)
            if remaining <= 0: break
            time.sleep(min(1.0,remaining,self.budget.remaining_seconds()))
        self.last_start=time.monotonic(); self.attempt+=1
        started=time.monotonic(); status='transport_exception'; http_status=None
        try:
            timeout=min(timeout,self.budget.remaining_seconds())
            response=self.transport(request,timeout)
            if not isinstance(response,HTTPResponse):
                return response
            http_status=response.status; status='http_response'
            return response
        finally:
            self.stream.write(safe_json({'attempt':self.attempt,'row_id':self.row_id,
                'status':status,'http_status':http_status,
                'elapsed_seconds':max(0,time.monotonic()-started)})+'\n')
            self.stream.flush()


def select_rows(rows,ids_file):
    if ids_file is None: return rows,None
    raw=ids_file.read_bytes(); ids=json.loads(raw)
    if (not isinstance(ids,list) or not ids or len(set(ids))!=len(ids)
            or any(not isinstance(i,str) or not i for i in ids)):
        raise ValueError('Invalid ids file')
    by_id={str(row['id']):row for row in rows}
    if any(i not in by_id for i in ids): raise ValueError('Unknown selected id')
    return [by_id[i] for i in ids],hashlib.sha256(raw).hexdigest()


def window_rows(rows,start_index,row_count):
    if type(start_index) is not int or start_index < 0:
        raise ValueError('Invalid start index')
    if row_count is not None and (type(row_count) is not int or row_count < 1):
        raise ValueError('Invalid row count')
    selected=rows[start_index:] if row_count is None else rows[start_index:start_index+row_count]
    if not selected: raise ValueError('Empty row window')
    return selected


CALL_STAGES=('one_shot','extractor','semantic_verifier','final_judge')


def call_telemetry(records):
    """Aggregate structured-call validity without treating routing as a call."""
    stages={stage:{'total':0,'valid':0,'invalid':0} for stage in CALL_STAGES}
    relations=Counter()
    for record in records:
        trace=record['review']['reading_trace']
        is_decomposed=any(item.get('stage') in ('extractor','semantic_verifier','final_judge')
                          for item in trace)
        usage=record['review'].get('semantic_usage',{})
        one_shot_total=usage.get('llm_calls',0) if isinstance(usage,dict) else 0
        if not is_decomposed and type(one_shot_total) is int and one_shot_total >= 0:
            stages['one_shot']['total']+=one_shot_total
        for item in trace:
            stage=item.get('stage')
            if stage in stages and item.get('call') is not None:
                stages[stage]['total']+=1
                key='valid' if item.get('valid') is True else 'invalid'
                stages[stage][key]+=1
            elif type(item.get('round')) is int:
                stages['one_shot']['valid']+=1
            if stage=='semantic_verifier' and isinstance(item.get('relations'),dict):
                relations.update(value for value in item['relations'].values() if isinstance(value,str))
    for item in stages.values():
        item['invalid']=item['total']-item['valid']
    total=sum(item['total'] for item in stages.values())
    valid=sum(item['valid'] for item in stages.values())
    return {'by_stage':stages,'total':total,'valid':valid,'invalid':total-valid,
            'valid_rate':valid/total if total else None,
            'semantic_relation_counts':dict(sorted(relations.items()))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',choices=('baseline','strict','decomposed'),required=True)
    parser.add_argument('--provider',choices=('groq','openrouter','gemini'),default='groq')
    parser.add_argument('--base-url')
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--ids-file',type=Path)
    parser.add_argument('--start-index',type=int,default=0,
                        help='Zero-based deterministic row window for quota-safe shards')
    parser.add_argument('--row-count',type=int)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--model',default='openai/gpt-oss-20b')
    parser.add_argument('--max-evidence-chars',type=int,default=4800)
    parser.add_argument('--max-prompt-chars',type=int,default=120000)
    parser.add_argument('--max-output-tokens',type=int,default=2048)
    parser.add_argument('--max-checks',type=int,default=12)
    parser.add_argument('--group-size',type=int,default=4)
    parser.add_argument('--max-requests',type=int,default=400)
    parser.add_argument('--max-input-chars',type=int,default=8000000)
    parser.add_argument('--seconds',type=float,default=7200)
    parser.add_argument('--timeout-seconds',type=float,default=60)
    parser.add_argument('--retries',type=int,default=1)
    parser.add_argument('--interval-seconds',type=float,default=30)
    parser.add_argument('--threshold',type=float,default=.5)
    args=parser.parse_args()
    if args.output_dir.exists(): parser.error('Use a fresh output directory')
    if not args.env_file.is_file(): parser.error('Explicit env file required')
    try:
        rows=read_rows(args.input); validate_rows(rows)
        rows,ids_hash=select_rows(rows,args.ids_file)
        rows=window_rows(rows,args.start_index,args.row_count)
        if not rows or any(str(row.get('label')) not in ('0','1') for row in rows): raise ValueError
        load_env_file(args.env_file)
        initial=ClientConfig.from_env()
        selected_url=args.base_url or (initial.base_url if args.provider=='groq' else None)
        config=provider_config(initial,args.provider,model=args.model,base_url=selected_url)
        config=replace(config,max_output_tokens=args.max_output_tokens,
                       timeout_seconds=args.timeout_seconds,max_retries=args.retries,
                       strict_schema=args.variant=='decomposed')
        budget=RunBudget(args.max_requests,args.max_input_chars,args.seconds)
        ChatClient(config).validate_configuration()
    except Exception:
        # argparse emits no secret/server data. Client errors have fixed categories,
        # but deliberately collapse them here as well.
        parser.error('Invalid input, environment or bounded-run configuration')
    package=Path(__import__('guardian_truth').__file__).parent
    source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}
    run_config={'variant':args.variant,'provider':args.provider,
        'model':config.model,'base_url':config.base_url,
        'input_hash':hashlib.sha256(args.input.read_bytes()).hexdigest(),'ids_file_hash':ids_hash,
        'row_window':{'start_index':args.start_index,'row_count':args.row_count},
        'selected_ids':[str(row['id']) for row in rows],
        'request':{'temperature':0,'max_output_tokens':config.max_output_tokens,
                   'provider_token_parameter':('max_tokens' if args.provider=='openrouter'
                                               else 'max_completion_tokens'),
                   'response_format':'json_schema_strict' if args.variant=='decomposed' else 'json_object',
                   'reasoning_effort':({'extractor':'low','semantic_verifier':'native_medium',
                                        'final_judge':'low'} if args.variant=='decomposed'
                                       else 'native_default_unmodified'),
                   'timeout_seconds':config.timeout_seconds,'max_retries':config.max_retries},
        'semantic':{'evidence_chars':args.max_evidence_chars,'max_prompt_chars':args.max_prompt_chars,
                    'max_checks':args.max_checks,'group_size':args.group_size},
        'budget':{'max_requests':args.max_requests,'max_input_chars':args.max_input_chars,
                  'seconds':args.seconds,'interval_seconds':args.interval_seconds},
        'threshold':args.threshold,'skip_mechanical_violations':True,
        'data_role':'inspected_development_screen' if args.ids_file else 'inspected_development_full',
        'labels_or_explanations_sent_to_model':False,'source_hashes':source_hashes,
        'runner_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output_dir.mkdir(parents=True,exist_ok=False)
    (args.output_dir/'configuration.json').write_text(json.dumps(run_config,indent=2),encoding='utf-8')
    records=[]; started=time.monotonic()
    with (args.output_dir/'attempts.jsonl').open('x',encoding='utf-8') as attempts, \
         (args.output_dir/'audit.jsonl').open('x',encoding='utf-8') as audit:
        paced=PacedTransport(attempts,args.interval_seconds,budget)
        client=ChatClient(config,transport=paced)
        if args.variant in ('baseline','strict'):
            semantic=LanguageAnalyzer(client,LanguageConfig(mode='graph',max_rounds=1,
                max_evidence_chars=args.max_evidence_chars,max_prompt_chars=args.max_prompt_chars,
                protocol=args.variant),budget=budget)
        else:
            from guardian_truth.decomposition import DecomposedAnalyzer,DecompositionConfig
            from guardian_truth.decomposition_exact import resolve_exact
            semantic=DecomposedAnalyzer(client,DecompositionConfig(max_evidence_chars=args.max_evidence_chars,
                max_prompt_chars=args.max_prompt_chars,max_checks=args.max_checks,
                group_size=args.group_size),budget=budget,deterministic_resolver=resolve_exact)
        detector=Detector(semantic=semantic); precheck=Detector(enabled=detector.enabled)
        for index,row in enumerate(rows,1):
            before=budget.requests; row_started=time.monotonic()
            review=precheck.review(row['prompt'],row['response'])
            skipped=review.status=='violation'; paced.row_id=str(row['id'])
            if not skipped: review=detector.review(row['prompt'],row['response'])
            decision=decide(review,threshold=args.threshold,use_semantic=True)
            trace=review.reading_trace
            ledger=next((item.get('ledger') for item in reversed(trace) if 'ledger' in item),None)
            supplied_calls=review.semantic_usage.get('llm_calls')
            logical_calls=(supplied_calls if type(supplied_calls) is int and supplied_calls >= 0
                           else sum(1 for item in trace if
                                    (item.get('stage') in ('extractor','semantic_verifier','final_judge')
                                     and item.get('call') is not None)
                                    or type(item.get('round')) is int))
            record={'id':str(row['id']),'label':int(row['label']),'prediction':decision.label,
                'decision':asdict(decision),'skipped_mechanical':skipped,'review':asdict(review),
                'logical_llm_calls':logical_calls,'http_attempts':budget.requests-before,
                'elapsed_seconds':max(0,time.monotonic()-row_started),'ledger':ledger}
            audit.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n');audit.flush()
            records.append(record)
            print(safe_json({'completed':index,'total':len(rows),'id':record['id'],
                  'prediction':record['prediction'],'fallback':decision.used_fallback,
                  'logical_calls':logical_calls,'http_attempts':record['http_attempts']}),flush=True)
    labels=[r['label'] for r in records]; predictions=[r['prediction'] for r in records]
    summary=metrics(labels,predictions)
    structured_calls=call_telemetry(records)
    summary.update(fallback=sum(r['decision']['used_fallback'] for r in records),
        logical_llm_calls=sum(r['logical_llm_calls'] for r in records),
        http_attempts=sum(r['http_attempts'] for r in records),
        reported_tokens=sum(r['review']['semantic_usage'].get('total_tokens',0) for r in records),
        elapsed_seconds=max(0,time.monotonic()-started),
        structured_valid_semantic_rows=sum(not r['skipped_mechanical'] and r['review']['semantic_score'] is not None for r in records),
        semantic_rows=sum(not r['skipped_mechanical'] for r in records),
        structured_calls=structured_calls,
        mechanical_short_circuits=sum(r['skipped_mechanical'] for r in records),
        deterministic_checks=sum(1 for r in records for entry in (r['ledger'] or [])
                                 if entry.get('verifier')=='deterministic'),
        deterministic_contradictions=sum(1 for r in records for entry in (r['ledger'] or [])
                                 if entry.get('verifier')=='deterministic'
                                 and entry.get('relation')=='CONTRADICTED'),
        issues=dict(Counter(issue for r in records for issue in r['review']['unresolved']
                            if issue.startswith(('language_','semantic_','decomposition_')))),
        changed_from_gold=[r['id'] for r in records if r['label']!=r['prediction']],
        budget=budget.summary())
    report={'configuration':run_config,'metrics':summary,
        'limitations':['Inspected development data; no hidden-test transfer claim.',
          'Screen selection is intentionally error-heavy and its F1 is not representative.',
          'Logical calls and HTTP attempts differ when transport retries occur.',
          'Reason Precision requires separate human/reference audit; model rationales are not self-gold.',
          'Native reasoning defaults are unmodified and may not imply identical internal compute.']}
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(safe_json(summary),flush=True)


if __name__=='__main__': main()
