"""All actual public46 rows through both service profiles; models disabled.

This proves ingestion/dispatch/payload/archiving, not semantic model quality.
The recorded method invocations are local stubs, never HTTP inference.
"""
import copy
import json
from unittest.mock import patch
from acceptance import ROOT
from compare_source_ids import prepare,OUT
from guardian_truth.source_search.store import SourceStore
from runtime import GuardianServiceRuntime
import runtime


class DisabledModel:
    def __init__(self):self.requests=[]
    def snapshot(self):
        return {'actual_api_attempts':0,'known_provider_tokens':0,'unknown_usage_upper_bounds':0}
    def __call__(self,messages):
        self.requests.append(messages)
        return {'status':'UNAVAILABLE','reason':'MECHANICAL_STAGE_ACCEPTANCE_MODEL_DISABLED'}


def main():
    frozen,rows=prepare();records=[]
    for row in rows:
        for arm in frozen['arms']:
            cfg=copy.deepcopy(frozen['config']);cfg['stages']['source_search']['mode']=arm
            with patch.object(runtime,'load_config',return_value=cfg):
                service=GuardianServiceRuntime(frozen['config']['config_id'],audit_path=OUT/'mechanical_service_audit.jsonl')
            disabled=DisabledModel();service._source_transport=disabled
            result=service.check({'case_id':row['id'],'prompt':row['prompt'],'response':row['response']})
            assert result['source_store']['raw']=={k:row[k] for k in ('prompt','response')}
            assert result['coverage']['source_index_complete']
            structural=result['coverage']['structural']=='confirmed_hit'
            assert structural or len(disabled.requests)==1
            assert structural or result['coverage']['stop_reason']=='MECHANICAL_STAGE_ACCEPTANCE_MODEL_DISABLED'
            sizes=[len(json.dumps(m,ensure_ascii=False).encode()) for m in disabled.requests]
            records.append({'id':row['id'],'arm':arm,'decision':result['decision'],
                'structural':structural,'stub_invocations':len(disabled.requests),
                'initial_request_bytes':sizes[0] if sizes else None,
                'source_archive':result['coverage']['source_archive'],
                'exact_source_roundtrip':True,'source_events':len(result['source_store']['sources'])-2})
    # Stable IDs preserve a hypothesis on a real target without copied citations.
    from guardian_truth.source_search.id_contract import decode_assessment
    from guardian_truth.source_search.pipeline import validate_assessment,QUESTIONS
    row=next(r for r in rows if r['id'].startswith('retail__48::'));store=SourceStore(row)
    prior=next(sid for sid,s in store.sources.items() if s['document']=='prompt' and s['role']=='system')
    target=next(sid for sid,s in store.sources.items() if s['document']=='response' and s['kind']!='raw')
    vote={'decision':'ERROR','explanation':'MECHANICAL_ONLY_SYNTHETIC_HYPOTHESIS',
        'findings':[{'type':'CONTRADICTION','target_source_id':target,
            'explanation':'Mechanical ID preservation; this is not a newly inferred finding.',
            'evidence_ids':[prior]}],
        'checks':{q:{'status':'CHECKED','reason':'MECHANICAL_ONLY','evidence_ids':[prior]} for q in QUESTIONS},
        'open_questions':[]}
    preserved=validate_assessment(store,decode_assessment(store,vote))
    assert preserved['decision']=='ERROR'
    report={'scope':'REAL46_PIPELINE_DISPATCH_AND_ID_PRESERVATION_ONLY_NOT_MODEL_ACCURACY',
        'http_calls':0,'records':records,'paired_records':len(records),
        'source_ids_real_case_control':{'id':row['id'],'hypothesis_preserved':True,
            'source_ids':[prior,target],'semantic_quality_claimed':False},
        'max_initial_request_bytes':max(r['initial_request_bytes'] or 0 for r in records),
        'new_profile_admission_chars':frozen['config']['limits']['max_input_chars']}
    (OUT/'mechanical_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'}))


if __name__=='__main__':main()
