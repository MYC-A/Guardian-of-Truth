import pytest
from scripts.v16_final_regressions import apply_veto


def test_final_regression_reports_lost_true_positive_and_protects_hard():
    rows=[dict(id=str(i),label=int(i!=2)) for i in range(4)]
    scores={r['id']:dict(admitted=True,score=-1) for r in rows}
    result=apply_veto(rows,[1,1,1,0],{0},scores)
    assert result['lost_tp']==1 and result['removed_fp']==1
    assert result['after']['tp']==1 and result['after']['fn']==2
    with pytest.raises(ValueError,match='JOIN'):apply_veto(rows,[1,1,1,0],{0},{})
