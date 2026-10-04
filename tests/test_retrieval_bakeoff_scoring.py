import pytest
from experiments.retrieval_bakeoff_v1.scoring import covered, score_reference

def unit(start,end,document='prompt'):
    return dict(document=document,start=start,end=end,why='Original required evidence')

def source(start,end,document='prompt'):
    return dict(source_id=f'{document}:{start}',document=document,start=start,end=end)

def test_adjacent_windows_cover_original_without_gap():
    assert covered(unit(3,20),[source(0,10),source(10,30)])
    assert not covered(unit(3,20),[source(0,10),source(11,30)])

def test_other_document_cannot_cover_span():
    assert not covered(unit(0,10),[source(0,100,'response')])

def test_alternatives_and_partial_reference_are_distinct_from_proof():
    r=dict(required_history_sources=[unit(0,10),unit(30,40)],partial_reference=True,
           alternative_valid_evidence_sets=[[unit(0,10)],[unit(30,40)]])
    s=score_reference(r,dict(read_sources=[source(0,10)]))
    assert s['complete_evidence_set_success'] and s['reference_partial']
    assert s['categories']['history']['recall']==.5 and s['false_absence_risk']
    assert s['subset_absence_is_proof'] is False and s['completeness_certified'] is False

def test_empty_category_is_not_measured_perfect_recall():
    s=score_reference({},dict(read_sources=[]))
    assert s['categories']['exception']['recall'] is None
    assert not s['complete_evidence_set_success']

def test_valid_alternative_is_not_an_unnecessary_source():
    r=dict(required_history_sources=[unit(0,10)],alternative_valid_evidence_sets=[[unit(30,40)]])
    s=score_reference(r,dict(read_sources=[source(30,40)]))
    assert s['complete_evidence_set_success']
    assert s['unnecessary_relative_to_reference']==[]

def test_declaration_and_target_are_credited_from_attached_originals():
    r=dict(required_target_sources=[unit(0,10,'response')],required_declarations=[unit(2,12)])
    s=score_reference(r,dict(current_targets=[source(0,10,'response')],declarations=[source(0,20)]))
    assert s['complete_evidence_set_success']

@pytest.mark.parametrize('u',[unit(-1,3),unit(3,3),unit(True,5),unit(0,3,'other')])
def test_invalid_reference_does_not_get_silently_scored(u):
    with pytest.raises(ValueError):covered(u,[])
