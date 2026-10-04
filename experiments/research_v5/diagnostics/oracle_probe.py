"""Human oracle annotations are diagnostic inputs, never business inference rules.

No gold value is passed to the executor. The separate summary reads saved binary
baselines after predictions have been materialized. No API client is imported.
"""
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from experiments.research_v5.process_grounding import build, execute
from guardian_truth.evidence_graph.facts import native_operand
from guardian_truth.evidence_graph.logic import evaluate_requirement
from guardian_truth.policy_table_v11.provenance import observations
from guardian_truth.policy_table_v11.witness import timeline
import pandas as pd

OUT=ROOT/'outputs/research_v5/oracle_process'


def save(name,value):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')


def field_id(fields,sid,key):
    ids=[i for i,f in fields.items() if f['source_id']==sid and f['record_keys']==[key]]
    assert len(ids)==1
    return ids[0]


def argument_id(args,did,key):
    return next(i for i,a in args.items() if a['declaration_id']==did and a['name']==key)


def skeleton(tid,policies,check,evidence,action):
    return dict(coverage='UNRESOLVED',rules=[dict(target_id=tid,regulated_action=action,
        policy_ids=policies,applies='YES',prerequisite_any_of=[dict(all_of=[check])],
        exemption='NO',exception_policy_ids=[],exception_evidence_ids=[],
        grounding_evidence_ids=evidence,unresolved=[])],open_questions=[],
        reason='Human oracle semantic relation, not a learned prediction or policy proof.')


def v4_oracles():
    from experiments.research_v3.build_suite import build as fixtures
    rows,_=fixtures()
    records=[]
    # This is annotation authoring over these disclosed fixtures, not a runtime
    # name dictionary. The emitted data contains only source/candidate IDs.
    for row in rows:
        if row['id'].split('.')[0] not in ('custody','reagent','calendar'):continue
        if row['id'].split('.')[1] not in ('allowed','identity','chronology'):continue
        g,f,a,_=build(row);tid=next(iter(g.targets))
        source=next(sid for sid,s in g.store.sources.items() if s['kind']=='result')
        tool=g.store.sources[source]['tool'];did=g.declarations[tool]
        r=(g.store.history_events if g.store.sources[source]['document']=='prompt' else g.store.target_events)[g.store.sources[source]['event']]
        flag=next(k for k in ('authorized','safe','approved') if k in r.value)
        joins=[]
        for k in g.targets[tid]['arguments']:
            joins.append(dict(role='Same '+k,target_field=field_id(f,tid,k),
                              call_argument=argument_id(a,did,k),result_field=field_id(f,source,k)))
        check=dict(meaning='Successful prior same-role inspection',declaration_id=did,
                   mode='SUCCESSFUL_BOOLEAN_CHECK',outcome_field=field_id(f,source,flag),joins=joins,unresolved=[])
        policies=[p for p in g.units if 'Before' in g.text(p) or 'only after' in g.text(p)][:1]
        assert policies
        reply=skeleton(tid,policies,check,[source],'Regulated modification')
        records.append(dict(id=row['id'],oracle=reply,complete=execute(row,reply,complete=True),
                            incomplete=execute(row,reply,complete=False)))
    assert len(records)==9
    assert sum(r['complete']['decision']=='ERROR' for r in records)==6
    assert all(r['incomplete']['decision']=='UNKNOWN' for r in records)
    # Satisfied narrow process rules still yield UNKNOWN for WHOLE-MOVE coverage.
    save('v4_process_controls.json',records)


def real_oracles():
    frame=pd.read_parquet(ROOT/'valid.parquet')
    rows={r.id:r.to_dict() for _,r in frame.iterrows()}
    # The three archived OR FN are selected for diagnostics, not hidden testing.
    case_ids=['banking_knowledge__task_003::t7','banking_knowledge__task_018::t6','retail__29::t13']
    output=[]
    for cid in case_ids:
        row=rows[cid];g,f,a,_=build(row)
        if cid==case_ids[0]:
            did=g.declarations['KB_search_bm25']
            policies=[p for p in g.units if 'no potential actions you can take' in g.text(p)]
            assert len(policies)==1
            check=dict(meaning='Attempt the still available complementary lexical search relevant to the unresolved fee question',
                declaration_id=did,mode='ATTEMPT',outcome_field=None,joins=[],unresolved=[])
            reply=skeleton(next(iter(g.targets)),policies,check,['h6','h10','h16',did],
                           'Escalation while a relevant untried in-scope alternative remains')
            reply['open_questions']=['Relevance and necessity are human semantic oracle assumptions; code cannot prove search would find an answer.',
                                     'A search result is not guaranteed. Policy does not require every tool blindly.']
            assumption='HUMAN_ORACLE: this complementary search is a potential relevant action for the still-unsolved request; no applicable override is observed.'
        elif cid==case_ids[1]:
            assert 'Fatima Al-Hassan' not in row['prompt']
            reply=dict(coverage='UNRESOLVED',rules=[],open_questions=[
                'No source-supported Latin lookup argument; system forbids transliteration.',
                'No independently justified mandatory untried check was found for the supplied name.'],reason='Do not manufacture the gold-proposed alternative.')
            assumption='SOURCE_GROUNDED_ORACLE_LIMIT: original gold remains 1, but the stated Latin alternative is unsupported.'
        else:
            reply=dict(coverage='UNRESOLVED',rules=[],open_questions=[
                'Latest h32 user rejects item 5206946487; oracle cannot treat it as desired.',
                'Pending-order membership does not prove available replacement inventory.',
                'No current native call; original graph native_operand requires a native target.'],reason='Intent and evidence gaps remain under an oracle.')
            assumption='SOURCE_GROUNDED_ORACLE_LIMIT: current desired replacement, inventory and native query scope are unresolved.'
        receipts=[]
        for name in g.declarations:
            # Full history receipt diagnostics, independent of whether there is
            # a current native target. No pairing heuristic is changed.
            prior=[('h'+str(i),e) for i,e in enumerate(g.store.history_events)]
            receipts.extend(dict(tool=name,call_sid=r.call_sid,result_sid=r.result_sid,valid=r.valid,reason=r.reason)
                            for r in observations(prior,name))
        complete=execute(row,reply,complete=True)
        incomplete=execute(row,reply,complete=False)
        output.append(dict(id=cid,assumption=assumption,oracle=reply,complete=complete,incomplete=incomplete,
                           strict_original_receipts=receipts))
    save('real_fn_oracle_relations.json',output)
    baseline=list(csv.DictReader((ROOT/'outputs/searh_23/baseline_frozen/control_repro_percase.csv').open(encoding='utf-8')))
    pred={r['id']:int(r['baseline'])|int(r['granite_repro']) for r in baseline}
    gold={r['id']:int(r['gold']) for r in baseline}
    corrected={i:pred[i] for i in pred}
    for r in output:corrected[r['id']]|=r['complete']['binary']
    sys.path.insert(0,str(Path(__file__).parent))
    from binary_audit import metrics
    save('summary.json',dict(new_http=0,new_tokens=0,selected_real_or_fn=len(output),
        existing_graph_before_process_closure='UNKNOWN: missing witness is not a FALSE fact in the original native graph.',
        source_grounded_complete_oracle_recoveries=sum(r['complete']['binary'] for r in output),
        incomplete_oracle_recoveries=sum(r['incomplete']['binary'] for r in output),
        unchanged_baseline=metrics(gold,pred),oracle_augmented_diagnostic=metrics(gold,corrected),
        architecture_improvement=False,claim='One of three residual FN is conditionally recoverable with an oracle relevance relation plus explicit complete-process closure. '
        'The other two are not source-justified recoveries. Gold-selected oracle augmentation is not an automatic F1 result.'))


def native_role_probe():
    frame=pd.read_parquet(ROOT/'valid.parquet')
    row=frame[frame.id.str.startswith('telecom__service_issuebreak_apn_settings-contract_end_suspension')].iloc[0].to_dict()
    g,_,_,_=build(row);tid=next(iter(g.targets));reads=[]
    try:
        result=native_operand(g,tid,dict(source_id='h10',pointer='/contract_end_date'),
                              [dict(target_pointer='/line_id',source_pointer='/line_id')],reads,{'contract_end_date'})
        diagnostic=dict(value=result,cause=None)
    except ValueError as exc:
        diagnostic=dict(value='UNKNOWN',cause=str(exc))
    save('native_role_scope_probe.json',dict(id=row['id'],source_sha256=g.store.source_sha256,
        oracle_role='The earlier receipt h10 describes line L1002; later h34 describes bill B1234321, not a later state of that line.',
        original_checker=diagnostic,code_source_reads=reads,
        implication='The polymorphic read tool is treated as a shared stream: a bill receipt supersedes the line receipt. '
                    'Correct role/entity-aware validity is needed before date comparison; no production change was made.'))


if __name__=='__main__':
    v4_oracles();real_oracles();native_role_probe()
    print((OUT/'summary.json').read_text(encoding='utf-8'))
