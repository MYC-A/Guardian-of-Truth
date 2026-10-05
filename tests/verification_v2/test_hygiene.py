"""P0 hygiene: the public default must be the recommended profile ('guard_adm2' = frozen A2 'guard' + admission v2,
adopted by pre-registered LB2 rule 1); 'guard' itself stays the frozen integrated-v1 A2 (admission v1)."""
from guardian_truth.integrated import ReviewConfig, review
from guardian_truth.integrated import cli
from guardian_truth.integrated.pipeline import PROFILES


def test_default_config_equals_guard_profile():
    assert ReviewConfig() == ReviewConfig.profile('guard_adm2')
    assert PROFILES['guard'] == dict(guard=True, relations=False, controller=False, admission='v1')
    assert ReviewConfig.profile('guard').admission == 'v1'


def test_default_review_request_identical_to_guard(tmp_path):
    from guardian_truth.integrated import StaticClient
    import pandas as pd
    row = pd.read_parquet('valid.parquet').iloc[0]
    c1, c2 = StaticClient(lambda r: None), StaticClient(lambda r: None)
    a = review(row.prompt, row.response, client=c1)
    b = review(row.prompt, row.response, ReviewConfig.profile('guard'), client=c2)
    assert c1.calls[0]['request'] == c2.calls[0]['request']          # admission never changes the request bytes
    assert {k: v for k, v in a['config'].items() if k != 'admission'} == {k: v for k, v in b['config'].items() if k != 'admission'}
    assert a['relations'] is None and len(a['steps']) == 1


def test_cli_default_profile_is_guard_adm2():
    src = open(cli.__file__).read()
    assert "default='guard_adm2'" in src and "default='integrated'" not in src


def test_guard_adm2_profile_only_changes_admission():
    from guardian_truth.integrated.pipeline import PROFILES, ReviewConfig
    a, b = ReviewConfig.profile('guard'), ReviewConfig.profile('guard_adm2')
    assert a.admission == 'v1' and b.admission == 'v2'
    assert {k: v for k, v in vars(a).items() if k != 'admission'} == {k: v for k, v in vars(b).items() if k != 'admission'}
