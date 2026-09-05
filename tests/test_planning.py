import copy
import json
import unittest

from guardian_truth.pipeline import Detector
from guardian_truth.planning import analyze_plan
from guardian_truth.parsing import parse_events,parse_catalog
from guardian_truth.provenance import build_graph


def eq(key,value): return {'eq':[{'state':key},{'literal':value}]}


def spec():
    return {'version':1,'initial':{'phase':{'literal':'new'}},'goal':eq('phase','done'),
            'actions':[{'id':'prepare','tool':'prepare','arguments':{'ticket_id':'T'},
                        'require':eq('phase','new'),'effects':{'phase':{'literal':'ready'}},'outcome':'guaranteed'},
                       {'id':'complete','tool':'complete','arguments':{'ticket_id':'T'},
                        'require':eq('phase','ready'),'effects':{'phase':{'literal':'done'}},'outcome':'guaranteed'}]}


def prompt(value):
    return ('⟦SYSTEM⟧\n[GUARDIAN_PLANNING]\n'+json.dumps(value)+'\n[/GUARDIAN_PLANNING]\n'
            '[AVAILABLE TOOLS]\n- prepare — Prepare.\n  ticket_id: string!\n'
            '- complete — Complete.\n  ticket_id: string!\n')


def run(value,**limits):
    text=prompt(value); events=parse_events(text,'prompt')
    return analyze_plan(events,parse_catalog(events,text),build_graph(events,[]),**limits)


class PlanningTests(unittest.TestCase):
    def test_two_step_plan_with_explicit_transitions(self):
        result=run(spec())
        self.assertEqual(result.status,'plan_in_declared_model')
        self.assertEqual([s['action'] for s in result.steps],['prepare','complete'])
        self.assertGreaterEqual(len(result.sources),3)

    def test_source_model_is_not_mutated(self):
        value=spec(); old=copy.deepcopy(value); run(value)
        self.assertEqual(value,old)

    def test_effects_without_preconditions_not_applied(self):
        value=spec(); value['initial']['phase']={'literal':'blocked'}
        self.assertEqual(run(value).status,'no_plan_in_declared_model')

    def test_unknown_initial_fact_is_not_guessed(self):
        value=spec(); value['initial']['phase']={'fact':{'tool':'lookup','role':'assistant','field':'phase',
                                                      'entity':{'ticket_id':{'literal':'T'}}}}
        self.assertEqual(run(value).status,'unknown')

    def test_initial_fact_uses_graph_and_sources(self):
        value=spec(); value['initial']['phase']={'fact':{'tool':'lookup','role':'assistant','field':'phase',
                                                      'entity':{'ticket_id':{'literal':'T'}}}}
        text=prompt(value)+'\n⟦TOOL_RESULT name="lookup" requestor="assistant"⟧\n{"ticket_id":"T","phase":"new"}'
        events=parse_events(text,'prompt')
        result=analyze_plan(events,parse_catalog(events,text),build_graph(events,[]))
        self.assertEqual(result.status,'plan_in_declared_model')
        self.assertTrue(any('TOOL_RESULT' in text[s.start:s.end] for s in result.sources))

    def test_conditional_success_remains_conditional(self):
        value=spec(); value['actions'][0]['outcome']='conditional'
        self.assertEqual(run(value).status,'conditional_plan')

    def test_refusal_not_labelled_from_plan_alone(self):
        review=Detector().review(prompt(spec()),'I cannot complete this request.')
        self.assertEqual(review.status,'unknown')
        self.assertEqual(review.planning['status'],'plan_in_declared_model')

    def test_unavailable_tool_prevents_plan(self):
        value=spec(); value['actions'][1]['tool']='invented'
        self.assertEqual(run(value).status,'unknown')

    def test_invalid_tool_arguments_prevent_plan(self):
        value=spec(); value['actions'][1]['arguments']={}
        self.assertEqual(run(value).status,'unknown')

    def test_depth_limit_is_not_proof_of_impossibility(self):
        self.assertEqual(run(spec(),max_depth=1).status,'unknown')

    def test_state_limit_is_explicit(self):
        self.assertEqual(run(spec(),max_states=1).status,'limit_reached')

    def test_inverted_goal_and_renaming(self):
        value=spec(); value['goal']=eq('phase','new')
        self.assertEqual(run(value).steps,[])
        text=prompt(spec()).replace('prepare','allocate').replace('complete','finish')
        events=parse_events(text,'prompt')
        result=analyze_plan(events,parse_catalog(events,text),build_graph(events,[]))
        self.assertEqual([s['tool'] for s in result.steps],['allocate','finish'])

    def test_user_planning_block_is_ignored(self):
        text=prompt(spec()).replace('⟦SYSTEM⟧','⟦USER⟧')
        events=parse_events(text,'prompt')
        self.assertIsNone(analyze_plan(events,parse_catalog(events,text),build_graph(events,[])))

    def test_code_and_unsupported_effects_are_rejected(self):
        for operation in ({'python':'raise RuntimeError()'},{'state':'undefined'}):
            value=spec(); value['actions'][0]['effects']['phase']=operation
            self.assertEqual(run(value).status,'unknown')
            self.assertIn('planning_invalid_model',run(value).issues)

    def test_bad_limits_are_rejected(self):
        for kwargs in ({'max_states':0},{'max_depth':True},{'max_depth':1.5}):
            with self.assertRaises(ValueError): run(spec(),**kwargs)


if __name__=='__main__': unittest.main()
