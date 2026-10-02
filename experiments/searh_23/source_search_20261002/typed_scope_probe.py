"""Frozen controlled ablation: same short input, direct vs typed BFS/DFS.

Navigation is code-driven from literal target roots. This tests the additional
evidence view, NOT model-selected navigation or unseen long-context transfer.
No gold enters inference; no API extension without explicit CLI authorization.
"""
import argparse
import json
from pathlib import Path
from acceptance import ROOT
from run_compare import identity, write
from guardian_truth.source_search.pipeline import run, decode_model_object, contract
from guardian_truth.source_search.store import SourceStore, digest
from guardian_truth.source_search.move_scope import MoveParse, PARSE_INSTRUCTION, input_packet, validate_parse
from guardian_truth.source_search.typed_pipeline import SCOPE_EXTENSION
from guardian_truth.source_search.move_scope import apply_scope_gate
from guardian_truth.source_search.finding_review import review_findings, INSTRUCTION as REVIEW_INSTRUCTION
from guardian_truth.source_search.archive import persist_snapshot
from guardian_truth.source_search.transport import ModelTransport

OUT=ROOT/'outputs/searh_23/source_search_20261002/typed_scope_probe_v3'

def prepare():
    rows=[json.loads(line) for line in (ROOT/'outputs/searh_23/source_search_20261002/counterevidence_bank_v2/short_inputs.jsonl').read_text(encoding='utf-8').splitlines()]
    protocol={'scope':'AUTHOR_SHORT_CONTROLLED_ABLATION_NOT_HELDOUT_OR_END_TO_END_SEARCH',
        'code_sha256':identity(),'runner_sha256':digest(Path(__file__).read_text(encoding='utf-8')),
        'rows':rows,'inputs_sha256':digest(rows),'models':[{'provider':'ollama','model':'gpt-oss:120b','reasoning_effort':'none'}],
        'arms':['direct','typed_BFS','typed_DFS'],'parse_schema':MoveParse.model_json_schema(),
        'parse_instruction':PARSE_INSTRUCTION,'scope_instruction':SCOPE_EXTENSION,
        'judge_instruction':contract('DIRECT'),'review_instruction':REVIEW_INSTRUCTION,
        'navigation':'All exact literal target roots; graph co-recording only; max_depth=3, max_nodes=24.',
        'review':'one independent per-finding batch after typed ERROR; same model with separate context',
        'max_new_http_attempts':30,'max_output_tokens':1800,'gold_opened_in_inference':False,
        'budget_extension':'PENDING_EXPLICIT_AUTHORIZATION_NO_DEFAULT_EXTENSION'}
    path=OUT/'frozen.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=protocol:
        raise RuntimeError('probe already frozen differently')
    write(path,protocol)
    return protocol

def graph_packet(store,frame,strategy):
    literals=[]
    def collect(value):
        if isinstance(value,dict):
            for child in value.values(): collect(child)
        elif isinstance(value,list):
            for child in value: collect(child)
        elif value is not None: literals.append(value)
    for act in frame['acts']:
        if act['act']=='ATTEMPT_TOOL': collect(act['arguments'])
        else: literals.extend(act['entity_literals'])
    roots=[entity for entity in store.entities.values()
           if any(type(entity['value']) is type(value) and entity['value']==value for value in literals)]
    traversals=[store.traverse(entity,strategy=strategy,max_depth=3,max_nodes=24) for entity in roots]
    return {'strategy':strategy,'roots':roots,'traversals':traversals,
            'status':'CO_RECORDED_SOURCE_VIEW_NOT_AUTHORIZATION',
            'root_selection':'CODE_EXACT_TARGET_LITERALS_NOT_MODEL_SELECTED'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--authorized-total-tokens',type=int,default=1000000)
    parser.add_argument('--authorized-total-attempts',type=int,default=300)
    args=parser.parse_args(); protocol=prepare()
    if not args.run:
        print(json.dumps({'state':'FROZEN','records':18,'max_new_attempts':30,'additional_budget':'PENDING'}))
        return
    phase='/workspace/guardian/results/source-search-api-phase-20261002'
    transport=ModelTransport(phase,**protocol['models'][0],max_calls=args.authorized_total_attempts,
        max_tokens=args.authorized_total_tokens,max_output_tokens=1800)
    launch_path=OUT/'launch.json'
    if launch_path.exists():
        launch=json.loads(launch_path.read_text(encoding='utf-8'))
        if launch['frozen_sha256']!=digest(protocol) or launch['limits']!=transport.snapshot()['limits']:
            raise ValueError('frozen protocol or authorized limits changed on resume')
    else:
        launch={'frozen_sha256':digest(protocol),'limits':transport.snapshot()['limits'],
                'initial_attempts':transport.snapshot()['actual_api_attempts']}
        write(launch_path,launch)
    path=OUT/'predictions.jsonl'
    done={}
    if path.exists():
        done={(r['case_id'],r['arm']):r for line in path.read_text(encoding='utf-8').splitlines() if (r:=json.loads(line))}
    start_attempts=launch['initial_attempts']
    transport.max_calls=min(transport.max_calls,start_attempts+30)
    for row in protocol['rows']:
        for arm in protocol['arms']:
            if (row['id'],arm) in done: continue
            before=transport.snapshot(); store=SourceStore(row)
            if arm=='direct':
                result=run(row,transport,mode='direct')
            else:
                # Identical parse requests hit the shared response cache on DFS.
                request=[{'role':'system','content':PARSE_INSTRUCTION}, {'role':'user','content':json.dumps({
                    'input':input_packet(store),'schema':protocol['parse_schema']},ensure_ascii=False)}]
                record=transport(request)
                try:
                    if record.get('status')!='OK': raise ValueError(record.get('reason','parse unavailable'))
                    frame=validate_parse(store,decode_model_object(record['content']))
                    graph=graph_packet(store,frame,arm.removeprefix('typed_'))
                    result=run(row,transport,mode='direct',source_store=store,initial_context={'move_scope':frame,'graph':graph},
                        system_extension=SCOPE_EXTENSION,
                        assessment_gate=lambda s,v,a:apply_scope_gate(s,frame,v,a))
                    result.update(move_scope=frame,graph_view=graph,parse_record=record)
                    if result['decision']=='ERROR':
                        reviewed=review_findings(store,result['assessment'],transport)
                        result.update(reviewed_assessment=reviewed,decision=reviewed['decision'])
                except (ValueError,TypeError,KeyError) as exc:
                    result={'decision':'UNKNOWN','stop_reason':'typed_parse_failed','error':str(exc),'parse_record':record}
            if 'sources' in result:
                result['source_archive']=persist_snapshot(result.pop('sources'),OUT/'source_stores')
            result.update(case_id=row['id'],arm=arm,budget_before=before,budget_after=transport.snapshot())
            with path.open('a',encoding='utf-8') as stream: stream.write(json.dumps(result,ensure_ascii=False)+'\n')
            done[(row['id'],arm)]=result
            after=transport.snapshot()
            if (transport.breaker.exists() or after['actual_api_attempts']-start_attempts>=30
                    or any(r.get('reason')=='approved_phase_budget_exhausted' for r in (result.get('parse_record',{}),))
                    or result.get('stop_reason')=='approved_phase_budget_exhausted'):
                write(OUT/'status.json',{'state':'STOPPED','records':len(done),'budget':after})
                return
    write(OUT/'status.json',{'state':'COMPLETE','records':len(done),'budget':transport.snapshot()})

if __name__=='__main__': main()
