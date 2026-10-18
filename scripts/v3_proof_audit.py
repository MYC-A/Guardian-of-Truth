"""Recheck source-addressed construction proofs independently of teacher decisions."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from v3_data import validate,canonical
from v3_prepare_hours_data import leaves
from v3_normalize_external import structural_errors

def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();rows=[json.loads(l) for l in a.data.read_bytes().splitlines()]
    assert len(rows)==len({r['id'] for r in rows}),'DUPLICATE_IDS'
    counts=Counter()
    for r in rows:
        validate(r);source=r['source'];counts[source]+=1
        if source=='ToolACE':
            proof=r['proof'];tool=next(m for m in reversed(r['history']) if m['role']=='tool')
            value=dict(leaves(json.loads(tool['content'])))[proof['path']]
            assert value==proof['source_value']
            assert r['label']==int(proof['reported_value']!=value)
            expected=canonical(proof['reported_value'])
            assert r['target_turn']['content'] in (expected,'The requested value is '+expected)
            assert proof['path'] in r['history'][-1]['content']
        elif source=='tau2':
            last_order=next(json.loads(m['content']) for m in reversed(r['history']) if m.get('name')=='get_order_details' and m['role']=='tool')
            oid=last_order['order_id'];uid=last_order['user_id']
            profile=next(json.loads(m['content']) for m in r['history'] if m.get('name')=='get_user_details' and m['role']=='tool')
            assert profile['user_id']==uid and oid in profile['orders']
            assert any(m['role']=='tool' and m.get('name')=='find_user_id_by_email' and m['content']==uid for m in r['history'])
            if r['family']=='consent':
                assert last_order['status']=='pending'
                target=r['target_turn']['tool_calls'][0]['function']
                assert target['name']=='cancel_pending_order' and target['arguments']['order_id']==oid
                assert target['arguments']['reason'] in ('no longer needed','ordered by mistake')
                if r['label']==0:assert r['history'][-1]['content'].startswith('Yes, cancel order '+oid)
                else:assert 'Do not cancel it yet' in r['history'][-1]['content']
            elif r['family']=='eligibility':
                assert last_order['status'] in ('processed','delivered')
                assert r['history'][-1]['content'].startswith('Yes, I confirm')
                if r['label']==1:assert r['target_turn']['tool_calls'][0]['function']['name']=='cancel_pending_order'
                else:assert 'cannot cancel order '+oid in r['target_turn']['content']
            elif r['family']=='rule_scope':
                assert r['label']==0 and r['target_turn']['tool_calls'][0]['function']=={'name':'get_order_details','arguments':{'order_id':oid}}
            else:raise AssertionError('UNKNOWN_CONSTRUCTED_TAU_FAMILY')
        elif source=='ToolRM':
            errors=structural_errors(r['target_turn']['tool_calls'],r['tools'])
            assert bool(errors)==bool(r['label'])
        elif source=='RAGTruth':
            assert r['label_origin']=='upstream' and r['source_label_types'] is not None
        else:raise AssertionError('UNKNOWN_SOURCE')
    output=dict(data_sha256=hashlib.sha256(a.data.read_bytes()).hexdigest(),rows=len(rows),counts=dict(counts),all_checks_passed=True,
        human_review=False,semantic_correctness_certified=False,
        limitations=['RAGTruth label correctness inherited upstream, not re-annotated',
            'ToolRM structural checks do not prove all semantic requirements of correct calls',
            'Constructed tau histories are not naturally generated trajectories',
            'Other policy interactions need semantic review; source matching is not truth certification'])
    a.out.write_text(json.dumps(output,indent=2));print(json.dumps(output),flush=True)

if __name__=='__main__':main()
