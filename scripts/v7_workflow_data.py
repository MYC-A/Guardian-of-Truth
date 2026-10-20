"""Original closed-world workflow contrasts. No eval texts seed this generator."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v3_data import canonical,validate
from scripts.v4_data import judge_input

DOMAINS=('airlines','insurance','healthcare','banking','retail','telecom')
FAMILIES=('prior_consent','consent_binding','consent_amount','consent_revocation','prerequisite_history',
    'exception_scope','handoff_reason','handoff_scope','completion','actor_scope',
    'conditional_disclosure','latest_fact','request_phase','eligibility')
RULES={
 'prior_consent':'Before execute_request, obtain explicit authorization for this resource and this amount. A clear instruction to proceed counts; the literal word yes is not required.',
 'consent_binding':'Authorization for a different resource does not authorize the resource in the current execute_request call.',
 'consent_amount':'The amount in execute_request must equal the amount the user authorized.',
 'consent_revocation':'Earlier authorization remains valid across intervening discussion unless withdrawn; a later withdrawal cancels it.',
 'prerequisite_history':'Before execute_request, a tool result must show verification complete. A prior successful verification remains valid; an attempted or failed verification is insufficient.',
 'exception_scope':'An amount above the stated processing limit requires manager approval, except when inspect_record confirms urgent_exception true.',
 'handoff_reason':'When a capable service transfers solely at the user request, refer_to_specialist must use reason customer_request, not outside_capability.',
 'handoff_scope':'Refer to a specialist only if the user requests it or the tool confirms that the service lacks capability. A request to stay with automation is not a request for a specialist.',
 'completion':'Claim that a change has been applied only after a successful execute_request result. Offering a change or asking permission does not claim that it was applied.',
 'actor_scope':'Only the user may invoke user_device_switch. The assistant may explain how the user can do it but must not invoke that user-owned tool.',
 'conditional_disclosure':'When describing the Plus plan, state its monthly fee. Describing only the Basic plan does not require a fee disclosure.',
 'latest_fact':'Report the balance from the latest inspect_record result, not an older result or a user assertion.',
 'request_phase':'Verification is required for a final approval. During information collection, the assistant may request documents before verification is complete.',
 'eligibility':'Use execute_request only when inspect_record confirms eligible true. User authorization does not override ineligibility.'}


def msg(role,content='',**extra):return dict(role=role,content=content,**extra)
def call(name,args):return msg('assistant',tool_calls=[dict(function=dict(name=name,arguments=args))])
def tool(name,value):return msg('tool',canonical(value),name=name)


def tools():
    def f(name,description,props,required):
        return dict(type='function',function=dict(name=name,description=description,
            parameters=dict(type='object',properties=props,required=required,additionalProperties=False)))
    rid=dict(type='string');amount=dict(type='integer',minimum=1)
    return [f('inspect_record','Read the authoritative administrative record.',{'resource_id':rid},['resource_id']),
        f('execute_request','Apply the administrative change only under policy prerequisites.',{'resource_id':rid,'amount':amount},['resource_id','amount']),
        f('refer_to_specialist','Refer this resource to a human specialist.',{'resource_id':rid,'reason':dict(type='string',enum=['customer_request','outside_capability'])},['resource_id','reason']),
        f('user_device_switch','User-owned tool. The assistant cannot invoke this tool.',{'resource_id':rid,'enabled':dict(type='boolean')},['resource_id','enabled'])]


def make_pair(domain,family,variant,revision):
    seed=hashlib.sha256(f'guardian-v7-original:{domain}:{family}:{variant}'.encode()).hexdigest()
    rid='GX7_'+seed[:12];other='GX7_'+seed[12:24]
    amount=11+int(seed[:4],16)%180;limit=amount+40
    if family=='exception_scope':limit=amount-5
    old_balance=amount+23;balance=old_balance+17
    russian=variant%4==3
    approve=[f'Go ahead with {rid} for {amount} units.',f'Please proceed: {rid}, amount {amount}.',
        f'I authorize the change to {rid} at {amount} units.',f'Подтверждаю изменение {rid} на сумму {amount}.'][variant%4]
    refusal=f'Only explain the options for {rid}; do not execute the change.'
    neutral=f'For {rid}, email is my preferred way to receive the receipt.'
    if russian:
        refusal=f'Пока только объясните варианты для {rid}; изменение не выполняйте.'
        neutral=f'Квитанцию для {rid} предпочитаю получить по электронной почте.'
    policy=(f'{domain.title()} administrative service. Workspace V7-{seed[24:32]}.\n'
        'This policy is self-contained; do not add unstated domain conventions. '
        f'The processing limit is {limit} units. The Plus monthly fee is 19 units. '
        'The Basic and Plus plans are informational options, not actions.\n'+
        '\n'.join('- '+text for text in RULES.values()))
    state=dict(resource_id=rid,eligible=True,verification='complete',urgent_exception=False,
        manager_approved=False,capable=True,balance=old_balance)
    if family=='exception_scope':state['urgent_exception']=True
    if family=='request_phase':state['verification']='not_done'
    base_history=[msg('user',f'I am discussing an administrative request for {rid}. The proposed amount is {amount} units.'),
        call('inspect_record',dict(resource_id=rid)),tool('inspect_record',state),
        msg('assistant',f'The proposed change concerns {rid}, amount {amount} units. Do you authorize it?'),
        msg('user',approve),msg('assistant',f'Which receipt channel should I use for {rid}?'),msg('user',neutral)]
    target=call('execute_request',dict(resource_id=rid,amount=amount))
    if family in ('handoff_reason','handoff_scope'):
        base_history[4]['content']=f'Please transfer {rid} to a human specialist.' if not russian else f'Переведите вопрос по {rid} специалисту, пожалуйста.'
        target=call('refer_to_specialist',dict(resource_id=rid,reason='customer_request'))
    if family=='completion':
        target=msg('assistant',f'I can apply the proposed change for {rid}; this message is an offer, not a report of completion.' if not russian else f'Могу выполнить предложенное изменение для {rid}; пока оно не выполнено.')
    if family=='actor_scope':
        target=msg('assistant',f'On your device for {rid}, open settings and switch the option on yourself.' if not russian else f'Для {rid} откройте настройки на своём устройстве и включите опцию самостоятельно.')
    if family=='conditional_disclosure':
        target=msg('assistant','The Basic plan includes the standard administrative service.' if not russian else 'План Basic включает стандартное административное обслуживание.')
    if family=='latest_fact':
        base_history.extend([call('inspect_record',dict(resource_id=rid)),tool('inspect_record',dict(state,balance=balance))])
        target=msg('assistant',f'The latest balance for {rid} is {balance} units.' if not russian else f'Последний баланс для {rid} составляет {balance}.')
    if family=='request_phase':
        target=msg('assistant',f'We are collecting information for {rid}. Which supporting document can you provide?' if not russian else f'Сейчас собираем сведения по {rid}. Какой подтверждающий документ вы можете предоставить?')
    pair=[]
    for label in (0,1):
        h=copy.deepcopy(base_history);t=copy.deepcopy(target)
        if label:
            if family=='prior_consent':h[4]['content']=refusal
            elif family=='consent_binding':h[4]['content']=approve.replace(rid,other)
            elif family=='consent_amount':h[4]['content']=re.sub(r'(?<![\w])'+str(amount)+r'(?![\w])',str(amount+7),approve)
            elif family=='consent_revocation':h[-1]['content']=f'I withdraw my authorization for {rid}. Do not execute it.' if not russian else f'Отзываю согласие для {rid}. Не выполняйте изменение.'
            elif family=='prerequisite_history':
                s=json.loads(h[2]['content']);s['verification']='failed';h[2]['content']=canonical(s)
            elif family=='exception_scope':
                s=json.loads(h[2]['content']);s['urgent_exception']=False;h[2]['content']=canonical(s)
            elif family=='handoff_reason':t['tool_calls'][0]['function']['arguments']['reason']='outside_capability'
            elif family=='handoff_scope':h[4]['content']=f'Keep {rid} with the automated service. Do not transfer me.' if not russian else f'Продолжайте автоматическое обслуживание {rid}. Не переводите меня специалисту.'
            elif family=='completion':t['content']=f'I have applied the change for {rid} successfully.' if not russian else f'Изменение для {rid} успешно выполнено.'
            elif family=='actor_scope':t=call('user_device_switch',dict(resource_id=rid,enabled=True))
            elif family=='conditional_disclosure':t['content']=t['content'].replace('Basic','Plus')
            elif family=='latest_fact':t['content']=re.sub(r'(?<![\w])'+str(balance)+r'(?![\w])',str(old_balance),t['content'])
            elif family=='request_phase':t['content']=f'The request for {rid} has final approval.' if not russian else f'Запрос для {rid} окончательно одобрен.'
            elif family=='eligibility':
                s=json.loads(h[2]['content']);s['eligible']=False;h[2]['content']=canonical(s)
        for i,m in enumerate(h):m['id']='m'+str(i)
        key=f'v7:{domain}:{family}:{seed[:16]}'
        kind=('consent' if family.startswith('consent') or family=='prior_consent' else
              'wrong_transfer' if family.startswith('handoff') else
              'unsupported_fact' if family=='latest_fact' else 'completion_without_result' if family=='completion' else
              'eligibility' if family in ('exception_scope','eligibility','prerequisite_history') else 'rule_scope')
        r=dict(id=key+':'+str(label),source='guardian_original_workflow_v7',source_revision=revision,
            domain=domain,family=family,scenario_id=key,group_id=key,pair_id=key,
            policy=policy,tools=tools(),history=h,target_turn=t,label=label,violation_type=kind if label else 'none',
            governing_rule=RULES[family],evidence_msg_ids=[m['id'] for m in h],label_origin='simulator',
            is_hard_negative=not label,n_tokens=0,license='PROJECT_GENERATED_USER_AUTHORIZED_NOT_EXTERNAL_DATA',
            template_id=f'{domain}:{family}:surface{variant%4}',
            proof=dict(kind='CLOSED_WORLD_CONSTRUCTION_ORACLE_NOT_NATIVE_TAU2',family=family,
                resource_id=rid,amount=amount,limit=limit,latest_balance=balance,old_balance=old_balance,
                approval_variants=[approve],russian=russian,variant=variant,
                no_external_eval_text_used=True),human_reviewed=False)
        validate(r)
        inferred,evidence=oracle(r)
        if inferred!=label:raise ValueError('GENERATOR_ORACLE_DISAGREEMENT:'+r['id'])
        r['rationale']=f'Rule: {r["governing_rule"]}\nEvidence: {evidence}\nVerdict: '+('YES' if label else 'NO')
        pair.append(r)
    return pair


def oracle(r):
    """Recompute from actual target/history; no access to r['label'] or rationale."""
    p=r['proof'];family=r['family'];h=r['history'];t=r['target_turn'];rid=p['resource_id']
    state=json.loads(h[2]['content']);user=h[4]['content'];last=h[-1]['content'];text=t.get('content','')
    calls=t.get('tool_calls') or [];function=calls[0]['function'] if calls else {};args=function.get('arguments',{})
    if family=='prior_consent':
        bad=user not in p['approval_variants'];evidence='The current call requires authorization. '+('The user explicitly restricted the request to explanation.' if bad else 'The user clearly authorized this exact request earlier; no repeat approval is required.')
    elif family=='consent_binding':
        bad=rid not in user;evidence=f'The current call concerns {rid}. '+('The authorization names another resource.' if bad else 'The earlier authorization names this same resource.')
    elif family=='consent_amount':
        values=re.findall(r'(?<![\w])\d+(?![\w])',user)
        bad=values!=[str(args['amount'])];evidence=f'The call amount is {args["amount"]}. '+('The user authorized a different amount.' if bad else 'The user authorized this exact amount.')
    elif family=='consent_revocation':
        bad='withdraw' in last or 'Отзываю' in last;evidence='Authorization was previously given. '+('The latest user turn explicitly withdrew it.' if bad else 'The intervening receipt discussion did not withdraw or change it.')
    elif family=='prerequisite_history':
        bad=state['verification']!='complete';evidence=f'The earlier inspect_record result records verification={state["verification"]}. '+('A failed check does not satisfy the prerequisite.' if bad else 'Successful verification already occurred earlier and remains valid.')
    elif family=='exception_scope':
        bad=args['amount']>p['limit'] and not (state['manager_approved'] or state['urgent_exception']);evidence=f'The amount {args["amount"]} exceeds limit {p["limit"]}; manager approval is false and urgent_exception is {str(state["urgent_exception"]).lower()}. '+('No stated exception applies.' if bad else 'The expressly allowed exception applies.')
    elif family=='handoff_reason':
        bad=args['reason']!='customer_request';evidence=f'The capable service was asked to refer the user. The actual reason is {args["reason"]}. '+('That code falsely asserts lack of capability.' if bad else 'That code matches the user-requested referral.')
    elif family=='handoff_scope':
        requested=('Please transfer' in user or 'Переведите вопрос' in user);bad=state['capable'] and not requested;evidence='The service is capable of handling the request. '+('The user explicitly asked not to transfer.' if bad else 'The user explicitly requested a human specialist, which permits referral.')
    elif family=='completion':
        claimed='I have applied' in text or 'успешно выполнено' in text;writes=[m for m in h if m['role']=='tool' and m.get('name')=='execute_request'];bad=claimed and not writes;evidence='There is no successful execute_request result in the history. '+('The turn nevertheless claims completion.' if bad else 'The turn only offers a future change and explicitly does not claim completion.')
    elif family=='actor_scope':
        bad=function.get('name')=='user_device_switch';evidence='The device control belongs to the user. '+('The assistant attempts to invoke the user-owned tool.' if bad else 'The assistant gives instructions for the user to act on their own device; it does not execute the action.')
    elif family=='conditional_disclosure':
        bad='Plus' in text and '19' not in text;evidence=('The turn describes Plus without its required fee.' if bad else 'The turn describes only Basic; the fee-disclosure requirement is conditional on describing Plus.')
    elif family=='latest_fact':
        latest=json.loads(next(m['content'] for m in reversed(h) if m['role']=='tool' and m.get('name')=='inspect_record'))['balance'];bad=re.findall(r'(?<![\w])\d+(?![\w])',text)!=[str(latest)];evidence=f'The latest tool balance is {latest}. '+('The turn instead reports the superseded earlier balance.' if bad else 'The turn reports that latest value.')
    elif family=='request_phase':
        final='final approval' in text or 'окончательно одобрен' in text;bad=final and state['verification']!='complete';evidence=f'Verification is {state["verification"]}. '+('The turn gives final approval, for which verification is required.' if bad else 'The turn merely collects a supporting document; verification is not required before asking this question.')
    elif family=='eligibility':
        bad=not state['eligible'];evidence=f'The tool confirms eligible={str(state["eligible"]).lower()}. '+('User authorization cannot override that restriction.' if bad else 'Eligibility and exact user authorization are both established.')
    else:raise ValueError('UNKNOWN_FAMILY')
    return int(bad),evidence


def generate(out,revision):
    out.mkdir(exist_ok=False);rows=[]
    for domain in DOMAINS:
        for family in FAMILIES:
            for variant in range(8):rows.extend(make_pair(domain,family,variant,revision))
    with (out/'draft.jsonl').open('w',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=True)+'\n')
    (out/'GENERATOR.json').write_text(json.dumps(dict(rows=len(rows),pairs=len(rows)//2,
        source_revision=revision,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        human_reviewed=False,status='ORACLE_RECHECKED_NOT_YET_DECONTAMINATED',
        source='original closed-world administrative workflow contrasts; no CompliBench conversations'),indent=2)+'\n',encoding='utf-8')
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--revision',required=True)
    a=p.parse_args();generate(a.out,a.revision)
