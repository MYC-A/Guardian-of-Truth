"""Contract/real loop regressions, not semantic model accuracy tests."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from acceptance import ROOT
from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.pipeline import run
from guardian_truth.source_search.id_contract import run_ids,decode_assessment,native_target_inventory
from test_source_search import case,complete_vote


def id_vote(store,decision='NO_ERROR'):
    return {'decision':decision,'explanation':'control, not an accuracy claim',
        'findings':[],'checks':{q:{'status':'NOT_APPLICABLE','reason':'control',
            'evidence_ids':['t0']} for q in ('scope','grounds','exceptions','alternatives','arithmetic')},
        'open_questions':[]}


class Tests(unittest.TestCase):
    def test_read_window_continuation_can_change_end_and_limit(self):
        row=case(); store=SourceStore(row); sid='h0'
        replies=iter([
            {'action':{'op':'read_source','args':{'source_id':sid,'start':0,'end':50,'limit':10}}},
            {'action':{'op':'read_source','args':{'source_id':sid,'start':10,'end':len(store.text(sid)),'limit':4000}}},
            {'assessment':complete_vote(row)}])
        result=run(row,lambda _: {'status':'OK','content':json.dumps(next(replies))},max_steps=3)
        self.assertEqual(result['decision'],'NO_ERROR')
        self.assertEqual(result['material_query_gaps'],[])

    def test_partial_judge_updates_open_question_operation(self):
        row=case(); vote=complete_vote(row);vote['checks']=vote['checks'][:1]
        replies=iter([{'ready_for_judge':True},{'assessment':vote},
            {'action':{'op':'get_open_questions','args':{}}},
            {'assessment':complete_vote(row)}])
        result=run(row,lambda _: {'status':'OK','content':json.dumps(next(replies))},max_steps=4)
        self.assertNotIn('scope',result['trace'][2]['result']['questions'])
        self.assertEqual(set(result['trace'][2]['result']['questions']),
                         {'grounds','exceptions','alternatives','arithmetic'})

    def test_ids_fill_exact_target_and_prior_quote(self):
        store=SourceStore(case()); vote=id_vote(store,'ERROR')
        vote['findings']=[{'type':'CONTRADICTION','target_source_id':'t0',
            'explanation':'hypothesis','evidence_ids':['h0']}]
        normalized=decode_assessment(store,vote)
        self.assertEqual(normalized['findings'][0]['response_quote'],store.text('t0'))
        self.assertEqual(normalized['findings'][0]['evidence'][0]['quote'],store.text('h0'))
        self.assertEqual(normalized['original_source_id_vote'],vote)

    def test_no_foreign_history_target_or_invented_source(self):
        store=SourceStore(case());vote=id_vote(store,'ERROR')
        vote['findings']=[{'type':'CONTRADICTION','target_source_id':'h0',
            'explanation':'control','evidence_ids':['h0']}]
        with self.assertRaises(ValueError):decode_assessment(store,vote)
        vote=id_vote(store);vote['checks']['scope']['evidence_ids']=['made-up']
        with self.assertRaises(ValueError):decode_assessment(store,vote)

    def test_missing_check_is_invalid_and_open_check_is_unknown(self):
        store=SourceStore(case());vote=id_vote(store);del vote['checks']['scope']
        with self.assertRaises(ValueError):decode_assessment(store,vote)
        vote=id_vote(store);vote['checks']['scope'].update(status='OPEN',evidence_ids=[])
        result=run_ids(case(),lambda _: {'status':'OK','content':json.dumps({'assessment':vote})},mode='direct')
        self.assertEqual(result['decision'],'UNKNOWN')
        self.assertEqual(result['assessment']['proposed_decision'],'NO_ERROR')

    def test_direct_ids_and_search_use_same_assessment_contract(self):
        store=SourceStore(case());vote=id_vote(store)
        seen=[]
        def ask(messages):
            seen.append(messages)
            if len(seen)==1:return {'status':'OK','content':json.dumps({'ready_for_judge':True})}
            return {'status':'OK','content':json.dumps({'assessment':vote})}
        result=run_ids(case(),ask,max_steps=3)
        self.assertEqual(result['decision'],'NO_ERROR')
        initial=json.loads(seen[0][1]['content'])
        self.assertTrue(initial['full_system_sources'])
        self.assertIn('source_registry',initial['source_linked_context'])
        self.assertIn('checks is an OBJECT',seen[1][0]['content'])

    def test_native_inventory_is_actual_current_call_not_prior_lookup(self):
        row=case(); row['response']='→ TOOL_CALL commit: {"item_id":"X91"}'
        result=native_target_inventory(SourceStore(row))
        self.assertEqual([(r['source_id'],r['tool']) for r in result],[('t0','commit')])
        self.assertEqual(result[0]['status'],'ATTEMPT_NOT_COMPLETED_EFFECT')

    def test_final_native_transport_disables_tools_and_loop_reminds_quota(self):
        from guardian_truth.source_search.transport import ModelTransport
        from guardian_truth.source_search.id_contract import id_contract
        captured=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'choices':[{'message':{'content':'{}'},
                'finish_reason':'stop'}],'usage':{'total_tokens':1}}).encode()
        with TemporaryDirectory() as directory:
            transport=ModelTransport(directory,provider='ollama',model='mock',max_tokens=100000)
            transport.key='mock-not-a-secret'
            def urlopen(request,**kwargs):
                captured.append(json.loads(request.data));return Response()
            with patch('urllib.request.urlopen',side_effect=urlopen):
                transport([{'role':'system','content':id_contract('FINAL')}])
        self.assertEqual(captured[0]['tool_choice'],'none')
        self.assertNotIn('tools',captured[0])
        seen=[];vote=id_vote(SourceStore(case()))
        def ask(messages):
            seen.append(json.loads(json.dumps(messages)))
            content=({'action':{'op':'read_source','args':{'source_id':'h0'}}}
                     if len(seen)==1 else {'assessment':vote})
            return {'status':'OK','content':json.dumps(content)}
        result=run_ids(case(),ask,max_steps=2)
        self.assertEqual(result['decision'],'NO_ERROR')
        self.assertIn('FINAL assessment JSON',seen[-1][-1]['content'])
        self.assertEqual([m['role'] for m in seen[-1]],['system','user'])
        transcript=json.loads(seen[-1][-1]['content'])['investigation_transcript']
        self.assertEqual(json.loads(transcript[0]['content']),json.loads(seen[0][1]['content']))
        self.assertTrue(any('operation_result' in m.get('content','') for m in transcript))


if __name__=='__main__':unittest.main()
