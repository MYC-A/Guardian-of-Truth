import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from v4_analyze import evaluate


def test_rank_blend_recomputed_on_supplied_batch_and_shape_keeps_legacy_hard():
    data=[dict(label=y,hard=h,shape=s,scores={'current35b':b,'base4b':b,'v4':a})
          for y,h,s,b,a in [(1,True,False,0,0),(0,False,False,1,3),(1,False,True,2,1),(0,False,False,3,2)]]
    result,ref=evaluate(data,np.arange(4),shape=True,rate=.4)
    assert ref=='current35b'
    assert all(r['metrics']['tp']==2 for r in result.values())
    assert all(r['matched_tp']['tp']==2 for r in result.values())
    # Rank ordering in a repeated/resampled batch is recomputed rather than
    # treating full-cohort percentile scores as fixed scalar measurements.
    sample=[data[i] for i in [3,3,2,0]]
    again,_=evaluate(sample,np.arange(4),shape=False,rate=.5)
    assert set(again)=={'current35b','base4b','v4','blend_v4'}
    assert again['current35b']['metrics']['tp']>=1
