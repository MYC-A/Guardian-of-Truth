"""Regression for wasted review after rejected/empty source discovery."""
from experiments.hybrid_mechanisms.runner import rows,catalog
from experiments.telecom_causal_recovery.packets import extract
from experiments.hybrid_mechanisms.retrieval import BoundedRetrieval
from experiments.hybrid_mechanisms.transport import read
from experiments.hybrid_diagnostics.guarded_plan import execute_or_stop
from pathlib import Path


def controller():
    row=rows()['telecom'];g,_,_=extract(row);cat=catalog(row)
    return BoundedRetrieval(g.store,cat['normative_catalog']+cat['history_catalog'],['t0'])


def no_review(_):raise AssertionError('Unexpected semantic/API review')


def test_actual_invalid_plan_cannot_invoke_review():
    plan=read(Path('outputs/hybrid_mechanisms_v1/retrieval/R1_plan_failure.json'))['reply']
    r=execute_or_stop(controller(),plan,no_review)
    assert r['status']=='PLAN_ADMISSION_FAILED' and r['failure']=='GAP_SOURCE_NAMESPACE_INVALID'
    assert r['decision'] is None and r['review_called'] is False
    assert r['controller_state']['distinct_complete_reads']==0


def test_search_navigation_is_not_enough_for_review():
    plan=dict(operations=[dict(operation='SEARCH_SOURCES',source_id=None,query='contract')],gaps=[],sufficient=False)
    r=execute_or_stop(controller(),plan,no_review)
    assert r['status']=='NO_COMPLETE_SOURCE_EVIDENCE' and r['decision'] is None


def test_valid_read_allows_review_without_proving_verdict():
    seen=[]
    r=execute_or_stop(controller(),dict(operations=[dict(operation='READ_SOURCE',source_id='h10',query=None)],gaps=[],sufficient=False),lambda context:seen.append(context) or {'decision':'UNKNOWN'})
    assert len(seen)==1 and r['review_called'] and r['code_proof'] is False
    assert r['review']['decision']=='UNKNOWN'
