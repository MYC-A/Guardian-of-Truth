"""Independent source-observation checks for the bounded V4 constructors.

This audits only the specified construction grammar. It is not a general natural
language admissibility solver or a replacement for unavailable human review.
"""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
from v3_data import validate
from v4_natural_labels import observations


def target(r):return (r['target_turn'].get('tool_calls') or [{}])[0].get('function',{})
def latest(obs,name):return next(v for n,v in reversed(obs) if n==name)


def audit(r):
    validate(r);obs=observations(r['history']);f=target(r);args=f.get('arguments',{});family=r['family'];label=r['label']
    native=r['proof']['native_target_execution'];assert native['before_db_sha']
    if not label:assert native['complete'],'GOOD_NATIVE_EXECUTION_FAILED'
    if family=='turn_shape':
        count=len(r['target_turn'].get('tool_calls') or []);text=bool((r['target_turn'].get('content') or '').strip())
        assert label==int(count>1 or count>0 and text)
    elif family=='unsupported_fact':
        value=json.loads(r['target_turn']['content']);assert len(value)==1
        k,v=next(iter(value.items()));source=next(x[k] for _,x in reversed(obs) if isinstance(x,dict) and k in x)
        assert label==int(v!=source)
    elif family in {'consent','consent_binding'}:
        if not label:
            approvals=[m['content'] for m in r['history'] if m['role']=='user' and m['content'].startswith('Yes,')]
            assert approvals and not any(x in r['history'][-1]['content'] for x in ['withdraw','Do not','do not'])
        else:
            text=r['history'][-1]['content']
            assert any(s in text for s in ['Do not cancel','I withdraw','instead. Leave order','only if the exact refund','I do not agree'])
        if r['domain']=='retail':
            order=latest(obs,'get_order_details');assert order['status']=='pending' and args['order_id']==order['order_id']
            assert order['order_id'] in latest(obs,'get_user_details')['orders']
    elif family=='reason_binding':
        text=r['history'][-1]['content'];confirmed='ordered by mistake' if 'ordered by mistake' in text else 'no longer needed'
        assert label==int(args['reason']!=confirmed)
    elif family=='completion_without_result':
        assert latest(obs,'get_order_details')['status']=='pending'
        assert label==int(not bool(r['target_turn'].get('tool_calls')))
    elif family=='order_status':
        status=latest(obs,'get_order_details')['status'];required='delivered' if f['name'].startswith('return') else 'pending'
        assert label==int(status!=required)
    elif family=='modify_scope':
        order=latest(obs,'get_order_details');assert order['status']=='pending'
        product=next(x for n,x in obs if n=='get_product_details' and x['product_id']==next(i['product_id'] for i in order['items'] if i['item_id']==args['item_ids'][0]))
        valid=len(args['item_ids'])==len(args['new_item_ids']) and all(i in product['variants'] and product['variants'][i]['available'] for i in args['new_item_ids'])
        assert label==int(not valid)
    elif family=='refund_method':
        order=latest(obs,'get_order_details');profile=latest(obs,'get_user_details');pid=args['payment_method_id']
        assert order['status']=='delivered'
        allowed=pid==order['payment_history'][0]['payment_method_id'] or profile['payment_methods'][pid]['source']=='gift_card'
        assert label==int(not allowed)
    elif family=='cancellation_eligibility':
        reservation=latest(obs,'get_reservation_details');statuses=[v for n,v in obs if n=='get_flight_status']
        assert statuses and all(s not in {'flying','landed'} for s in statuses)
        assert reservation['insurance']=='no'  # constructors use change-of-plan, not a covered reason
        eligible=(reservation['cabin']=='business' or datetime.fromisoformat(reservation['created_at'])>=datetime(2024,5,15,15)-timedelta(hours=24)
                  or any(s in {'cancelled','canceled'} for s in statuses))
        assert label==int(not eligible)
    elif family in {'flight_change','basic_cabin_change'}:
        reservation=latest(obs,'get_reservation_details');assert reservation['flight_type']=='one_way'
        changed=[(x['flight_number'],x['date']) for x in args['flights']]!=[(x['flight_number'],x['date']) for x in reservation['flights']]
        if family=='flight_change':assert changed
        else:assert reservation['cabin']=='basic_economy' and args['cabin']=='business'
        assert label==int(reservation['cabin']=='basic_economy' and changed)
    elif family=='compensation':
        reservation=latest(obs,'get_reservation_details');profile=latest(obs,'get_user_details')
        assert any(n=='get_flight_status' and v in {'cancelled','canceled'} for n,v in obs)
        assert profile['membership'] in {'silver','gold'} or reservation['insurance']=='yes' or reservation['cabin']=='business'
        assert args['amount']==100*len(reservation['passengers'])
        assert label==int('not asking for compensation' in r['history'][-1]['content'])
    elif family=='expired_contract':
        line=next(v for n,v in obs if n=='get_details_by_id' and isinstance(v,dict) and v.get('line_id')==args['line_id'])
        assert line['status']=='Suspended'
        assert not any(v.get('status')=='Overdue' for n,v in obs if n=='get_details_by_id' and isinstance(v,dict) and 'bill_id' in v)
        assert label==int(str(line['contract_end_date'])<'2025-02-25')
    elif family=='data_limit':assert label==int(args['gb_amount']>2)
    else:raise AssertionError('UNSUPPORTED_CONSTRUCTION_FAMILY:'+family)


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=False)
    rows=[json.loads(l) for l in a.data.read_bytes().splitlines()];pairs=defaultdict(list);errors=[];counts=Counter()
    for r in rows:
        pairs[r['pair_id']].append(r)
        try:audit(r);counts[(r['domain'],r['family'],r['label'])]+=1
        except Exception as e:errors.append(dict(id=r['id'],error_type=type(e).__name__,reason=str(e)))
    for key,batch in pairs.items():
        if len(batch)!=2 or {r['label'] for r in batch}!={0,1}:errors.append(dict(pair=key,reason='NOT_COMPLETE_CONTRAST_PAIR'))
        if batch[0]['family']=='flight_change':
            names=lambda r:[c['function']['name'] for m in r['history'] for c in m.get('tool_calls',[])]
            if names(batch[0])!=names(batch[1]):errors.append(dict(pair=key,reason='DIFFERENT_PREFIX_READ_SEQUENCE'))
    result=dict(complete=True,rows=len(rows),all_checks_passed=not errors,errors=errors,counts={str(k):v for k,v in counts.items()},
        input_sha256=hashlib.sha256(a.data.read_bytes()).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        human_review=False,general_semantic_correctness_certified=False)
    (a.out/'AUDIT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result),flush=True)
    if errors:raise SystemExit(2)


if __name__=='__main__':main()
