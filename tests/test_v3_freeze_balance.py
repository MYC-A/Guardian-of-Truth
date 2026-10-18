import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from v3_freeze_hours_split import balance_training_pairs


def row(source,pair,index,label):
    return dict(id=f'{source}:{pair}:{index}',source=source,pair_id=pair,
                label=label,is_hard_negative=not label)


def test_class_repair_preserves_pairs_sources_and_input_order():
    rows=[]
    for source in ('a','b','c'):
        for pair in range(5):
            rows.extend([row(source,str(pair),0,0),row(source,str(pair),1,1)])
        rows.append(row(source,'singleton',0,0))
        rows.append(row(source,'singleton2',0,0))
    retained,removed=balance_training_pairs(rows)
    assert removed
    assert sum(r['label'] for r in retained)<=.4*len(retained)
    retained_ids={r['id'] for r in retained}
    assert retained==[r for r in rows if r['id'] in retained_ids]
    for source in ('a','b','c'):
        assert sum(r['source']==source for r in retained)<=.4*len(retained)
        for pair in range(5):
            assert sum(r['source']==source and r['pair_id']==str(pair) for r in retained) in (0,2)
    assert balance_training_pairs(rows)==(retained,removed)


def test_compliant_selection_is_unchanged_and_impossible_repair_fails():
    rows=[row(source,str(i),i,int(i==0)) for source in ('a','b','c') for i in range(3)]
    assert balance_training_pairs(rows)==(rows,[])
    with pytest.raises(ValueError,match='NO_PAIR_PRESERVING'):
        balance_training_pairs([row(source,'pair',i,i) for source in ('a','b','c') for i in (0,1)])
