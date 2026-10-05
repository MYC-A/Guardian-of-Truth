"""P0 hygiene: the public default must be the recommended frozen A2 ('guard') profile."""
from guardian_truth.integrated import ReviewConfig, review
from guardian_truth.integrated import cli
from guardian_truth.integrated.pipeline import PROFILES


def test_default_config_equals_guard_profile():
    assert ReviewConfig() == ReviewConfig.profile('guard')
    assert PROFILES['guard'] == dict(guard=True, relations=False, controller=False)


def test_default_review_request_identical_to_guard(tmp_path):
    from guardian_truth.integrated import StaticClient
    import pandas as pd
    row = pd.read_parquet('valid.parquet').iloc[0]
    c1, c2 = StaticClient(lambda r: None), StaticClient(lambda r: None)
    a = review(row.prompt, row.response, client=c1)
    b = review(row.prompt, row.response, ReviewConfig.profile('guard'), client=c2)
    assert c1.calls[0]['request'] == c2.calls[0]['request'] and a['config'] == b['config']
    assert a['relations'] is None and len(a['steps']) == 1


def test_cli_default_profile_is_guard():
    src = open(cli.__file__).read()
    assert "default='guard'" in src and "default='integrated'" not in src
