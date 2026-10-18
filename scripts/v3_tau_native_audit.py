"""Verify constructed retail contexts and operation constraints against native tools."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['TAU2_DATA_DIR']='/workspace/guardian-lab-20261018/v3-20261019/tau2-source/data'

def source_fields_equal(actual,source):
    # Native Pydantic adds omitted optional defaults. Compare every upstream field,
    # including exact nested list order, without declaring added defaults a mutation.
    if isinstance(source,dict):return isinstance(actual,dict) and all(k in actual and source_fields_equal(actual[k],v) for k,v in source.items())
    if isinstance(source,list):return isinstance(actual,list) and len(actual)==len(source) and all(source_fields_equal(a,b) for a,b in zip(actual,source))
    return actual==source

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True)
    args=parser.parse_args()
    from tau2.domains.retail.data_model import RetailDB
    from tau2.domains.retail.tools import RetailTools
    raw=json.loads((Path(os.environ['TAU2_DATA_DIR'])/'tau2/domains/retail/db.json').read_bytes())
    results=[]
    for line in args.data.read_bytes().splitlines():
        row=json.loads(line)
        if row['source']!='tau2':continue
        oid=row['scenario_id'].split(':',2)[-1];order=raw['orders'][oid];uid=order['user_id'];user=raw['users'][uid]
        db=RetailDB.model_validate(dict(products={},users={uid:copy.deepcopy(user)},orders={oid:copy.deepcopy(order)}))
        tools=RetailTools(db)
        assert tools.find_user_id_by_email(user['email'])==uid
        assert source_fields_equal(tools.get_order_details(oid).model_dump(mode='json'),order),'SOURCE_ORDER_CHANGED'
        assert source_fields_equal(tools.get_user_details(uid).model_dump(mode='json'),user),'SOURCE_USER_CHANGED'
        record=dict(id=row['id'],all_upstream_fields_match=True,native_optional_defaults_not_in_upstream_history=True,
                    policy_consent_checked_by_generator_not_tool=True)
        if order['status']=='pending':
            result=tools.cancel_pending_order(oid,'no longer needed')
            assert result.status=='cancelled';record['native_write_allowed']=True
        else:
            try:tools.cancel_pending_order(oid,'no longer needed')
            except ValueError as exc:
                assert str(exc)=='Non-pending order cannot be cancelled';record['native_write_allowed']=False
            else:raise AssertionError('NATIVE_ELIGIBILITY_UNEXPECTED')
        results.append(record)
    output=args.data.parent/'NATIVE_RETAIL_AUDIT.json'
    output.write_text(json.dumps(dict(rows=len(results),all_passed=True,records=results,
        candidate_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),
        consent_semantics_not_proven_by_environment=True,human_reviewed=False),indent=2))
    print(json.dumps(dict(native_retail_rows=len(results),all_passed=True)),flush=True)

if __name__=='__main__':main()
