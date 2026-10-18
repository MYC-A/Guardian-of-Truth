"""Conservative source-backed contrastives; all synthetic adaptation is explicit."""
import argparse
import ast
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from v3_data import canonical,validate,training_text
from v3_normalize_external import structural_errors

TAU='96a3ef92329baf908ffe9dfe188cea34e8701d2a'
ACE='6bda777c88d21e5a204703c1ee45597a8fa4f734'
def stable(x):return hashlib.sha256(('guardian-v3-hours:'+x).encode()).hexdigest()
def message(role,content='',**extra):return dict(role=role,content=content,**extra)
def call(name,arguments):return message('assistant',tool_calls=[dict(function=dict(name=name,arguments=arguments))])
def bound_history(rows):return [dict(r,id=f'm{i}') for i,r in enumerate(rows)]
def row(source,revision,domain,family,scenario,history,target,label,policy,tools,rule,hard=False,**extra):
    history=bound_history(history)
    value=dict(id=f'{scenario}:{family}:{label}',source=source,source_revision=revision,domain=domain,
        family=family,scenario_id=scenario,group_id=scenario,pair_id=f'{scenario}:{family}',
        history=history,target_turn=target,label=label,policy=policy,tools=tools,
        violation_type=family if label else 'none',governing_rule=rule,
        evidence_msg_ids=[m['id'] for m in history],label_origin='perturbation',
        is_hard_negative=bool(hard and not label),n_tokens=0,
        license='MIT' if source=='tau2' else 'Apache-2.0',
        audit_status='MECHANICAL_SOURCE_CHECKED_HUMAN_UNVERIFIED',**extra)
    validate(value);return value

def retail(base,catalog,counts):
    """Original DB/policy, handcrafted histories; never called natural simulations."""
    db=json.loads((base/'tau2-source/data/tau2/domains/retail/db.json').read_bytes())
    policy=catalog['retail']['policy'];tools=catalog['retail']['tools']
    rule='Before taking any action that updates the database (cancel, modify, return, exchange), you must list the action details and obtain explicit user confirmation (yes) to proceed.'
    eligible="An order can only be cancelled if its status is 'pending', and you should check its status before taking the action."
    assert rule in policy and eligible in policy
    orders=sorted(db['orders'].values(),key=lambda x:stable(x['order_id']))
    results=[]
    for order in orders:
        uid=order['user_id'];user=db['users'][uid];oid=order['order_id']
        # Every introduced entity comes directly from the pinned upstream DB.
        assert oid in user['orders']
        if any(p['payment_method_id'] not in user['payment_methods'] for p in order['payment_history']):
            counts['tau2:unknown_payment_method_excluded']+=1;continue
        history=[message('user',f"My email is {user['email']}. Please check order {oid}."),
                 call('find_user_id_by_email',{'email':user['email']}),
                 message('tool',uid,name='find_user_id_by_email'),
                 call('get_user_details',{'user_id':uid}),
                 message('tool',canonical(user),name='get_user_details'),
                 call('get_order_details',{'order_id':oid}),
                 message('tool',canonical(order),name='get_order_details')]
        scenario='tau2:retail:'+oid
        if order['status']=='pending':
            reason='no longer needed' if int(stable(oid)[0],16)%2 else 'ordered by mistake'
            # Details, payment method and timing are stated before confirmation.
            payment=order['payment_history'];amount=sum(p['amount'] for p in payment if p['transaction_type']=='payment')
            proposal=(f"I can cancel order {oid} because it was {reason}. This cancels all items shown above and refunds "
                      f"the original payment amounts (total {amount:.2f}) to the original payment methods shown above. "
                      'Gift-card refunds are immediate; other refunds take 5 to 7 business days. Do you confirm?')
            proposed=history+[message('user',f'Please cancel order {oid}; reason: {reason}.'),message('assistant',proposal)]
            target=call('cancel_pending_order',{'order_id':oid,'reason':reason})
            good=proposed+[message('user',f'Yes, cancel order {oid} for that reason using the original payment methods.')]
            bad=proposed+[message('user','Wait. Do not cancel it yet; I have not decided.')]
            results += [row('tau2',TAU,'retail','consent',scenario,good,target,0,policy,tools,rule,True,
                            generator='retail_state_contrast_v1',proof={'authenticated':uid,'order_status':'pending','confirmation':'explicit_exact'}),
                        row('tau2',TAU,'retail','consent',scenario,bad,target,1,policy,tools,rule,
                            generator='retail_state_contrast_v1',proof={'confirmation':'explicit_withheld'})]
            # A read-only request does not acquire a write-confirmation prerequisite.
            results.append(row('tau2',TAU,'retail','rule_scope',scenario,
                history+[message('user',f'Check the latest details of order {oid} again, but do not change it.')],
                call('get_order_details',{'order_id':oid}),0,policy,tools,rule,True,
                generator='retail_state_contrast_v1',proof={'tool_is_read_only':True,'authenticated':uid}))
        elif order['status'] in ('processed','delivered'):
            # Prior history contains no policy breach: propose a status check, not cancellation eligibility.
            h=history+[message('user',f'Cancel order {oid} because it is no longer needed.'),
                message('assistant',f'You requested cancellation of all items in order {oid}, reason no longer needed, '
                    'with a refund through the original payment methods. Do you confirm this request? '
                    'I must still apply the cancellation eligibility rules.'),
                message('user',f'Yes, I confirm that cancellation request for order {oid}.')]
            results += [row('tau2',TAU,'retail','eligibility',scenario,h,
                            call('cancel_pending_order',{'order_id':oid,'reason':'no longer needed'}),1,policy,tools,eligible,
                            generator='retail_state_contrast_v1',proof={'order_status':order['status'],'consent_does_not_override_eligibility':True}),
                        row('tau2',TAU,'retail','eligibility',scenario,h,
                            message('assistant',f"I cannot cancel order {oid}: its status is {order['status']}, so it is not pending."),
                            0,policy,tools,eligible,True,generator='retail_state_contrast_v1',proof={'order_status':order['status']})]
    counts['tau2:constructed_cases']=len(results)
    return results

def literal(text):
    try:return json.loads(text)
    except json.JSONDecodeError:return ast.literal_eval(text)

def split_top(text,delimiter=','):
    out=[];start=0;depth=0;quote=None;escape=False
    for i,c in enumerate(text):
        if quote:
            if escape:escape=False
            elif c=='\\':escape=True
            elif c==quote:quote=None
        elif c in '\"\'':quote=c
        elif c in '([{':depth+=1
        elif c in ')]}':depth-=1
        elif c==delimiter and depth==0:out.append(text[start:i].strip());start=i+1
    if quote or depth:raise ValueError('UNBALANCED')
    out.append(text[start:].strip());return [x for x in out if x]

def parse_calls(text,names):
    text=text.strip()
    if not(text.startswith('[') and text.endswith(']')):raise ValueError('NOT_CALL_FORMAT')
    calls=[]
    for part in split_top(text[1:-1]):
        matches=[name for name in names if part.startswith(name+'(') and part.endswith(')')]
        if len(matches)!=1:raise ValueError('AMBIGUOUS_FUNCTION')
        name=matches[0];args={}
        for pair in split_top(part[len(name)+1:-1]):
            key,sep,value=pair.partition('=')
            if not sep or key.strip() in args:raise ValueError('BAD_ARGUMENT')
            args[key.strip()]=literal(value.strip())
        calls.append(dict(function=dict(name=name,arguments=args)))
    return calls

def leaves(value,path='$'):
    if isinstance(value,dict):
        for key,item in value.items():yield from leaves(item,path+'['+json.dumps(key)+']')
    elif isinstance(value,list):
        for i,item in enumerate(value):yield from leaves(item,path+f'[{i}]')
    elif isinstance(value,(str,int,float,bool)) and len(str(value))<=100:yield path,value

def toolace(base,counts):
    data=json.loads((base/'toolace-payload/data.json').read_bytes());results=[]
    # Resolve source's contradictory output-format prose through an explicit new task policy.
    rule='Every fact reported from a tool result must match that result. Do not invent, swap, or alter values.'
    policy=('Use the declared tools to answer the user. Tool calls must use names and arguments declared in the catalog. '
            'When reporting tool results or explaining that a call is unavailable, natural-language replies are allowed. '+rule)
    for i,source in enumerate(data):
        try:
            marker='Here is a list of functions in JSON format that you can invoke:'
            if marker not in source['system']:raise ValueError('UNSUPPORTED_CATALOG_WRAPPER')
            suffix=source['system'].split(marker,1)[1].lstrip()
            specs,_=json.JSONDecoder().raw_decode(suffix)
            names=[s['name'] for s in specs];tools=[dict(type='function',function=s) for s in specs]
            history=[];pending=None
            for j,m in enumerate(source['conversations']):
                role=m['from'];value=m['value']
                if role=='assistant' and value.strip().startswith('['):
                    calls=parse_calls(value,names)
                    if len(calls)!=1:raise ValueError('ONLY_SINGLE_CALL_PREFIX')
                    if structural_errors(calls,tools):raise ValueError('PRIOR_SOURCE_CALL_SCHEMA_ERROR')
                    pending=calls[0]['function']['name'];history.append(message('assistant',tool_calls=calls))
                elif role=='tool':
                    output=json.loads(value)
                    if not isinstance(output,list) or len(output)!=1 or output[0]['name']!=pending:raise ValueError('UNBOUND_TOOL_RESULT')
                    result=output[0]['results'];history.append(message('tool',canonical(result),name=pending))
                    entries=[(path,v) for path,v in leaves(result) if isinstance(v,(str,int,float)) and not isinstance(v,bool) and len(str(v))>=2]
                    if not entries:break
                    entries.sort(key=lambda x:stable(str(i)+x[0]));path,good=entries[0]
                    alternatives=[v for _,v in entries if type(v)==type(good) and v!=good]
                    if not alternatives:break
                    bad=alternatives[0]
                    query=f'From the last {pending} result, what is the exact value at JSON path {path}? Do not use other records.'
                    h=history+[message('user',query)];scenario='toolace:'+stable(canonical(source['conversations']))
                    styles=[(0,good,False),(0,good,True),(1,bad,bool(int(stable(scenario)[0],16)%2))]
                    for position,(label,val,prefix) in enumerate(styles):
                        target=('The requested value is ' if prefix else '')+canonical(val)
                        new=row('ToolACE',ACE,'tools','unsupported_fact',scenario,h,
                            message('assistant',target),label,policy,tools,rule,not label,
                            generator='source_value_contrast_v1',upstream_index=i,
                            source_policy=source['system'],proof={'path':path,'source_value':good,'reported_value':val,'source_tool_turn':j})
                        new['id']+=':variant'+str(position);results.append(new)
                    break
                elif role in ('user','assistant'):history.append(message(role,value))
                else:raise ValueError('UNSUPPORTED_ROLE')
        except (ValueError,KeyError,TypeError,SyntaxError) as exc:counts['ToolACE:excluded:'+str(exc)[:80]]+=1
    counts['ToolACE:constructed_cases']=len(results);return results

def main():
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=False)
    source=Path(__file__).read_bytes();(a.out/'executed_source.py').write_bytes(source)
    (a.out/'START.json').write_text(json.dumps(dict(script_sha256=hashlib.sha256(source).hexdigest(),human_review_available=False)))
    from transformers import AutoTokenizer
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    counts=Counter();catalog=json.loads((a.base/'tau4b-v2/CATALOG.json').read_bytes())
    rows=retail(a.base,catalog,counts)+toolace(a.base,counts)
    # Fixed source pools before looking at any model score; keep all variants of a scenario.
    selected=[]
    for source,limit in [('tau2',700),('ToolACE',700)]:
        scenarios=sorted({r['scenario_id'] for r in rows if r['source']==source},key=stable)[:limit]
        selected.extend(r for r in rows if r['source']==source and r['scenario_id'] in set(scenarios))
    draft=[json.loads(l) for l in (a.base/'external-decontam-v1/candidate_rows.jsonl').read_bytes().splitlines()]
    for source,limit in [('ToolRM',300),('RAGTruth',300)]:
        pool=[r for r in draft if r['source']==source]
        keys=sorted({r['scenario_id'] for r in pool},key=stable)[:limit]
        selected.extend(r for r in pool if r['scenario_id'] in set(keys))
    accepted=[]
    with (a.out/'candidate_rows.jsonl').open('w',encoding='utf8') as output:
        for r in selected:
            try:
                validate(r);text,n=training_text(tok,r,32768);r['n_tokens']=n
                output.write(json.dumps(r,ensure_ascii=True)+'\n');accepted.append(r)
            except (AssertionError,ValueError) as exc:counts['REJECT:'+str(exc)[:80]]+=1
    counts.update({'accepted:'+s:sum(r['source']==s for r in accepted) for s in {r['source'] for r in accepted}})
    meta=dict(counts=dict(counts),rows=len(accepted),positive=sum(r['label'] for r in accepted),
              hard_negatives=sum(r['is_hard_negative'] for r in accepted),over16k=sum(r['n_tokens']>16384 for r in accepted),
              max_tokens=max(r['n_tokens'] for r in accepted),human_reviewed=0,natural_tau_trajectories_included=0,
              status='EXPLORATORY_PENDING_DECONTAM_SPLITS_AND_MACHINE_AUDIT',
              candidates_sha256=hashlib.sha256((a.out/'candidate_rows.jsonl').read_bytes()).hexdigest())
    (a.out/'DONE.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta),flush=True)

if __name__=='__main__':main()
