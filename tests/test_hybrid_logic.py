"""Finite source exploration and conservative consistency boundaries."""
import pytest
from guardian_truth.source_search.store import SourceStore
from experiments.hybrid_mechanisms.retrieval import BoundedRetrieval
from experiments.hybrid_mechanisms.consistency import audit_consistency, proof_adapter, IndependentQualification, hypothesis_adapter


def store_and_catalog(n=9):
    # Independent adjacent full-source records, not an oracle list for Telecom.
    text = '\n'.join('record %s %s' % (i,'x'*100) for i in range(n))
    s = SourceStore(dict(prompt=text,response='current request'))
    sources, start = [], 0
    for line in text.splitlines(keepends=True):
        sid = s.quote_id('prompt',start,start+len(line))
        sources.append(dict(source_id=sid,title='original'))
        start += len(line)
    return s,sources


def read(sid):
    return dict(operation='READ_SOURCE',source_id=sid,query=None)


def gap(sid,status='OPEN'):
    return dict(gap_id='G1',question='What fact supports this condition?',required_fact_type='ENTITY_STATE',
                policy_sources=[],target_sources=['response'],candidate_source_ids=[sid],
                visited_source_ids=[sid],supporting_sources=[sid] if status=='RESOLVED' else [],status=status,
                unresolved_reason=None)


def test_complete_large_read_preserves_offsets_and_originals():
    s=SourceStore(dict(prompt='A'*18011,response='current'))
    c=BoundedRetrieval(s,[dict(source_id='prompt')],['response'])
    before=dict(s.raw)
    c.step(dict(operations=[read('prompt')]))
    got=c.result()['read_sources'][0]
    assert got['text']==before['prompt'] and s.raw==before
    assert len(got['windows'])==3
    assert [w['start'] for w in got['windows']]==[0,8000,16000]
    assert got['coverage']=='COMPLETE_SELECTED_SOURCE'


def test_repeated_read_stops_without_extra_evidence():
    s,cat=store_and_catalog()
    c=BoundedRetrieval(s,cat,['response'])
    sid=cat[0]['source_id']
    c.step(dict(operations=[read(sid)],gaps=[gap(sid)]))
    c.step(dict(operations=[read(sid)],gaps=[gap(sid)]))
    assert c.result()['distinct_complete_reads']==1
    assert c.stop_reason=='NO_NEW_SOURCE'
    assert c.traces[-1]['results'][0]['status']=='ALREADY_READ'


def test_eight_distinct_reads_enforced_across_rounds():
    s,cat=store_and_catalog()
    c=BoundedRetrieval(s,cat,['response'])
    c.step(dict(operations=[read(x['source_id']) for x in cat[:7]]))
    c.step(dict(operations=[read(cat[7]['source_id']),read(cat[8]['source_id'])],gaps=[gap(cat[8]['source_id'],'RESOLVED')]))
    assert len(c.read_sources)==8 and c.stop_reason=='READ_LIMIT'
    assert c.gaps['G1']['status']=='UNRESOLVED'
    assert c.gaps['G1']['supporting_sources']==[]
    assert c.traces[-1]['results'][-1]['status']=='READ_LIMIT'
    with pytest.raises(ValueError,match='TERMINAL'):
        c.step(dict(operations=[]))


def test_search_is_navigation_and_does_not_resolve_evidence():
    s,cat=store_and_catalog()
    c=BoundedRetrieval(s,cat,['response'])
    op=dict(operation='SEARCH_SOURCES',source_id=None,query='record')
    c.step(dict(operations=[op]))
    assert not c.read_sources
    assert c.navigation[0]['result']['admitted_as_evidence'] is False
    with pytest.raises(ValueError,match='NOT_COMPLETELY_READ'):
        c.step(dict(operations=[],gaps=[gap(cat[0]['source_id'],'RESOLVED')]))
    assert len(c.traces)==1


@pytest.mark.parametrize('op',[dict(operation='WRITE_SOURCE',source_id='prompt'),
    dict(operation='READ_SOURCE',source_id='made_up',query=None),
    dict(operation='READ_SOURCE',source_id='prompt',query='covert search')])
def test_invalid_entire_plan_has_no_admitted_mutation(op):
    s,cat=store_and_catalog()
    c=BoundedRetrieval(s,cat,['response'])
    with pytest.raises(ValueError):
        c.step(dict(operations=[read(cat[0]['source_id']),op]))
    assert not c.read_sources and not c.traces


def test_round_limit_prevents_loop_with_new_sources():
    s,cat=store_and_catalog()
    c=BoundedRetrieval(s,cat,['response'])
    iterator=iter(cat)
    r=c.run(lambda context:dict(operations=[read(next(iterator)['source_id'])]))
    assert r['rounds']==3 and r['stop_reason']=='ROUND_LIMIT'
    assert r['distinct_complete_reads']==3
    assert r['completeness_certified'] is False


def norm(**changes):
    n=dict(modality='FORBID',applicability='YES',condition='TRUE',exception='FALSE',violated='TRUE')
    return {**n,**changes}


def test_gate_detects_typed_contradiction_without_flipping_label():
    r=dict(decision='NO_ERROR',norm_assessments=[norm()])
    gate=audit_consistency(r)
    assert gate['status']=='POTENTIAL_CONTRADICTION'
    assert gate['decision']==r['decision']=='NO_ERROR' and gate['changed'] is False
    assert gate['semantic_truth_certified'] is False


def test_gate_does_not_keyword_repair_old_free_text():
    r=dict(decision='NO_ERROR',reason='This violates the prohibition; forbidden action',applicable_norms=[])
    assert audit_consistency(r)['status']=='NO_TYPED_CONTRADICTION_FOUND'


@pytest.mark.parametrize('changes',[dict(applicability='UNKNOWN',violated='UNKNOWN'),
    dict(condition='UNKNOWN',violated='UNKNOWN'),dict(exception='UNKNOWN',violated='UNKNOWN'),
    dict(modality='PERMIT',violated='FALSE')])
def test_uncertainty_or_permission_does_not_create_warning(changes):
    assert audit_consistency(dict(decision='NO_ERROR',norm_assessments=[norm(**changes)]))['flags']==[]


def qualified():
    return IndependentQualification(('p1',),'t0',('h1',),('p1',),True,True,True,'manual_source_audit_1')


def proof():
    return dict(modality='FORBID',applicability='YES',condition='TRUE',exception='FALSE',
                target_id='t0',source_refs=['p1','t0','h1'])


def test_model_bool_hypothesis_cannot_become_independent_proof():
    r=proof_adapter(proof(),dict(applicability_confirmed=True,state_relation_confirmed=True,
       exception_closure_confirmed=True),['p1','t0','h1'])
    assert r['decision']=='UNKNOWN' and r['reason']=='NO_INDEPENDENT_QUALIFICATION'


def test_qualified_adapter_is_explicitly_oracle_assisted():
    r=proof_adapter(proof(),qualified(),['p1','t0','h1'])
    assert r['decision']=='ERROR'
    assert r['qualification_kind']=='INDEPENDENT_SOURCE_AUDIT_ASSISTED'
    assert r['semantic_truth_certified'] is False


@pytest.mark.parametrize('changes',[dict(exception='UNKNOWN'),dict(modality='REQUIRE'),
    dict(target_id='user_action'),dict(source_refs=['t0']),dict(source_refs=['p1','t0','made_up'])])
def test_unsupported_or_incomplete_proof_stays_unknown(changes):
    assert proof_adapter({**proof(),**changes},qualified(),['p1','t0','h1'])['decision']=='UNKNOWN'


def test_exception_closure_requires_independent_source_support():
    q=IndependentQualification(('p1',),'t0',('h1',),(),True,True,True,'audit')
    assert proof_adapter(proof(),q,['p1','t0','h1'])['reason']=='QUALIFICATION_SOURCE_COVERAGE_MISSING'


def semantics(n=None,**changes):
    n=norm() if n is None else n
    n={**n,'target_id':'t0','policy_source_id':'p1','source_refs':['t0','p1','h1']}
    return dict(norm_assessments=[n],coverage='SUFFICIENT',open_questions=[],**changes)


def test_hypothesis_adapter_error_is_not_independent_proof():
    result=hypothesis_adapter(semantics())
    assert result['decision']=='ERROR'
    assert result['independent_proof_decision']=='UNKNOWN'
    assert result['code_proof'] is False and result['semantic_truth_certified'] is False


def test_hypothesis_adapter_known_violation_survives_incomplete_other_coverage():
    s=semantics();s['coverage']='INSUFFICIENT';s['open_questions']=['Another norm remains unresolved.']
    assert hypothesis_adapter(s)['decision']=='ERROR'


def test_hypothesis_adapter_requirement_false_is_violation():
    assert hypothesis_adapter(semantics(norm(modality='REQUIRE',condition='FALSE')))['decision']=='ERROR'


def test_hypothesis_adapter_typed_conflict_cannot_be_repaired_by_prose():
    s=semantics(norm(violated='FALSE'));s['reason']='Definitely violates policy.'
    result=hypothesis_adapter(s)
    assert result['decision']=='UNKNOWN' and result['reason']=='INCONSISTENT_SEMANTIC_HYPOTHESES'


def test_hypothesis_adapter_uncertain_exception_cannot_accuse():
    assert hypothesis_adapter(semantics(norm(exception='UNKNOWN')))['decision']=='UNKNOWN'


def test_hypothesis_adapter_no_error_requires_sufficient_declared_coverage():
    s=semantics(norm(condition='FALSE',violated='FALSE'))
    assert hypothesis_adapter(s)['decision']=='NO_ERROR'
    s['coverage']='INSUFFICIENT'
    assert hypothesis_adapter(s)['decision']=='UNKNOWN'


def test_hypothesis_adapter_current_norm_citations_required():
    s=semantics();s['norm_assessments'][0]['source_refs']=['h1']
    assert hypothesis_adapter(s)['decision']=='UNKNOWN'
