from collections import Counter
from scripts.v13_native_mining import paired,select,mining_text


def test_mining_preserves_twins_caps_templates_and_prioritises_false_accusations():
    rows=[];scores={}
    for i in range(30):
        for label in (0,1):
            r=dict(id=f'{i}:{label}',label=label,pair_id=str(i),domain='retail',family='consent',template_id=str(i//10))
            rows.append(r);scores[r['id']]=i if label==0 else 1
    chosen=select(rows,scores)
    assert len(chosen)==16 and len(paired(chosen))==8
    assert max(Counter(r['template_id'] for r in chosen).values())<=8
    assert {'29','28','27','26'}<={r['pair_id'] for r in chosen}
    assert '0' not in {r['pair_id'] for r in chosen}


def test_incomplete_pair_is_excluded_without_filling_from_other_data():
    r=dict(id='a',label=0,pair_id='p',domain='retail',family='consent',template_id='t')
    assert select([r],{'a':12})==[]


def test_binary_mining_asks_for_verdict_rather_than_first_rationale_token():
    from guardian_truth.judge.prompting import QUESTION
    from scripts.v7_prepare import REVIEW_QUESTION
    text=mining_text('<question>old question</question>')
    assert QUESTION in text
    assert REVIEW_QUESTION not in text
