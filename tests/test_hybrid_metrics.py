import pytest
from experiments.hybrid_diagnostics.metrics import metric,group


def test_empty_and_all_negative_do_not_invent_positive_f1():
    assert metric([])['F1'] is None and metric([])['n']==0
    assert metric([(0,'NO_ERROR')])['F1'] is None


def test_unknown_projection_keeps_real_false_negative():
    m=metric([(1,'UNKNOWN'),(0,'NO_ERROR')])
    assert m['FN']==1 and m['TN']==1 and m['F1']==0 and m['UNKNOWN']==1
    with pytest.raises(ValueError):metric([(1,None)])


def test_additional_cases_are_not_factorial_denominators():
    a=dict(name='mistral_telecom_I4',case='telecom',provider='mistral',stage=None)
    b=dict(a,name='mistral_exception_I4',case='exception')
    assert group(a)=='I4' and group(b)=='EXTRA_I4'
