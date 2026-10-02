"""Typed latest-move hypotheses with code-owned tool calls and exact spans.

Pydantic validates shape; source checks validate provenance. Neither certifies
the linguistic labels. A rejected binding is UNKNOWN, never a clean verdict.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

ActKind = Literal['ASK_CONFIRM', 'ASK_CLARIFY', 'ASK_USER_ACTION', 'OFFER_FUTURE',
                  'OFFER_ESCALATION', 'REFUSE', 'ASSERT_FACT', 'ASSERT_DONE', 'UNKNOWN']
Modality = Literal['PRESENT', 'REQUEST', 'FUTURE', 'CONDITIONAL', 'CLAIMED_COMPLETED', 'UNKNOWN']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Quote(StrictModel):
    source_id: str
    quote: str = Field(min_length=1)


class TextAct(StrictModel):
    id: str = Field(min_length=1)
    speaker: Literal['ASSISTANT', 'USER', 'UNKNOWN']
    performer: Literal['ASSISTANT', 'USER', 'OTHER', 'UNKNOWN'] = Field(
        description='Who performs the requested or described action. For Please confirm: USER, not the speaker.')
    act: ActKind
    modality: Modality
    action: str = Field(min_length=1)
    entity_literals: list[str]
    evidence: Quote


class Intent(StrictModel):
    status: Literal['EXPLICIT', 'AMBIGUOUS', 'UNKNOWN']
    requested_action: str | None
    evidence: Quote | None


class MoveParse(StrictModel):
    acts: list[TextAct]
    intent: Intent


PARSE_INSTRUCTION = '''Classify the latest assistant's TEXT and the latest user's
request, without deciding policy compliance. Native tool calls are supplied
separately by code: do not copy or reinterpret them as text acts.
Cover every material text clause with a sourced act. Return no verdict or rule.
Distinguish speaker from performer: "Please run the test" is spoken by the
assistant, asks the USER to act, modality REQUEST, not assistant execution.
"Confirm and I will replace it" is ASK_CONFIRM / REQUEST plus OFFER_FUTURE /
CONDITIONAL, not ASSERT_DONE. The confirmation performer is USER; the future
replacement performer is ASSISTANT. Speaker is the role already present in the
source packet, never inferred from whether an action was requested.
"I replaced it" is ASSERT_DONE / CLAIMED_COMPLETED;
it is a claim, not proof of successful execution. "I will transfer you" is
OFFER_ESCALATION / FUTURE, not a completed transfer. "I cannot help" is REFUSE /
PRESENT. "The capacity is 65%" is ASSERT_FACT / PRESENT, to be checked later.
Use exact contiguous quotes and supplied source IDs; preserve spelling. Copy
entity_literals only when explicitly in that act's quote; do not resolve aliases.
For "Please help with item X" intent is AMBIGUOUS and requested_action null;
neither inspection-only nor authorization to commit follows from that text.
For "Please replace item X" intent is EXPLICIT. Missing/latest-user uncertainty
is UNKNOWN. Every category is a linguistic hypothesis, not established truth.
Return JSON conforming to the supplied schema.'''


def input_packet(store):
    calls, texts = [], []
    for sid, source in store.sources.items():
        if source['document'] != 'response' or source['kind'] == 'raw':
            continue
        event = store.target_events[source['event']]
        if source['kind'] == 'call':
            calls.append({'id':'native:'+sid, 'act':'ATTEMPT_TOOL',
                'modality':'ATTEMPTED', 'speaker':event.role.upper(),
                'performer':event.role.upper(), 'tool':event.name,
                'arguments':event.value, 'json_valid':event.json_valid,
                'evidence':store.resolve_quote({'source_id':sid,'quote':store.text(sid)}),
                'status':'CODE_PARSED_ATTEMPT_NOT_SUCCESS_OR_EFFECT'})
        elif source['kind'] == 'text' and event.role == 'assistant':
            texts.append({'source_id':sid,'speaker':event.role.upper(),'text':store.text(sid)})
    users = [s for s in store.sources.values()
             if s['document']=='prompt' and s['role']=='user' and s['kind']=='text']
    latest = max(users,key=lambda s:s['start']) if users else None
    return {'text_segments':texts, 'native_calls':calls,
            'latest_user':{'source_id':latest['id'],'text':store.text(latest['id'])} if latest else None}


def validate_parse(store, value):
    parsed = MoveParse.model_validate(value).model_dump()
    packet = input_packet(store)
    acts, ids, covered = list(packet['native_calls']), set(), set()
    for act in parsed['acts']:
        if act['id'] in ids or act['id'].startswith('native:'):
            raise ValueError('duplicate or reserved text-act ID')
        ids.add(act['id'])
        ref = store.resolve_quote(act['evidence'])
        # The conversation role is observable syntax, not a semantic question
        # for the model. Bind by exact span containment even for raw/q refs.
        sources=[s for s in store.sources.values() if s['document']=='response'
                 and s['kind']=='text' and s['role']=='assistant'
                 and s['start']<=ref['start'] and ref['end']<=s['end']]
        if ref['document']!='response' or len(sources)!=1:
            raise ValueError('text act must reference assistant text, never a tool call')
        act['model_speaker']=act['speaker']
        act['speaker']=sources[0]['role'].upper()
        act['speaker_basis']='CODE_SOURCE_ROLE'
        if act['act']=='ASSERT_DONE' and act['modality']!='CLAIMED_COMPLETED':
            raise ValueError('completion claim requires CLAIMED_COMPLETED modality')
        if act['act'] in ('OFFER_FUTURE','OFFER_ESCALATION') and act['modality'] not in ('FUTURE','CONDITIONAL'):
            raise ValueError('offer requires future or conditional modality')
        if act['act'].startswith('ASK_') and act['modality']!='REQUEST':
            raise ValueError('request requires REQUEST modality')
        if act['act']=='ASK_USER_ACTION' and act['performer']!='USER':
            raise ValueError('user-action request requires USER performer')
        if any(not literal or literal not in ref['quote'] for literal in act['entity_literals']):
            raise ValueError('entity literal absent from exact act span')
        acts.append({**act,'verified_evidence':ref,'status':'MODEL_CLASSIFIED_EXACT_SOURCE'})
        covered.update(range(ref['start'],ref['end']))
    intent = parsed['intent']
    if intent['status']!='EXPLICIT' and intent['requested_action'] is not None:
        raise ValueError('ambiguous intent cannot acquire an invented action')
    if intent['status']=='EXPLICIT' and not intent['requested_action']:
        raise ValueError('explicit intent requires an action hypothesis')
    if intent['evidence'] is not None:
        ref = store.resolve_quote(intent['evidence'])
        latest = packet['latest_user']
        latest_source=store.sources[latest['source_id']] if latest else None
        if (latest_source is None or ref['document']!='prompt'
                or not latest_source['start']<=ref['start']<ref['end']<=latest_source['end']):
            raise ValueError('intent must cite the latest user request')
        intent['verified_evidence']=ref
    elif intent['status']!='UNKNOWN':
        raise ValueError('known intent requires latest-user evidence')
    missing = []
    for text in packet['text_segments']:
        source=store.sources[text['source_id']]
        missing.extend(i for i in range(source['start'],source['end'])
                       if store.raw['response'][i].isalnum() and i not in covered)
    issues = (['uncovered_target_text'] if missing else [])
    issues += ['invalid_native_call_arguments'] if any(not c['json_valid'] for c in packet['native_calls']) else []
    issues += ['unknown_target_act'] if any(a['act']=='UNKNOWN' for a in acts) else []
    issues += ['unknown_action_performer'] if any(a['performer']=='UNKNOWN' and a['act'] not in ('ASSERT_FACT','UNKNOWN') for a in acts) else []
    return {'acts':acts,'intent':intent,'issues':issues,'uncovered_material_chars':len(missing),
            'source_sha256':store.source_sha256,'semantic_classification_proven':False,
            'status':'COMPLETE_SOURCE_COVERAGE' if not issues else 'INCOMPLETE_SCOPE'}


def check_binding(store, frame, finding):
    """Reject mismatched hypotheses, without asserting entailment on a match."""
    binding=finding.get('scope_binding')
    if not isinstance(binding,dict):
        return {'status':'UNKNOWN','reason':'missing_scope_binding'}
    acts={a['id']:a for a in frame['acts']}
    act=acts.get(binding.get('act_id'))
    if act is None:
        return {'status':'UNKNOWN','reason':'finding_has_no_such_target_act'}
    if act['act']!=binding.get('governed_act') or act['modality']!=binding.get('governed_modality'):
        return {'status':'MISMATCH','reason':'rule_trigger_and_target_act_differ'}
    if act['performer']!=binding.get('governed_performer'):
        return {'status':'MISMATCH','reason':'rule_governs_another_performer'}
    if act['act']=='ATTEMPT_TOOL':
        if act['tool']!=binding.get('governed_tool'):
            return {'status':'MISMATCH','reason':'rule_governs_another_tool'}
    elif binding.get('governed_tool') is not None:
        return {'status':'UNKNOWN','reason':'text_action_to_tool_semantics_not_established'}
    try:
        policy=store.resolve_quote(binding['policy_evidence'])
        sources=[s for s in store.sources.values() if s['role']=='system' and s['document']=='prompt'
                 and s['start']<=policy['start'] and policy['end']<=s['end']]
        if not sources:
            raise ValueError('governed rule must be a system-policy span')
        target=store.resolve_quote({'source_id':'response','quote':finding['response_quote']})
        ref=act.get('verified_evidence') or act['evidence']
        if target['end']<=ref['start'] or target['start']>=ref['end']:
            return {'status':'MISMATCH','reason':'finding_quotes_another_target_span'}
    except (ValueError,KeyError,TypeError) as exc:
        return {'status':'UNKNOWN','reason':str(exc)}
    return {'status':'COMPATIBLE_NOT_ENTAILED','act_id':act['id'],'policy_evidence':policy}


def apply_scope_gate(store, frame, vote, assessment):
    bindings=[check_binding(store,frame,f) for f in vote.get('findings',[])]
    result={**assessment,'scope_bindings':bindings,'move_scope':frame}
    failures=[b for b in bindings if b['status']!='COMPATIBLE_NOT_ENTAILED']
    if assessment['decision']!='UNKNOWN' and (frame['issues'] or failures):
        result.update(decision='UNKNOWN',proposed_decision=assessment['decision'],
                      reason='typed_scope_incomplete_or_mismatched')
    return result
