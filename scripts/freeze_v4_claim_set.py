"""Freeze a small audited development claim set BEFORE judge calls.

Eight original accusation probes + eight exact-source contrast controls.
The controls balance the relation task, not the contest class distribution.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from guardian_truth.claim_verifier import build_messages
from guardian_truth.cli import read_rows


# Selection is frozen by error class and citation relation, never model results.
PROBES = [
 ('airline__10::t19',0,['entity_confusion']),
 ('banking_knowledge__task_033::t2',0,[]),
 ('telecom__mms_issuebad_network_preference-bad_wifi_calling-break_apn_mms_setting-break_app_::t7',0,['wrong_polarity']),
 ('airline__21::t7',1,['entity_confusion']),
 ('banking_knowledge__task_005::t6',0,[]),
 ('retail__106::t3',0,['entity_confusion']),
 ('retail__36::t10',0,['wrong_polarity']),
 ('telecom__mms_issuebreak_apn_mms_setting-user_abroad_roaming_enabled_offPERSONA_Hard::t27',1,[]),
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,default=Path('outputs/v4_baseline_reason_audit/audit.json'))
    parser.add_argument('--data',type=Path,default=Path('valid.parquet'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Frozen output already exists; do not overwrite')
    audit=json.loads(args.audit.read_text(encoding='utf-8'))
    rows={row['id']:row for row in audit['rows']}
    data={str(row['id']):row for row in read_rows(args.data)}
    cases=[]
    for row_id,index,tags in PROBES:
        claim=next(c for c in rows[row_id]['claims'] if c['finding_index']==index)
        cases.append({'id':f'original-{len(cases)+1:02d}','row_id':row_id,
            'claim':claim['normalized_accusation'],'evidence':claim['evidence'],
            'candidate_response':data[row_id]['response'],
            'gold_relation':claim['relation_to_cited_evidence'],'tags':tags,
            'audit_origin':{'finding_index':index,'message':claim['message']},
            'annotation_note':claim['assessment']})
    controls=[
      ('retail__36::t10',16665,18179,
       'The supplied order record contains item_id 6117189161 for an Action Camera.','ENTAILED',['entity_confusion']),
      ('retail__36::t10',16665,18179,
       'The supplied order record has no item with item_id 6117189161.','CONTRADICTED',['wrong_polarity']),
      ('airline__21::t7',19241,20242,
       'The OBUT9V reservation in this record has economy cabin and IAH as origin.','ENTAILED',['entity_confusion']),
      ('airline__21::t7',19241,20242,
       'The OBUT9V reservation in this record has business cabin and MCO as origin.','CONTRADICTED',['entity_confusion','wrong_polarity']),
      ('airline__10::t19',24440,24475,
       'The supplied calculate tool result is 795.0.','ENTAILED',[]),
      ('airline__10::t19',24440,24475,
       'The supplied calculate tool result is 1185.0.','CONTRADICTED',['wrong_polarity']),
      ('banking_knowledge__task_005::t6',6338,6745,
       'The rule allows verification with any two of date of birth, email, phone number and address.','ENTAILED',[]),
      ('airline__10::t19',24440,24475,
       'The traveler prefers an aisle seat.','INSUFFICIENT',[]),
    ]
    for row_id,start,end,claim,gold,tags in controls:
        cases.append({'id':f'control-{len(cases)-len(PROBES)+1:02d}','row_id':row_id,'claim':claim,
            'evidence':[{'id':'s0','text':data[row_id]['prompt'][start:end]}],
            'candidate_response':None,'gold_relation':gold,'tags':tags,
            'audit_origin':{'document':'prompt','start':start,'end':end},
            'annotation_note':'Exact-source contrast, not a production accusation or new contest label.'})
    for case in cases:
        messages=build_messages(case['claim'],case['evidence'],case['candidate_response'])
        case['messages_sha256']=hashlib.sha256(json.dumps(messages,sort_keys=True).encode()).hexdigest()
    result={'schema_version':1,'data_role':'inspected_development_diagnostic',
        'selection':'Eight prespecified original accusation probes + eight exact-source controls; no model-result selection.',
        'protocol':{'temperature':0,'max_output_tokens':2048,'response_format':'json_object',
                    'reasoning_effort':'omitted; native model defaults, not equal internal compute',
                    'stage2_selection':'Retain two best by all-case relation accuracy; ties use ENTAILED precision, then validity, then fewer entity-tag errors. Do not count transport failures as semantic evidence; unresolved quota confounding prevents elimination.'},
        'relation_counts':dict(Counter(c['gold_relation'] for c in cases)),
        'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.audit,args.data)},
        'cases':cases}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'cases':len(cases),'relations':result['relation_counts'],
                      'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__=='__main__':
    main()
