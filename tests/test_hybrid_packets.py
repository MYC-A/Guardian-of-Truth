"""Original-event integration, factorial isolation and failure-boundary tests."""
import json
import pytest
from experiments.hybrid_mechanisms import interfaces,packets,runner
from experiments.hybrid_mechanisms.transport import serialized
from experiments.hybrid_mechanisms.retrieval import BoundedRetrieval
from experiments.telecom_causal_recovery import packets as old


def test_whole_move_original_scopes():
    pp=runner.prepared();rr=runner.rows()
    assert [s['source_id'] for s in pp['multicall']['current_targets']]==['t0','t1','t2','t3']
    assert pp['bank']['native_target_inventory']==[]
    assert pp['bank']['current_targets'][0]['kind']=='text'
    for name,p in pp.items():assert packets.validate_packet(rr[name],p)['coverage']=='DISCLOSED_SELECTED_SOURCES'


def test_factorial_changes_only_declared_factors():
    p=runner.prepared()['telecom']
    b={i:interfaces.body(p,'mistral','ministral-14b-2512',i) for i in ('I1','I2','I3','I4')}
    assert b['I1']['messages']==b['I2']['messages']
    assert b['I3']['messages']==b['I4']['messages']
    assert b['I1']['messages'][1]==b['I3']['messages'][1]
    assert b['I3']['messages'][0]['content']==b['I1']['messages'][0]['content']+interfaces.LABELS
    schemas={i:v['response_format']['json_schema']['schema'] for i,v in b.items()}
    assert list(schemas['I1']['properties'])[0]=='decision'
    assert list(schemas['I2']['properties'])[-1]=='decision'
    assert schemas['I1']==schemas['I3'] and schemas['I2']==schemas['I4']
    assert serialized(b['I1'])!=serialized(b['I2'])


def test_facts_do_not_expand_source_coverage():
    pp=runner.prepared();rr=runner.rows()
    for name in ('telecom','bank'):
        allowed=set(packets.sources(pp[name]))
        for f in packets.facts(rr[name],pp[name]):
            for key in ('source_ids','right_source_ids'):
                assert set(f.get(key,[]))<=allowed
            if 'left_source' in f:assert f['left_source'] in allowed
            for r in f.get('receipts',[]):assert {r['call_source'],r['result_source']}<=allowed
    assert len(packets.facts(rr['telecom'],pp['telecom'],True))<len(packets.facts(rr['telecom'],pp['telecom']))


def test_conflicts_use_prediction_refs_not_fixed_business_ids():
    row=runner.rows()['telecom']
    empty=packets.conflicts(row,dict(evidence_ids=[]))
    assert empty['diagnostics']==[]
    c=packets.conflicts(row,dict(evidence_ids=['h30','t0']))
    assert c['diagnostics'][0]['actor']=='user'
    assert c['diagnostics'][1]['is_current_move'] is True
    assert all('POTENTIAL' in d['conclusion'] for d in c['diagnostics'])


@pytest.mark.parametrize('choices',[None,{},[],[None],[dict(message=None)]])
def test_decode_bad_provider_is_technical_failure(choices):
    r=dict(request_sha256='x',status='OK',provider_response=dict(model='m',choices=choices))
    v=runner.decode(r,None,runner.prepared()['telecom'])
    assert v['decision'] is None and v['failure']


def test_real_coverage_reads_early_fact_and_preserves_spans():
    row=runner.rows()['telecom'];cat=runner.catalog(row);g,_,_=old.extract(row)
    c=BoundedRetrieval(g.store,cat['normative_catalog']+cat['history_catalog'],['t0'],max_rounds=2)
    c.step(runner.coverage_plan(row,cat))
    assert len(c.result()['read_sources'])<=8
    # This asserts the predeclared generic identity/temporal rule's measured
    # behavior on this regression; runtime selection contains no h10 constant.
    assert 'h10' in {s['source_id'] for s in c.result()['read_sources']}
    packets.validate_packet(row,runner.retrieval_packet(row,cat,c.context()))
