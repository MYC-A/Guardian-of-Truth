from scripts.v12_transfer import filtered


def test_veto_protects_hard_unknown_and_does_not_refill_or_add_positives():
    before=[1,1,1,1,1,0,0]
    values={0:dict(admitted=True,score=-20),1:dict(admitted=False,score=None),
            2:dict(admitted=True,score=-.1),3:dict(admitted=True,score=0),
            4:dict(admitted=True,score=.01)}
    assert filtered(before,{0},values)==[1,1,0,0,1,0,0]


def test_missing_positive_verification_fails_instead_of_silently_succeeding():
    import pytest
    with pytest.raises(KeyError):
        filtered([1],set(),{})
