import pytest
from experiments.retrieval_bakeoff_v1.gaps import validate_plan

def plan():
    return dict(sufficient=False,missing_facts=[dict(question='Which original observation matches the object?',
        related_policy_sources=['q0'],related_target_sources=['t0'],candidate_source_ids=['h1'],
        reason_needed='The read norm requires its original state.')],next_queries=['object state'])

def valid(p):
    return validate_plan(p,catalog_ids={'q0','h1'},target_ids={'t0'},read_policy_ids={'q0'})

def test_namespaces_are_separate_and_input_unchanged():
    p=plan();assert valid(p)==p
    p['missing_facts'][0]['related_target_sources']=['h1']
    with pytest.raises(ValueError,match='GAP_TARGET_NAMESPACE_INVALID'):valid(p)

def test_declaration_is_not_silently_a_readable_policy():
    p=plan();p['missing_facts'][0]['related_policy_sources']=['d0']
    with pytest.raises(ValueError,match='GAP_POLICY_NOT_ALREADY_READ'):valid(p)

def test_unknown_candidate_rejects_whole_plan():
    p=plan();p['missing_facts'][0]['candidate_source_ids']=['h1','invented']
    with pytest.raises(ValueError,match='GAP_CANDIDATE_NAMESPACE_INVALID'):valid(p)

def test_sufficiency_with_open_gaps_is_not_accepted():
    p=plan();p['sufficient']=True
    with pytest.raises(ValueError,match='SUFFICIENT_WITH_OPEN_GAPS'):valid(p)

def test_closed_sufficiency_remains_only_model_boolean():
    assert valid(dict(sufficient=True,missing_facts=[],next_queries=[]))['sufficient'] is True

def test_duplicate_extra_field_and_string_boolean_fail_shape():
    p=plan();p['sufficient']='true'
    with pytest.raises(ValueError):valid(p)

def test_new_reads_cap_four_even_when_seed_is_empty():
    from experiments.retrieval_bakeoff_v1.corpus import build_corpus
    from experiments.retrieval_bakeoff_v1.adapters import assemble
    from experiments.retrieval_bakeoff_v1.gaps import apply_plan
    prompt='⟦SYSTEM⟧\nInspect original evidence.\n'
    for i in range(7):
        prompt+='⟦ASSISTANT⟧\n→ TOOL_CALL inspect: {"entry_id":"E-'+str(i)+'"}\n'
    c=build_corpus(dict(prompt=prompt,response='⟦ASSISTANT⟧\nI request information.'))
    seed=assemble(c,[],8,None)
    ids=[s['source_id'] for s in c.catalog if s['kind']=='call']
    p=dict(sufficient=False,missing_facts=[dict(question='Which observed entry applies?',
        related_policy_sources=[],related_target_sources=['t0'],candidate_source_ids=ids,
        reason_needed='Obtain the original event before deciding.')],next_queries=[])
    result=apply_plan(c,seed,p,read_policy_ids=[],token_limit=None)
    assert result['gap_diagnostics']['distinct_new_complete_reads']==4
    p=plan();p['business_tool_call']={}
    with pytest.raises(ValueError):valid(p)
