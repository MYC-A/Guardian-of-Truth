"""Code-grounded source-ID assessment interface over the same investigation loop.

The IDs establish provenance only. They do not certify semantic applicability,
missing alternatives, policy completeness or the model's final interpretation.
"""
import json
from .pipeline import QUESTIONS, contract, run
from .store import SourceStore


def id_contract(phase, *, checks_mode='legacy'):
    original=contract(phase, checks_mode=checks_mode)
    if phase=='SEARCH':return original
    header=original.split('Assessment schema:',1)[0]
    example={'assessment':{'decision':'ERROR|NO_ERROR|UNKNOWN','explanation':'specific reason',
        'findings':[{'type':'CONTRADICTION|UNSUPPORTED|OTHER','target_source_id':'t0',
                     'explanation':'a specific error in THIS latest event','evidence_ids':['h0','q0']}],
        'checks':{question:{'status':'CHECKED|NOT_APPLICABLE|OPEN','reason':'specific reason',
                            'evidence_ids':['h0']} for question in QUESTIONS},'open_questions':[]}}
    text = header+'''Assessment schema: '''+json.dumps(example)+'''
The source-ID registry gives stable events and source offsets. Select only IDs
that exist in the registry or were returned by operations. Code supplies exact
source text; never recopy quotations. t-prefixed events are the current response;
h-prefixed events are earlier context. Both roles and native tool calls are
provided by code. A previous lookup is not the current action. The assistant's
explanations about why it acted correctly are claims to verify, not evidence.
Do not infer inspection-only intent from a broad help request. Distinguish who
performs a described act, future timing and conditionality; these are independent
properties. A claim of completion does not prove successful execution.
checks is an OBJECT with exactly the five named keys. A CHECKED or
NOT_APPLICABLE check needs a concrete reason and source IDs; use current target
IDs for checks whose nonapplicability follows from the actual move. OPEN means
missing evidence for the evaluator, not that the assistant omitted a required
step. An evidenced omitted required step may be an ERROR. Test whether the
policy governs THIS action, all AND/OR conditions on the SAME entity, relevant
exceptions, permissible alternatives, and arithmetic via calculate when needed.
The five check labels are bookkeeping, not a proof of complete NL understanding.
ERROR requires a specific finding; NO_ERROR has no findings. Known material
uncertainty remains UNKNOWN. Do not introduce errors simply to fill a finding.
Return one schema JSON object and no surrounding prose.'''
    if checks_mode == 'diagnostic':
        text = text.replace('A CHECKED or\nNOT_APPLICABLE check needs a concrete reason and source IDs;',
            'A CHECKED check needs a concrete reason and source IDs; NOT_APPLICABLE may omit IDs;')
        text += '\nChecks are diagnostic. Missing check evidence does not change an independently supported decision.'
    return text


def registry(store):
    # No duplicate raw text. Full sources remain accessible through the store.
    return [{k:s[k] for k in ('id','document','role','kind','tool','start','end')}
            for s in store.sources.values() if s['kind']!='raw']


def native_target_inventory(store):
    return [{'source_id':sid,'tool':store.target_events[s['event']].name,
             'arguments':store.target_events[s['event']].value,
             'status':'ATTEMPT_NOT_COMPLETED_EFFECT'}
            for sid,s in store.sources.items() if s['document']=='response' and s['kind']=='call']


def references(store,ids):
    if not isinstance(ids,list) or any(not isinstance(sid,str) for sid in ids):
        raise ValueError('evidence_ids must be a list of registered IDs')
    if len(ids)!=len(set(ids)):
        raise ValueError('duplicate evidence ID')
    result=[]
    for sid in ids:
        if sid not in store.sources and sid not in store.quotes:
            raise ValueError('unregistered evidence ID: '+sid)
        result.append({'source_id':sid,'quote':store.text(sid)})
    return result


def decode_assessment(store,vote):
    if not isinstance(vote,dict):raise ValueError('assessment must be an object')
    checks=vote.get('checks')
    if not isinstance(checks,dict) or set(checks)!=set(QUESTIONS):
        raise ValueError('checks must contain exactly the five question keys')
    findings=vote.get('findings',[])
    if not isinstance(findings,list):raise ValueError('findings must be a list')
    normalized=[]
    for finding in findings:
        sid=finding.get('target_source_id')
        source=store.sources.get(sid)
        if not source or source['document']!='response' or source['kind']=='raw':
            raise ValueError('finding must bind a registered latest target event')
        normalized.append({'type':finding.get('type'),'response_quote':store.text(sid),
            'explanation':finding.get('explanation'),
            'evidence':references(store,finding.get('evidence_ids')),
            'target_source_id':sid})
    return {'decision':vote.get('decision'),'explanation':vote.get('explanation'),
        'findings':normalized,'checks':[{'question_id':question,'status':check.get('status'),
            'reason':check.get('reason'),'evidence':references(store,check.get('evidence_ids'))}
            for question,check in checks.items()],
        'open_questions':vote.get('open_questions',[]),'original_source_id_vote':vote}


def run_ids(row,ask,*,mode='search',max_steps=6,max_payload_bytes=800000,checks_mode='legacy'):
    store=SourceStore(row)
    return run(row,ask,mode=mode,max_steps=max_steps,max_payload_bytes=max_payload_bytes,
        policy_first=True,source_store=store,contract_builder=lambda phase:id_contract(phase,checks_mode=checks_mode),
        checks_mode=checks_mode,
        assessment_decoder=decode_assessment,
        initial_context={'source_registry':registry(store),
                         'native_target_calls':native_target_inventory(store)})
