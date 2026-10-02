"""Isolate target-act parsing from USER intent; 32 cases, at most 8 HTTP.

This is a new diagnostic after v2, not a repair of its predictions. Gold stays
in the separately frozen author_review file and is never imported here.
"""
import argparse
import json
from pathlib import Path
from acceptance import ROOT
from run_compare import write, identity
from guardian_truth.source_search.store import SourceStore, digest
from guardian_truth.source_search.pipeline import decode_model_object
from guardian_truth.source_search.move_scope import StrictModel, TextAct, Intent, input_packet, validate_parse
from guardian_truth.source_search.transport import ModelTransport

class ActCase(StrictModel):
    id: str
    acts: list[TextAct]
class ActCases(StrictModel):
    cases: list[ActCase]
class IntentCase(StrictModel):
    id: str
    intent: Intent
class IntentCases(StrictModel):
    cases: list[IntentCase]

ACT_INSTRUCTION='''Classify only supplied assistant text_segments into speech
acts. Conversation speaker is supplied metadata. performer is the person who
performs the requested or described action: Please confirm -> USER; I will
replace after confirmation -> ASSISTANT. Cover material text with exact source
quotes. ASK_CONFIRM/ASK_CLARIFY/ASK_USER_ACTION -> REQUEST; OFFER_FUTURE and
OFFER_ESCALATION -> FUTURE or CONDITIONAL; ASSERT_DONE -> CLAIMED_COMPLETED;
REFUSE/ASSERT_FACT -> PRESENT. A future transfer is OFFER_ESCALATION, not an
executed transfer. A claim of completion is not observed completion. Empty
text_segments -> empty acts. Native calls are owned by code and not supplied.
Copy entity_literals only from the act's own quote. No policy, user request,
business verdict or imagined tool call. Return every case ID under the schema.'''
INTENT_INSTRUCTION='''Classify only the supplied latest_user request. EXPLICIT
means an identified requested operation; AMBIGUOUS means an operation is not
specified, requested_action null. Please help with item X is AMBIGUOUS, neither
inspection-only nor commit authorization. Please replace item X is EXPLICIT.
Missing request is UNKNOWN. Cite exactly the supplied USER source. Do not
generate assistant acts or a policy verdict. Return every case ID under schema.'''
OUT=ROOT/'outputs/searh_23/source_search_20261002/move_intent_probe_v1'

def prepare():
    rows=[json.loads(line) for line in (ROOT/'outputs/searh_23/source_search_20261002/move_intent_bank_v1/inputs.jsonl').read_text(encoding='utf-8').splitlines()]
    protocol={'scope':'AUTHOR_MOVE_INTENT_COMPONENT_DIAGNOSTIC_NOT_TRANSFER',
        'code_sha256':identity(),'runner_sha256':digest(Path(__file__).read_text(encoding='utf-8')),
        'rows':rows,'model':'SERVER_MISTRAL_MODEL','provider':'mistral','batch_size':8,
        'act_schema':ActCases.model_json_schema(),'intent_schema':IntentCases.model_json_schema(),
        'act_instruction':ACT_INSTRUCTION,'intent_instruction':INTENT_INSTRUCTION,
        'max_http_attempts':8,'max_output_tokens':4000,
        'prompt_revisions_after_output':False,'human_review_status':'PENDING'}
    path=OUT/'frozen.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=protocol:
        raise ValueError('frozen probe changed')
    write(path,protocol); return protocol

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--run',action='store_true')
    parser.add_argument('--authorized-total-tokens',type=int,default=1200000)
    parser.add_argument('--authorized-total-attempts',type=int,default=350)
    args=parser.parse_args(); protocol=prepare()
    if not args.run:
        print(json.dumps({'state':'FROZEN','cases':32,'max_http_attempts':8})); return
    phase='/workspace/guardian/results/source-search-api-phase-20261002'
    for offset in range(0,len(protocol['rows']),8):
        batch=protocol['rows'][offset:offset+8]; replies={}
        for stage,model in (('act',ActCases),('intent',IntentCases)):
            path=OUT/f'batch_{offset}_{stage}.json'
            if path.exists():
                rec=json.loads(path.read_text(encoding='utf-8'))
            else:
                transport=ModelTransport(phase,provider='mistral',response_schema=protocol[stage+'_schema'],
                    max_output_tokens=4000,max_calls=args.authorized_total_attempts,max_tokens=args.authorized_total_tokens)
                cases=[]
                for row in batch:
                    packet=input_packet(SourceStore(row))
                    field='text_segments' if stage=='act' else 'latest_user'
                    cases.append({'id':row['id'],field:packet[field]})
                before=transport.snapshot()
                record=transport([{'role':'system','content':protocol[stage+'_instruction']},
                                  {'role':'user','content':json.dumps({'cases':cases},ensure_ascii=False)}])
                rec={'raw_record':record,'budget_before':before,'budget_after':transport.snapshot()}
                write(path,rec)
            if rec['raw_record'].get('status')!='OK':
                write(OUT/'status.json',{'state':'STOPPED','reason':rec['raw_record'].get('reason'),
                    'batch_offset':offset,'stage':stage,'budget':rec['budget_after']}); return
            try:
                values=model.model_validate(decode_model_object(rec['raw_record']['content'])).model_dump()['cases']
                by_id={r['id']:r for r in values}
                if len(values)!=len(by_id) or set(by_id)!={r['id'] for r in batch}:
                    raise ValueError('missing, duplicate or foreign case IDs')
                replies[stage]=by_id
            except (ValueError,TypeError,KeyError) as exc:
                write(OUT/'status.json',{'state':'FORMAT_STOP','batch_offset':offset,'stage':stage,'error':str(exc)})
                return
        results=[]
        for row in batch:
            try:
                frame=validate_parse(SourceStore(row),{'acts':replies['act'][row['id']]['acts'],
                                     'intent':replies['intent'][row['id']]['intent']})
                results.append({'id':row['id'],'move_scope':frame})
            except (ValueError,KeyError,TypeError) as exc:
                results.append({'id':row['id'],'error':str(exc),'raw_act':replies['act'][row['id']],
                                'raw_intent':replies['intent'][row['id']]})
        write(OUT/f'batch_{offset}_validated.json',results)
    write(OUT/'status.json',{'state':'COMPLETE','cases':32,'batches':4})

if __name__=='__main__': main()
