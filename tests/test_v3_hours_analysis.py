import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from v3_analyze_hours import metrics,quota,at_recall,paired_ci

def test_false_accusation_share_is_distinct_from_false_positive_rate():
    result=metrics([1,1,0,0,0],[1,0,1,1,0])
    assert result['false_discovery_rate']==2/3
    assert result['fpr']==2/3
    other=metrics([1,1,0,0],[1,0,1,1])
    assert other['false_discovery_rate']==2/3 and other['fpr']==1

def test_hard_rows_consume_quota_and_can_exceed_it():
    assert quota([8,8,1,0],{3},.5)==[1,0,0,1]
    assert quota([8,1,0],{1,2},.4)==[0,1,1]
    result=at_recall([1,0,1,0],[1,3,2,0],.5,{3})
    assert result['tp']==1 and result['fp']==2 and result['recall']==.5

def test_identical_models_have_zero_paired_intervals():
    result=paired_ci([0,1,0,1],[0,3,2,1],[0,3,2,1],['a','a','b','b'])
    assert result['f1_difference']['ci95']==[0,0]
    assert result['auc_difference']['ci95']==[0,0]
    assert result['matched_615_fp_relative_reduction']['ci95']==[0,0]
