"""CLI --repair v6fix: compact and --full output carry the v6fix result (findings, rules, coverage, certificate
bases, re-check) and separate the code-checked fact from the norm basis. Network-free: model parts are stubbed."""
import json

import pytest

from v6fix_fixtures import call, packet, user

UNDECL = packet([user('h0', 'hi')], [call('t0', 'no_such_tool', {})], status={'no_such_tool': 'UNDECLARED_IN_COMPLETE_PARSED_CATALOG'})
HYP = packet([user('h0', 'hi')], [call('t0', 'get_order', {'order_id': 'X-404'})])      # no contract -> hypothesis only


@pytest.fixture
def stub(monkeypatch):
    import guardian_truth.integrated.cli as cli
    import guardian_truth.repair.v5 as v5
    import guardian_truth.verification.pipeline as vp
    from guardian_truth.v6fix import turnrules as F
    box = {}
    monkeypatch.setattr(vp, 'packet_for', lambda row, budget: dict(box['p'], _budget=budget))
    monkeypatch.setattr(v5, 'run_v5', lambda row, client, **k: {'A': {'final': 'NO_ERROR', 'guard_error': None}, 'pool': [], 'components': {}})
    monkeypatch.setattr(v5, 'decide', lambda rec: (0, None))
    monkeypatch.setattr(F, 'extract', lambda client, model, srcs: dict(runs=[[], []], raw=['[]', '[]'], steps=[], n_lines=1))
    monkeypatch.setattr(cli, 'Transport', lambda *a, **k: None)
    import guardian_truth.repair.clients as cl
    monkeypatch.setattr(cl, 'ReadThrough', lambda *a, **k: None)
    return cli, box


def _run(stub, tmp_path, p, *extra):
    cli, box = stub
    box['p'] = p
    f, o = tmp_path / 'in.jsonl', tmp_path / 'out.jsonl'
    f.write_text(json.dumps(dict(prompt='x', response='y')) + '\n')
    assert cli.main([str(f), '--repair', 'v6fix', '--provider', 'mistral', '--output', str(o), *extra]) == 0
    return json.loads(o.read_text().splitlines()[0])


def test_compact_output_has_certificate_bases(stub, tmp_path):
    r = _run(stub, tmp_path, UNDECL)
    assert r['binary'] == 1 and r['accusation']['certificate'] == 'MECHANICAL' and r['decision_owner'] == 'S'
    m = r['mechanical'][0]
    assert m['fact_basis'] == 'CODE_CHECKED_ON_INPUT' and m['norm_basis'] == 'CONTRACT_TEXT' and m['decisive']
    assert r['layer_budget_bytes'] == 20000          # same context as r_fix by default


def test_hypothesis_is_reported_not_decisive(stub, tmp_path):
    r = _run(stub, tmp_path, HYP)
    assert r['binary'] == 0 and r['accusation'] is None
    assert [(m['kind'], m['status'], m['decisive']) for m in r['mechanical']] == [('UNSOURCED_REFERENCE', 'HYPOTHESIS', False)]


def test_full_output_is_the_v6fix_result(stub, tmp_path):
    r = _run(stub, tmp_path, UNDECL, '--full', '--layer-budget-bytes', '400000')
    assert set(r) == {'result', 'layers', 'recheck', 'r_fix'}
    assert r['result']['binary'] == 1 and r['layers']['budget'] == 400000
    assert {'findings', 'rules', 'records', 'coverage', 'extraction'} <= set(r['layers'])
    assert r['recheck'] == [dict(kind='UNDECLARED_TOOL', target_id='t0', recheck=True)]
