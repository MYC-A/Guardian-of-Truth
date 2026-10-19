"""Conservative current-turn labels from local trajectories, never task reward.

Unknown prefixes are recorded, not implicitly labeled correct. Stop each source
trajectory after its first provable assistant violation. Source results used to
check read execution are receipts only, never appended after the current target.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tarfile

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
from jsonschema import Draft202012Validator
from v3_data import validate
from v4_data import judge_input
from v4_shape_gate import scan

PIN='96a3ef92329baf908ffe9dfe188cea34e8701d2a'


def canon(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def sha(x):return hashlib.sha256(x.encode()).hexdigest()


def convert(messages):
    names={};out=[]
    for i,m in enumerate(messages):
        row=dict(id='m'+str(i),role=m['role'],content=m.get('content') or '')
        calls=[]
        for c in m.get('tool_calls') or []:
            f=c.get('function',c);args=f['arguments']
            if isinstance(args,str):args=json.loads(args)
            calls.append(dict(function=dict(name=f['name'],arguments=args)))
            names[c['id']]=f['name']
        if calls:row['tool_calls']=calls
        if m['role']=='tool':row['name']=names[m['id']]
        out.append(row)
    return out


def observations(history):
    out=[]
    for m in history:
        if m['role']!='tool' or str(m['content']).startswith('Error:'):continue
        try:value=json.loads(m['content'])
        except (ValueError,TypeError):value=m['content']
        out.append((m['name'],value))
    return out


def safe_read(domain,function,history):
    """Sufficient narrow read permissions; not a general semantic verifier."""
    name=function['name'];a=function['arguments']
    user='\n'.join(m['content'] for m in history if m['role']=='user')
    observed=observations(history)
    if domain=='retail':
        if name in {'find_user_id_by_email','find_user_id_by_name_zip'}:
            return bool(a) and all(str(v).casefold() in user.casefold() for v in a.values())
        uids={v for n,v in observed if n in {'find_user_id_by_email','find_user_id_by_name_zip'} and isinstance(v,str)}
        if name=='get_user_details':return a.get('user_id') in uids
        profiles=[v for n,v in observed if n=='get_user_details' and isinstance(v,dict) and v.get('user_id') in uids]
        if name=='get_order_details':return any(a.get('order_id') in v['orders'] for v in profiles)
        if name=='get_product_details':return bool(profiles) and str(a.get('product_id','')) in canon(observed)
    if domain=='airline':
        if name=='get_user_details':return bool(a.get('user_id')) and a['user_id'] in user
        profiles=[v for n,v in observed if n=='get_user_details' and isinstance(v,dict) and v.get('user_id','!') in user]
        if name=='get_reservation_details':return any(a.get('reservation_id') in v['reservations'] for v in profiles)
        if name=='get_flight_status':return bool(profiles) and all(str(v) in canon(observed) for v in a.values())
    if domain=='telecom':
        if name in {'get_customer_by_phone','get_customer_by_id'}:
            return bool(a) and all(str(v) in user for v in a.values())
        profiles=[v for n,v in observed if n.startswith('get_customer_by_') and isinstance(v,dict)]
        if name=='get_details_by_id':
            ids=set()
            for v in profiles:ids.update(v.get('line_ids',[]));ids.update(v.get('bill_ids',[]))
            for n,v in observed:
                if isinstance(v,dict) and v.get('line_id') in ids:
                    ids.update(v.get(k) for k in ('plan_id','device_id') if v.get(k))
            return a.get('id') in ids
    return False


def classify(domain,policy,tools,history,target):
    request=judge_input(dict(id='probe',policy=policy,tools=tools,history=history,target_turn=target))
    shape=scan(request['prompt'],request['response'])
    if shape['violations']:
        return 1,'turn_shape',shape['violations'][0]['quote'],dict(shape=shape),'rule_scope'
    functions={t.get('function',t)['name']:t.get('function',t) for t in tools}
    calls=target.get('tool_calls',[])
    for c in calls:
        f=c['function']
        if f['name'] not in functions:
            q=next((q for q in ['You should not make up any information or knowledge or procedures not provided by the user or the tools, or give subjective recommendations or comments.',
                'You should not provide any information, knowledge, or procedures not provided by the user or available tools, or give subjective recommendations or comments.'] if q in policy),None)
            if q:return 1,'unknown_tool',q,dict(unavailable_tool=f['name'],catalog_names=sorted(functions)),'tool_args'
        else:
            errors=list(Draft202012Validator(functions[f['name']]['parameters']).iter_errors(f['arguments']))
            if errors:
                q=next((q for q in ['You should not make up any information or knowledge or procedures not provided by the user or the tools, or give subjective recommendations or comments.',
                    'You should not provide any information, knowledge, or procedures not provided by the user or available tools, or give subjective recommendations or comments.'] if q in policy),None)
                if q:return 1,'schema',q,dict(schema_errors=[e.message for e in errors]),'tool_args'
            if f['name']=='modify_pending_order_items' and len(f['arguments'].get('item_ids',[]))!=len(f['arguments'].get('new_item_ids',[])):
                q='For a pending order, each item can be modified to an available new item of the same product but of different product option. There cannot be any change of product types, e.g. modify shirt to shoe.'
                if q in policy:return 1,'modify_scope',q,dict(unequal_replacement_lengths=True),'rule_scope'
            if f['name'] in {'cancel_pending_order','modify_pending_order_items','return_delivered_order_items'}:
                oid=f['arguments'].get('order_id');order=next((v for n,v in reversed(observations(history)) if n=='get_order_details' and isinstance(v,dict) and v.get('order_id')==oid),None)
                required='delivered' if f['name'].startswith('return') else 'pending'
                verb={'cancel_pending_order':'cancelled','modify_pending_order_items':'modified','return_delivered_order_items':'returned'}[f['name']]
                q=f"An order can only be {verb} if its status is '{required}', and you should check its status before taking the action."
                # Do not infer current state from a stale read after a write.
                if order and order['status']!=required and q in policy and not any('tool_calls' in m and any(z['function']['name'] not in {'get_order_details','get_user_details','get_product_details','find_user_id_by_email','find_user_id_by_name_zip'} for z in m['tool_calls']) for m in history):
                    return 1,'order_status',q,dict(observed_status=order['status'],required=required),'eligibility'
    if len(calls)==1 and not target.get('content','').strip() and safe_read(domain,calls[0]['function'],history):
        q=next((q for q in ['You can only help one user per conversation (but you can handle multiple requests from the same user), and must deny any requests for tasks related to any other user.',
                           'The user must provide their user id.','You can look up customer information using:'] if q in policy),None)
        if q:return 0,'source_verified_read',q,dict(narrow_read_scope=True),'none'
    return None


def main():
    p=argparse.ArgumentParser();p.add_argument('--archives',type=Path,nargs='+',required=True)
    p.add_argument('--catalog',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=False)
    catalog=json.loads(a.catalog.read_bytes());rows=[];excluded=[];counts=Counter();trajectories=0
    for archive in a.archives:
        with tarfile.open(archive) as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith('.json'):continue
                x=json.loads(tar.extractfile(member).read())
                if not isinstance(x,dict) or 'simulation' not in x or not x.get('complete'):continue
                trajectories+=1;domain=x['domain'];policy=x['simulation']['policy'];tools=catalog[domain]['tools'];messages=x['simulation']['messages']
                try:converted=convert(messages)
                except Exception as e:excluded.append(dict(source=member.name,reason='UNBOUND_OR_MALFORMED_HISTORY',error=str(e)));continue
                prefix_unknown=False
                for i,(raw,target) in enumerate(zip(messages,converted)):
                    if raw['role']!='assistant' or raw.get('usage') is None:continue
                    history=converted[:i];decision=classify(domain,policy,tools,history,target)
                    if decision is None:
                        prefix_unknown=True;excluded.append(dict(source=member.name,turn=i,reason='SEMANTIC_SCOPE_UNRESOLVED'));continue
                    label,family,quote,proof,violation=decision
                    if not label:
                        next_results=[m for m in messages[i+1:] if m['role']=='tool']
                        callid=(raw.get('tool_calls') or [{}])[0].get('id')
                        receipt=next((m for m in next_results if m.get('id')==callid),None)
                        if receipt is None or receipt.get('error'):
                            prefix_unknown=True;excluded.append(dict(source=member.name,turn=i,reason='READ_EXECUTION_NOT_CONFIRMED'));continue
                        proof['execution_receipt_sha256']=sha(canon(receipt))
                    scenario='tau2-task:'+domain+':'+x['task_id'];rid='v4-natural:'+sha(member.name+':'+str(i))[:28]
                    row=dict(id=rid,source='tau2',source_revision=PIN,domain=domain,family=family,
                        template_id='natural:'+family,scenario_id=scenario,group_id=scenario,pair_id=rid,
                        policy=policy,tools=tools,history=history,target_turn=target,label=label,violation_type=violation,
                        governing_rule=quote,evidence_msg_ids=[m['id'] for m in history],label_origin='simulator',is_hard_negative=False,
                        n_tokens=0,license='MIT',natural_trajectory=True,human_reviewed=False,
                        source_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),source_member=member.name,
                        source_turn=i,model_config=x['config_name'],seed=x['seed'],proof=proof,
                        prefix_semantics_completely_verified=not prefix_unknown,first_provable_violation_only=True,
                        hidden_reference_or_reward_used_for_label=False)
                    validate(row);rows.append(row);counts[(domain,family,label)]+=1
                    if label:break
    for name,items in [('candidate_rows.jsonl',rows),('excluded.jsonl',excluded)]:
        (a.out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in items),encoding='utf-8')
    result=dict(complete=True,status='SOURCE_CHECKED_DRAFT_NOT_TRAIN_READY',trajectories=trajectories,rows=len(rows),
        positive=sum(r['label'] for r in rows),counts={str(k):v for k,v in counts.items()},excluded=len(excluded),human_reviewed=False,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (a.out/'DONE.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)


if __name__=='__main__':main()
