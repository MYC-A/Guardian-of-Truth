"""Quantifier isolation, unknown values, cycles and actual call-scope tests."""
import unittest
from acceptance import ROOT
from guardian_truth.source_search.store import SourceStore
from predicate_witness import evaluate


def node(id,op,args=(),**fields):
    return {'id':id,'op':op,'args':list(args),'source_id':None,'pointer':None,
            'quote':None,'variable':None,'boolean':None,**fields}


def setup(payload):
    import json
    store=SourceStore({'prompt':'⟦SYSTEM⟧\nRecords require owner U1 and status READY.\n'
        '⟦USER⟧\nI am U1.\n⟦ASSISTANT⟧\n← TOOL_RESPONSE inspect: '+json.dumps(payload)+'\n',
        'response':'No eligible record exists.'})
    formula={'policy_evidence':{'source_id':'h0','quote':'Records require owner U1 and status READY.'},
        'target_source_id':'t0','target_kind':'TEXT_CLAIM','governed_tool':None,'gaps':[],
        'interpretation':'existence of one eligible same record','error_root':'exists','nodes':[
            node('records','DATA',source_id='h2',pointer='/records'),
            node('owner','BOUND',variable='r',pointer='/owner'),
            node('status','BOUND',variable='r',pointer='/status'),
            node('user','TEXT',source_id='h1',quote='U1'),
            node('ready','TEXT',source_id='h0',quote='READY'),
            node('owns','EQ',['owner','user']),node('active','EQ',['status','ready']),
            node('eligible','AND',['owns','active']),
            node('exists','ANY',['records','eligible'],variable='r')]}
    return store,formula


class Tests(unittest.TestCase):
    def test_same_record_join_and_false_cross_record_join(self):
        for rows,expected in [([{'owner':'U1','status':'OLD'},{'owner':'U2','status':'READY'}],False),
                              ([{'owner':'U1','status':'READY'}],True)]:
            s,f=setup({'records':rows}); self.assertIs(evaluate(s,f)['predicate_value'],expected)

    def test_missing_status_is_unknown_not_false(self):
        s,f=setup({'records':[{'owner':'U1'}]})
        self.assertIsNone(evaluate(s,f)['predicate_value'])

    def test_cycle_does_not_establish_error(self):
        s,f=setup({'records':[]}); f['nodes'].append(node('cycle','NOT',['cycle'])); f['error_root']='cycle'
        self.assertIsNone(evaluate(s,f)['predicate_value'])

    def test_no_invented_comparison_literal(self):
        s,f=setup({'records':[{'owner':'U1','status':'READY'}]})
        next(n for n in f['nodes'] if n['id']=='ready')['quote']='INVENTED'
        self.assertIsNone(evaluate(s,f)['predicate_value'])

    def test_native_gate_does_not_attach_to_lookup(self):
        s=SourceStore({'prompt':'⟦SYSTEM⟧\nTool commit requires approval; lookup reads only.\n⟦USER⟧\nCheck state.',
                       'response':'→ TOOL_CALL lookup: {"id":"R1"}'})
        f={'policy_evidence':{'source_id':'h0','quote':'Tool commit requires approval; lookup reads only.'},
           'target_source_id':'t0','target_kind':'NATIVE_CALL','governed_tool':'commit',
           'nodes':[],'error_root':None,'gaps':[],'interpretation':'commit gate'}
        self.assertIs(evaluate(s,f)['predicate_value'],False)


if __name__=='__main__': unittest.main()
