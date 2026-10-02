"""Scope misbinding, absent acts and counterreview safety: zero API calls."""
import json
import unittest
from acceptance import ROOT
from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.move_scope import input_packet, validate_parse, check_binding, apply_scope_gate
from guardian_truth.source_search.finding_review import review_findings
from guardian_truth.source_search.typed_pipeline import run_typed


def row(response='Please confirm the change.'):
    return {'prompt':'⟦SYSTEM⟧\nOnly tool_b requires approval.\n⟦USER⟧\nPlease help with item X91.',
            'response':response}

def parse(store, act='ASK_CONFIRM', modality='REQUEST', performer='USER'):
    packet=input_packet(store)
    return {'acts':[{'id':'a1','speaker':'ASSISTANT','performer':performer,'act':act,
                    'modality':modality,'action':'change','entity_literals':[],
                    'evidence':{'source_id':'t0','quote':store.text('t0')}}] if packet['text_segments'] else [],
            'intent':{'status':'AMBIGUOUS','requested_action':None,
                      'evidence':{'source_id':'h1','quote':'Please help with item X91.'}}}

class Tests(unittest.TestCase):
    def test_source_id_review_never_accepts_invented_or_agent_only_proof(self):
        from guardian_truth.source_search.finding_review import review_findings_by_id
        store=SourceStore(row()); assessment={'decision':'ERROR','findings':[{'explanation':'control'}]}
        def answer(ids):
            return lambda _: {'status':'OK','content':json.dumps({'reviews':[{'finding_index':0,
                'policy_applies_to_target':True,'candidate_error_is_supported':True,
                'reason':'control','evidence_ids':ids}]})}
        for ids in (['invented'],['t0']):
            self.assertEqual(review_findings_by_id(store,assessment,answer(ids))['decision'],'UNKNOWN')
        self.assertEqual(review_findings_by_id(store,assessment,answer(['h0','t0']))['decision'],'ERROR')

    def test_source_id_review_keeps_refuted_finding_unknown(self):
        from guardian_truth.source_search.finding_review import review_findings_by_id
        store=SourceStore(row()); assessment={'decision':'ERROR','findings':[{}]}
        rec={'status':'OK','content':json.dumps({'reviews':[{'finding_index':0,
            'policy_applies_to_target':False,'candidate_error_is_supported':False,
            'reason':'Request is not execution.','evidence_ids':['h0','t0']}]})}
        result=review_findings_by_id(store,assessment,lambda _:rec)
        self.assertEqual(result['decision'],'UNKNOWN')
        self.assertEqual(result['reviews'][0]['verified_evidence'][1]['quote'],store.raw['response'])

    def test_separated_requests_never_mix_user_and_target_text(self):
        from guardian_truth.source_search.scope_stages import request,parse_stores
        store=SourceStore(row()); stores={'x':store}
        act_messages,_=request('act',stores); intent_messages,_=request('intent',stores)
        act=json.loads(act_messages[1]['content']); intent=json.loads(intent_messages[1]['content'])
        self.assertNotIn('latest_user',act['cases'][0])
        self.assertNotIn('text_segments',intent['cases'][0])
        value=parse(store)
        result=parse_stores(stores,
            lambda _: {'status':'OK','content':json.dumps({'cases':[{'id':'x','acts':value['acts']}]})},
            lambda _: {'status':'OK','content':json.dumps({'cases':[{'id':'x','intent':value['intent']}]})})
        self.assertEqual(result['cases']['x']['move_scope']['intent']['status'],'AMBIGUOUS')

    def test_separated_stage_failure_stops_before_intent_or_judge(self):
        from guardian_truth.source_search.scope_stages import parse_stores
        def forbidden(_): raise AssertionError('must not call the next model')
        result=parse_stores({'x':SourceStore(row())},lambda _: {'status':'UNAVAILABLE','reason':'http_429'},forbidden)
        self.assertEqual(result['cases']['x']['stage'],'act')

    def test_speaker_is_observed_role_not_model_guess(self):
        store=SourceStore(row()); value=parse(store)
        value['acts'][0]['speaker']='UNKNOWN'
        frame=validate_parse(store,value)
        self.assertEqual(frame['acts'][0]['speaker'],'ASSISTANT')
        self.assertEqual(frame['acts'][0]['model_speaker'],'UNKNOWN')

    def test_raw_quote_still_requires_containment_in_correct_text_role(self):
        store=SourceStore(row()); value=parse(store)
        value['acts'][0]['evidence']['source_id']='response'
        value['intent']['evidence']['source_id']='prompt'
        self.assertFalse(validate_parse(store,value)['issues'])
        value['intent']['evidence']['quote']='Only tool_b requires approval.'
        with self.assertRaisesRegex(ValueError,'latest user'):
            validate_parse(store,value)

    def test_native_inventory_owned_by_code_and_never_proves_success(self):
        store=SourceStore(row('→ TOOL_CALL tool_a: {"item_id":"X91"}'))
        frame=validate_parse(store,parse(store))
        self.assertEqual(frame['acts'][0]['act'],'ATTEMPT_TOOL')
        self.assertEqual(frame['acts'][0]['tool'],'tool_a')
        self.assertFalse(frame['semantic_classification_proven'])
        self.assertFalse(frame['issues'])

    def test_text_cannot_reclassify_a_tool_call_as_refusal(self):
        store=SourceStore(row('→ TOOL_CALL tool_a: {"item_id":"X91"}'))
        value=parse(store)
        value['acts']=[{'id':'a1','speaker':'ASSISTANT','performer':'ASSISTANT',
            'act':'REFUSE','modality':'PRESENT','action':'change','entity_literals':[],
            'evidence':{'source_id':'t0','quote':store.text('t0')}}]
        with self.assertRaisesRegex(ValueError,'text act'):
            validate_parse(store,value)

    def test_ambiguous_intent_does_not_become_inspection_only(self):
        store=SourceStore(row()); value=parse(store)
        value['intent']['requested_action']='inspection only'
        with self.assertRaisesRegex(ValueError,'invented action'):
            validate_parse(store,value)

    def test_lookup_bound_to_commit_rule_is_rejected(self):
        store=SourceStore(row('→ TOOL_CALL tool_a: {"item_id":"X91"}'))
        frame=validate_parse(store,parse(store))
        finding={'response_quote':store.raw['response'],'scope_binding':{
            'act_id':'native:t0','governed_act':'ATTEMPT_TOOL','governed_modality':'ATTEMPTED',
            'governed_performer':'ASSISTANT',
            'governed_tool':'tool_b','policy_evidence':{'source_id':'h0','quote':'Only tool_b requires approval.'}}}
        self.assertEqual(check_binding(store,frame,finding)['reason'],'rule_governs_another_tool')
        assessment=apply_scope_gate(store,frame,{'findings':[finding]}, {'decision':'ERROR'})
        self.assertEqual(assessment['decision'],'UNKNOWN')

    def test_fake_refusal_has_no_matching_act(self):
        store=SourceStore(row()); frame=validate_parse(store,parse(store))
        finding={'scope_binding':{'act_id':'a1','governed_act':'REFUSE','governed_modality':'PRESENT'}}
        self.assertEqual(check_binding(store,frame,finding)['status'],'MISMATCH')

    def test_user_action_is_not_assistant_action(self):
        store=SourceStore(row('Please run the test.'))
        frame=validate_parse(store,parse(store,act='ASK_USER_ACTION'))
        self.assertEqual(frame['acts'][0]['speaker'],'ASSISTANT')
        self.assertEqual(frame['acts'][0]['performer'],'USER')
        finding={'scope_binding':{'act_id':'a1','governed_act':'ASK_USER_ACTION',
            'governed_modality':'REQUEST','governed_performer':'ASSISTANT'}}
        self.assertEqual(check_binding(store,frame,finding)['reason'],'rule_governs_another_performer')

    def test_uncovered_material_clause_is_not_a_complete_frame(self):
        store=SourceStore(row('Please confirm the change. I cannot help.'))
        value=parse(store); value['acts'][0]['evidence']['quote']='Please confirm the change.'
        self.assertIn('uncovered_target_text',validate_parse(store,value)['issues'])

    def test_quoted_entity_and_completed_modality_must_be_valid(self):
        store=SourceStore(row()); value=parse(store)
        value['acts'][0]['entity_literals']=['wrong-item']
        with self.assertRaisesRegex(ValueError,'entity literal'):
            validate_parse(store,value)
        value=parse(store,act='ASSERT_DONE')
        with self.assertRaisesRegex(ValueError,'completion claim'):
            validate_parse(store,value)

    def test_refuting_all_findings_is_not_a_clean_verdict(self):
        store=SourceStore(row())
        assessment={'decision':'ERROR','findings':[{'response_quote':store.raw['response']}]}
        result=review_findings(store,assessment,lambda _: {'status':'OK','content':json.dumps({'reviews':[
            {'finding_index':0,'applicability':'REFUTED','entailment':'REFUTED','reason':'Request is not execution.',
             'evidence':[{'source_id':'response','quote':store.raw['response']}]}]})})
        self.assertEqual(result['decision'],'UNKNOWN')

    def test_review_cannot_drop_a_finding_or_reference_a_fake_quote(self):
        store=SourceStore(row()); assessment={'decision':'ERROR','findings':[{}]}
        result=review_findings(store,assessment,lambda _: {'status':'OK','content':'{"reviews":[]}'})
        self.assertEqual(result['decision'],'UNKNOWN')
        self.assertIn('missing',result['review_error'])

    def test_parse_failure_never_reaches_judge(self):
        def judge(_): raise AssertionError('judge must not run')
        result=run_typed(row(),lambda _: {'status':'OK','content':'{"acts":[]}'},judge)
        self.assertEqual(result['decision'],'UNKNOWN')

    def test_shared_store_preserves_source_reference_identity(self):
        from guardian_truth.source_search.pipeline import run
        data=row(); store=SourceStore(data)
        ref=store.quote_id('prompt',data['prompt'].index('Only'),data['prompt'].index('⟦USER⟧')-1)
        def ask(_):
            vote={'decision':'NO_ERROR','explanation':'control','findings':[],
                'checks':[{'question_id':qid,'status':'CHECKED','reason':'control',
                          'evidence':[{'source_id':ref,'quote':store.text(ref)}]} for qid in
                          ('scope','grounds','exceptions','alternatives','arithmetic')],
                'open_questions':[]}
            return {'status':'OK','content':json.dumps({'assessment':vote})}
        self.assertEqual(run(data,ask,mode='direct',source_store=store)['decision'],'NO_ERROR')
        other=row('other response')
        with self.assertRaisesRegex(ValueError,'another input'):
            run(other,ask,source_store=store)

if __name__=='__main__': unittest.main()
