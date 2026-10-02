"""The tested separated act/intent requests, reusable outside the benchmark.

Exact sources and fixed conversation roles; semantic categories remain model
hypotheses. No domain names, rule keywords or authored labels are used here.
"""
import json
from .move_scope import StrictModel, TextAct, Intent, input_packet, validate_parse
from .pipeline import decode_model_object

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

def request(stage, stores):
    if stage not in ('act','intent'): raise ValueError('unknown scope stage')
    field='text_segments' if stage=='act' else 'latest_user'
    instruction=ACT_INSTRUCTION if stage=='act' else INTENT_INSTRUCTION
    schema=ActCases.model_json_schema() if stage=='act' else IntentCases.model_json_schema()
    cases=[{'id':key,field:input_packet(store)[field]} for key,store in stores.items()]
    return [{'role':'system','content':instruction},
            {'role':'user','content':json.dumps({'cases':cases},ensure_ascii=False)}],schema

def parse_stores(stores, act_ask, intent_ask):
    records,replies={},{}
    for stage,ask,model in (('act',act_ask,ActCases),('intent',intent_ask,IntentCases)):
        messages,_=request(stage,stores)
        rec=ask(messages); records[stage]=rec
        try:
            if rec.get('status')!='OK': raise ValueError(rec.get('reason','scope stage unavailable'))
            values=model.model_validate(decode_model_object(rec['content'])).model_dump()['cases']
            by_id={r['id']:r for r in values}
            if len(values)!=len(by_id) or set(by_id)!=set(stores):
                raise ValueError('missing, duplicate or foreign scope case IDs')
            replies[stage]=by_id
        except (ValueError,TypeError,KeyError) as exc:
            return {'cases':{key:{'error':str(exc),'stage':stage} for key in stores},'records':records}
    cases={}
    for key,store in stores.items():
        try:
            cases[key]={'move_scope':validate_parse(store,{'acts':replies['act'][key]['acts'],
                'intent':replies['intent'][key]['intent']})}
        except (ValueError,TypeError,KeyError) as exc: cases[key]={'error':str(exc)}
    return {'cases':cases,'records':records}
