from scripts.v10_offbox_report import quota_bootstrap


def test_bootstrap_reranks_so_a_previously_unselected_tp_can_become_exposed():
    rows=[dict(id=str(i),original_id=str(i),group=str(i)) for i in range(4)]
    gold={str(i):int(i==2) for i in range(4)}
    # Native quota selects indices0,1; only row2 is vetoed. A fixed-prediction
    # bootstrap would claim zero lostTP in every draw, missing quota reselection.
    result=quota_bootstrap(rows,gold,set(),{i:4-i for i in range(4)},
        {'base':[True]*4,'new':[True,True,False,True]})
    assert result['difference_95pct']['base']['tp']==[0.,0.]
    assert result['difference_95pct']['new']['tp'][0]<0
    assert result['quota_and_ranking_recomputed_per_draw'] is True
