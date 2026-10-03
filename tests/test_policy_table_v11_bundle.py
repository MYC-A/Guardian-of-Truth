import copy
import json
import pytest
from test_policy_table_v11 import store, policy, atomic
from guardian_truth.policy_table_v11.bundle import (BundleError, build_bundle, compile_from_replies, verify_bundle,
                                                    load_bundle, write_bundle)
from guardian_truth.policy_table_v11.service import Gate, main, score

TRIGGER = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}


def replies(s, n=3):
    a = atomic().model_dump()
    return [{'policy': policy(s)['policy_sha256'], 'trigger': TRIGGER, 'proposer': f'p{i}',
             'family': ['one', 'two', 'three'][i], 'response': {'atoms': [a]}} for i in range(n)]


def compiled(s):
    tables, coverage = compile_from_replies({policy(s)['policy_sha256']: policy(s)}, replies(s))
    return tables, coverage


def test_compile_requires_three_proposers_and_reports_gap():
    s = store()
    tables, coverage = compile_from_replies({policy(s)['policy_sha256']: policy(s)}, replies(s, 2))
    assert tables == [] and coverage[policy(s)['policy_sha256']]['reason'] == 'needs_3_proposers_have_2'


def test_sha_bundle_roundtrip_and_tamper_detection(tmp_path):
    s = store(); tables, coverage = compiled(s)
    bundle = build_bundle(tables, coverage=coverage, key='')
    assert bundle['signature']['algorithm'] == 'SHA256' and len(bundle['tables']) == 1
    write_bundle(bundle, tmp_path / 'b.json'); assert load_bundle(tmp_path / 'b.json', key='')
    bad = copy.deepcopy(bundle); next(iter(bad['tables'].values()))['atoms'][0]['status'] = 'SHADOW'
    with pytest.raises(BundleError): verify_bundle(bad, key='')
    with pytest.raises(BundleError): verify_bundle(bundle, key='', require_hmac=True)


def test_hmac_bundle_needs_matching_key():
    s = store(); tables, coverage = compiled(s)
    bundle = build_bundle(tables, coverage=coverage, key='secret')
    assert verify_bundle(bundle, key='secret')['signature']['algorithm'] == 'HMAC-SHA256'
    with pytest.raises(BundleError): verify_bundle(bundle, key='other')
    with pytest.raises(BundleError): verify_bundle(bundle, key='')


def test_gate_uses_bundle_table_without_llm():
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n'); tables, _ = compiled(s)
    row = {'id': 'r1', **s.raw}
    without = Gate().check(row)
    assert any(n['code'] == 'NO_POLICY_TABLE' for n in without['notes'])
    with_table = Gate(build_bundle(tables, key='')).check(row)
    assert with_table['verdict'] == 'VIOLATION' and with_table['label'] == 1
    assert any(v['code'] == 'POLICY_ATOM_VIOLATION' for v in with_table['violations'])


def test_gate_never_crashes_on_bad_row():
    r = Gate(unknown_label=1).check({'id': 'x', 'prompt': None, 'response': 'hi'})
    assert r['verdict'] == 'UNKNOWN' and r['label'] == 1 and 'error' in r


def test_score_and_cli(tmp_path):
    assert score([{'id': 'a', 'label': 1}, {'id': 'b', 'label': 0}], {'a': 1, 'b': 1})['f1'] == pytest.approx(0.6667)
    s = store()
    src = tmp_path / 'in.jsonl'
    src.write_text(json.dumps({'id': 'a', 'label': 1, **s.raw}, ensure_ascii=False) + '\n', encoding='utf-8')
    rc = main(['--input', str(src), '--output', str(tmp_path / 'p.csv'), '--metrics', str(tmp_path / 'm.json'),
               '--audit', str(tmp_path / 'a.jsonl')])
    assert rc == 0 and json.loads((tmp_path / 'm.json').read_text())['llm_calls'] == 0
    assert (tmp_path / 'p.csv').read_text().startswith('id,label')
