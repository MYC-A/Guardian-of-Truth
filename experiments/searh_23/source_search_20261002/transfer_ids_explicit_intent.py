"""Freeze explicit user intent after independent blind source-only audit.

Original bank/run remain unchanged. Completion-report pair is byte-identical
and can reuse its requests. Six modified action cases cost at most 42 HTTP.
"""
import argparse
import json
from pathlib import Path
from acceptance import ROOT
from run_compare import identity,write
from target_frame_probe import target_frame,request_with_target
from guardian_truth.source_search.id_contract import run_ids
from guardian_truth.source_search.store import digest
from guardian_truth.source_search.archive import persist_snapshot
from guardian_truth.source_search.transport import ModelTransport

OUT=ROOT/'outputs/searh_23/source_search_20261002/transfer_ids_explicit_intent_v1'


def prepare():
    prior=ROOT/'outputs/searh_23/source_search_20261002/transfer_ids_followup_v1'
    original=[json.loads(s) for s in (prior/'inputs.jsonl').read_text(encoding='utf-8').splitlines()]
    labels={r['id']:r for s in (prior/'author_review_queue.jsonl').read_text(encoding='utf-8').splitlines() if (r:=json.loads(s))}
    rows=[];gold=[];mapping=[]
    for row in original:
        label=labels[row['id']];changed=label['group']!='effect_completion'
        if changed:
            prompt=row['prompt'].replace('please help with component X-31.',
                'Please commit the single prepared change for component X-31 now. Keep all separate policy prerequisites in force.')
            prompt=prompt.replace('Commits the requested change.',
                'Applies the single prepared change for the specified item. The user must request this action; policy prerequisites still apply.')
            if prompt==row['prompt']:raise ValueError('expected generic intent/catalog text not found')
            row={'id':'explicit-'+digest({'prompt':prompt,'response':row['response']})[:12],
                 'prompt':prompt,'response':row['response']}
        rows.append(row);gold.append({**label,'id':row['id'],'human_review_status':'PENDING',
            'blind_machine_review':'Target relation verified; intent/catalog clarified before viewing old run replies.'})
        mapping.append({'id':row['id'],'original_id':label['id'],'intent_changed':changed})
    config=json.loads((ROOT/'service/configs/source-search-ids-v5.json').read_text(encoding='utf-8'))
    protocol={'scope':'NEW_EXPLICIT_INTENT_LONG_AUTHOR_CONTRASTS_NOT_HUMAN_GOLD',
        'case_ids':[r['id'] for r in rows],'arms':['direct','search'],'human_review_status':'PENDING',
        'input_sha256':digest(rows),'author_label_sha256':digest(gold),'config':config,'code_sha256':identity(),
        'runner_sha256':digest(Path(__file__).read_text(encoding='utf-8')),
        'adapter_sha256':digest((Path(__file__).parent/'target_frame_probe.py').read_text(encoding='utf-8')),
        'mapping':mapping,'max_new_http':42,'total_tokens':6000000,'total_attempts':650,
        'reason':'Blind Astra source-only audit found three permitted commit cases ambiguous under please help. Explicitly define requested prepared action without waiving recorded approval/identity/waiver/date conditions.',
        'freeze_timing':'Before root opens prior followup model replies or scores. Original frozen bank and predictions unchanged.',
        'authorization':'User authorized necessary token spending; original shared ledger retained, 650 attempt cap unchanged.',
        'quality':'All four paired mechanisms with negative controls; report UNKNOWN separately, not held-out human validation.',
        'stops':'Shared provider breaker, no HTTP retry.'}
    p=OUT/'frozen.json'
    if p.exists() and json.loads(p.read_text(encoding='utf-8'))!=protocol:raise ValueError('frozen protocol changed')
    write(p,protocol)
    for name,values in (('inputs.jsonl',rows),('author_review_queue.jsonl',gold)):
        (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in values),encoding='utf-8')
    return protocol,rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');args=parser.parse_args()
    protocol,rows=prepare()
    if not args.run:print(json.dumps({'state':'FROZEN','records':16,'max_new_http':42,'human_review':'PENDING'}));return
    transport=ModelTransport('/workspace/guardian/results/source-search-api-phase-20261002',
        **{**protocol['config']['model_budget'],'max_tokens':protocol['total_tokens'],'max_calls':protocol['total_attempts']})
    journal=OUT/'predictions.jsonl';done=set()
    if journal.exists():done={(r['case_id'],r['mode']) for s in journal.read_text(encoding='utf-8').splitlines() if (r:=json.loads(s))}
    state='COMPLETE'
    for row in rows:
        frame=target_frame(row)
        def ask(messages):return transport(request_with_target(messages,frame))
        for arm in protocol['arms']:
            if (row['id'],arm) in done:continue
            before=transport.snapshot();result=run_ids(row,ask,mode=arm,max_steps=6,max_payload_bytes=800000)
            archive=persist_snapshot(result.pop('sources'),OUT/'source_stores')
            result.update(module_trace=result.pop('trace'),cost_before=before,cost_after=transport.snapshot(),source_archive=archive,
                coverage={**result['coverage'],'stop_reason':result['stop_reason']})
            with journal.open('a',encoding='utf-8') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
            done.add((row['id'],arm))
            if transport.breaker.exists() or result['stop_reason'] in ('approved_phase_budget_exhausted','provider_circuit_open'):
                state='STOPPED';break
        if state=='STOPPED':break
    write(OUT/'status.json',{'state':state,'records':len(done),'planned_records':16,'budget':transport.snapshot()})


if __name__=='__main__':main()
