"""Frozen real-input direct/search comparison using the same source-ID judge.

First six historical mechanism regressions, then the other public46 rows. Gold
never enters inference. Prefixes schedule diagnostic cases only; runtime has no
case-name logic. CLI runs at most the approved finite part of the protocol.
"""
import argparse
import copy
import json
from unittest.mock import patch
from acceptance import ROOT
from run_compare import identity,write
from guardian_truth.source_search.store import SourceStore,digest
from guardian_truth.source_search.archive import persist_snapshot
from guardian_truth.source_search.id_contract import id_contract
from guardian_truth.source_search.transport import ModelTransport
from runtime import GuardianServiceRuntime
import runtime

OUT=ROOT/'outputs/searh_23/source_search_20261002/comparison_ids_v2'


def prepare():
    inputs=ROOT/'outputs/searh_23/source_search_20261002/comparison_v12/inputs.jsonl'
    rows=[json.loads(line) for line in inputs.read_text(encoding='utf-8').splitlines()]
    cfg=json.loads((ROOT/'service/configs/source-search-ids-v2.json').read_text(encoding='utf-8'))
    # Scheduling is disclosed historical regression selection, not a detector rule.
    prefixes=('airline__7::','retail__36::','retail__29::','banking_knowledge__task_051::',
              'banking_knowledge__task_003::','retail__48::')
    priority=[]
    for prefix in prefixes:
        matches=[r for r in rows if r['id'].startswith(prefix)]
        if len(matches)!=1:raise ValueError('historical regression source missing or ambiguous: '+prefix)
        priority.extend(matches)
    remaining=[r for r in rows if r['id'] not in {r['id'] for r in priority}]
    ordered=priority+remaining
    protocol={'scope':'BURNED_PUBLIC46_REAL_INPUT_DEVELOPMENT_NOT_INDEPENDENT_TRANSFER',
        'case_ids':[r['id'] for r in ordered], 'arms':['direct','search'],
        'input_sha256':digest(ordered),'code_sha256':identity(),'config':cfg,
        'id_contract_sha256':digest((ROOT/'src/guardian_truth/source_search/id_contract.py').read_text(encoding='utf-8')),
        'runner_sha256':digest(__import__('pathlib').Path(__file__).read_text(encoding='utf-8')),
        'contracts':{p:id_contract(p) for p in ('DIRECT','SEARCH','JUDGE','FINAL')},
        'comparison':'Same structural layer, source universe, model and assessment interface; direct full-context vs sequential search.',
        'authorization':'Current 1200000/350 total cap. Enlarging a budget requires explicit approval; no second ledger.',
        'stops':'First persistent provider error including 402/429 stops entire run; no retries or availability polling.',
        'max_full_run_http_attempts':46*7,
        'limits':'At most 1 direct and 6 search calls per nonstructural row; structural rows need 0 model calls.',
        'source_privacy':'Only user-provided competition dialogues, no API keys or private server metadata in model messages.',
        'quality_scoring':'Separate script after completion; retain raw outputs and source IDs; UNKNOWN distinct from NO_ERROR.'}
    path=OUT/'frozen.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=protocol:raise ValueError('frozen protocol changed')
    write(path,protocol)
    data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in ordered)
    (OUT/'inputs.jsonl').write_text(data,encoding='utf-8')
    return protocol,ordered


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true')
    parser.add_argument('--cases',type=int,default=6)
    parser.add_argument('--total-token-cap',type=int,default=1200000)
    parser.add_argument('--total-attempt-cap',type=int,default=350)
    parser.add_argument('--approval-receipt',type=__import__('pathlib').Path)
    args=parser.parse_args();protocol,rows=prepare()
    if not args.run:
        print(json.dumps({'state':'FROZEN','cases':46,'paired_records':92,
                          'pilot_cases':6,'max_pilot_calls':42,'max_full_calls':322}));return
    if not 1<=args.cases<=46:raise ValueError('finite case limit must be 1..46')
    if args.total_token_cap>1200000 or args.total_attempt_cap>350:
        if not args.approval_receipt or not args.approval_receipt.exists():raise ValueError('explicit budget approval receipt required')
        receipt=json.loads(args.approval_receipt.read_text())
        if receipt.get('total_tokens')!=args.total_token_cap or receipt.get('total_attempts')!=args.total_attempt_cap:
            raise ValueError('approval does not match requested total cap')
    budget={**protocol['config']['model_budget'],'max_tokens':args.total_token_cap,'max_calls':args.total_attempt_cap}
    transport=ModelTransport('/workspace/guardian/results/source-search-api-phase-20261002',**budget)
    journal=OUT/'predictions.jsonl'
    done={(r['case_id'],r['mode']) for line in journal.read_text(encoding='utf-8').splitlines() if (r:=json.loads(line))} if journal.exists() else set()
    state='COMPLETE'
    for row in rows[:args.cases]:
        for arm in protocol['arms']:
            if (row['id'],arm) in done:continue
            cfg=copy.deepcopy(protocol['config']);cfg['stages']['source_search']['mode']=arm
            with patch.object(runtime,'load_config',return_value=cfg):
                service=GuardianServiceRuntime('source-search-ids-v2',audit_path=OUT/(arm+'_audit.jsonl'))
            service._source_transport=transport;before=transport.snapshot()
            payload=service.check({'case_id':row['id'],'prompt':row['prompt'],'response':row['response']})
            archive=persist_snapshot(payload.pop('source_store'),OUT/'source_stores')
            payload.update(mode=arm,cost_before=before,cost_after=transport.snapshot(),source_archive=archive)
            with journal.open('a',encoding='utf-8') as stream:stream.write(json.dumps(payload,ensure_ascii=False)+'\n')
            done.add((row['id'],arm))
            if transport.breaker.exists() or payload['coverage'].get('stop_reason') in (
                    'approved_phase_budget_exhausted','provider_circuit_open'):
                state='STOPPED';break
        if state=='STOPPED':break
    write(OUT/'status.json',{'state':state,'requested_cases':args.cases,'records':len(done),
                            'full_comparison_complete':len(done)==92,'budget':transport.snapshot()})


if __name__=='__main__':main()
