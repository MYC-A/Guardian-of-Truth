"""Eight previously unrun long authored contrasts; human review stays explicit."""
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

OUT=ROOT/'outputs/searh_23/source_search_20261002/transfer_ids_followup_v1'


def prepare():
    bank=ROOT/'outputs/searh_23/source_search_20261002/transfer_v1'
    rows={r['id']:r for s in (bank/'inputs.jsonl').read_text(encoding='utf-8').splitlines() if (r:=json.loads(s))}
    author=[json.loads(s) for s in (bank/'author_gold_review_queue.jsonl').read_text(encoding='utf-8').splitlines()]
    groups=('absolute_deadline','shared_antecedent','exception_scope','effect_completion')
    selected=[];labels=[]
    for group in groups:
        pair=[r for r in author if r['group']==group][:2]
        if len(pair)!=2:raise ValueError('paired bank missing')
        selected.extend(rows[r['id']] for r in pair);labels.extend(pair)
    config=json.loads((ROOT/'service/configs/source-search-ids-v5.json').read_text(encoding='utf-8'))
    protocol={'scope':'NEW_UNRUN_LONG_AUTHOR_CONTRASTS_NOT_INDEPENDENT_HUMAN_GOLD',
        'human_review_status':'PENDING','groups':groups,'case_ids':[r['id'] for r in selected],
        'arms':['direct','search'],'model':config['model_budget']['model'],'config':config,
        'input_sha256':digest(selected),'author_label_sha256':digest(labels),'code_sha256':identity(),
        'runner_sha256':digest(Path(__file__).read_text(encoding='utf-8')),
        'adapter_sha256':digest((Path(__file__).parent/'target_frame_probe.py').read_text(encoding='utf-8')),
        'total_tokens':6000000,'total_attempts':650,'max_new_http':56,
        'authorization':'User authorized necessary token spending 2026-10-03; retain original phase ledger and 650 total attempt cap.',
        'selection':'First pre-existing EN pair in each of four groups not included in prior six-case preflight. Author group metadata selects inputs only, never enters inference.',
        'inference':'Same frozen V5 source-ID loop plus phase-aware target frame V3. No free-form reviewer or formal compiler. Only source inputs go to model; no labels.',
        'limit':'Eight real-length authored sources, at most one direct/six search calls per source, no benchmark-specific runtime branches.',
        'quality':'Report TP FP FN TN UNKNOWN per arm and both members of each contrast. Pending human review is not relabelled as held-out proof.',
        'stops':'Single ledger, first provider circuit breaker stops batch, no HTTP retries.'}
    p=OUT/'frozen.json'
    if p.exists() and json.loads(p.read_text(encoding='utf-8'))!=json.loads(json.dumps(protocol)):raise ValueError('frozen changed')
    write(p,protocol)
    for name,items in (('inputs.jsonl',selected),('author_review_queue.jsonl',labels)):
        (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in items),encoding='utf-8')
    return protocol,selected


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');args=parser.parse_args()
    protocol,rows=prepare()
    if not args.run:print(json.dumps({'state':'FROZEN','records':16,'max_new_http':56,'human_review':'PENDING'}));return
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
