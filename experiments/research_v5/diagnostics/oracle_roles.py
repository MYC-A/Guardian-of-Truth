"""New offline phase: role-scoped validity oracle on the real context-limited R0 FN."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from experiments.research_v5.process_grounding import build
from experiments.research_v5.native_role_grounding import execute
import pandas as pd


def main():
    frame=pd.read_parquet(ROOT/'valid.parquet')
    row=frame[frame.id.str.startswith('telecom__service_issuebreak_apn_settings-contract_end_suspension')].iloc[0].to_dict()
    g,f,a,_=build(row)
    F=lambda s,k:next(i for i,v in f.items() if v['source_id']==s and v['record_keys']==[k])
    A=next(i for i,v in a.items() if v['declaration_id']==g.declarations['get_details_by_id'] and v['name']=='id')
    policies=[p for p in g.units if "not allowed to lift the suspension" in g.text(p)]
    assert len(policies)==1
    rule=dict(target_id='t0',regulated_action='Lift suspension for the line with a past contract end date',
        policy_ids=policies,modality='FORBID',applies='YES',fact_field=F('h10','contract_end_date'),
        target_identity_field=F('t0','line_id'),read_call_argument=A,result_identity_field=F('h10','line_id'),
        operation='DATE_BEFORE_SYSTEM_DATE',exemption='NO',exception_policy_ids=[],unresolved=[])
    reply=dict(process=dict(coverage='UNRESOLVED',rules=[],open_questions=[],reason='World-state date rule, not event absence'),
               native_role_rules=[rule],open_questions=[],reason='Human role/alias oracle. Payment does not waive the past-contract prohibition.')
    before=json.loads((ROOT/'outputs/research_v5/oracle_process/native_role_scope_probe.json').read_text(encoding='utf-8'))
    complete=execute(row,reply,complete=True);incomplete=execute(row,reply,complete=False)
    assert complete['decision']==incomplete['decision']=='ERROR'
    assert complete['native_roles'][0]['fact']['left']=='2025-01-31'
    assert complete['native_roles'][0]['fact']['right']=='2025-02-25'
    report=dict(id=row['id'],source_sha256=g.store.source_sha256,new_http=0,
        original_checker=before['original_checker'],oracle=reply,role_scoped=complete,
        incomplete_log=incomplete,world_state_absence_is_false=False,
        recoveries=dict(context_limited_R0_FN=1,archived_Guardian_OR_Granite_FN=0),
        claim='Oracle alias plus source-preserving entity receipt view fixes the native factual query. '
              'This is not an automatic role-grounding or full-valid46 F1 result; the archived OR already detects this case.')
    out=ROOT/'outputs/research_v5/oracle_role_scope';out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(native_fact=complete['native_roles'][0]['fact']['value'],decision=complete['decision'],new_http=0)))


if __name__=='__main__':main()
