import json
from types import SimpleNamespace

import pytest

from experiments.guardian_local_a100 import lynx_native_v2 as lynx
from experiments.guardian_local_a100.first_circle_qa import combined


def test_coverage_is_counted_once_and_optional_extra_pass_is_not_another_row():
    parts = {s: dict(rows=n, n_verdict=n-1, n_fallback=1, n_extra_pass=2)
             for s, n in [('dev', 10), ('contrast', 14), ('valid46', 46)]}
    out = combined(parts)
    assert out['rows'] == 70 and out['valid_solution_coverage'] == 1 and out['all_sets_present']
    assert combined({'valid46': parts['valid46']})['valid_solution_coverage'] == 46/70
    assert not combined({'valid46': parts['valid46']})['all_sets_present']


@pytest.mark.parametrize('value', ['PASS', '{"SCORE":"PASS"}', '{"SCORE":"FAIL","REASONING":1}',
                                  '{"SCORE":"FAIL","SCORE":"PASS","REASONING":[]}',
                                  '{"SCORE":"PASS","REASONING":[],"extra":1}'])
def test_native_contract_rejects_incomplete_or_ambiguous_output(value):
    assert lynx.parse(value) is None


def test_native_contract_and_prompt_do_not_require_first_token_pass_fail():
    value = {'REASONING': ['The number agrees.'], 'SCORE': 'PASS'}
    assert lynx.parse(json.dumps(value)) == value
    assert lynx.parse('```json\n' + json.dumps(value) + '\n```') == value
    text = lynx.messages('DOC', 'QUESTION', 'ANSWER')[0]['content']
    assert 'QUESTION (THIS DOES NOT COUNT AS BACKGROUND INFORMATION):\nQUESTION' in text
    assert '\nDOCUMENT:\nDOC' in text and '\nANSWER:\nANSWER' in text


def test_receipt_failure_never_becomes_pass_and_context_never_truncates(tmp_path, monkeypatch):
    monkeypatch.setattr(lynx, 'prompt_tokens', lambda endpoint, request: 7000)
    calls = []
    client = SimpleNamespace(live=SimpleNamespace(endpoint='test'), call=lambda *args, **kwargs: calls.append(args))
    req = dict(model='local-test', max_tokens=1024, messages=lynx.messages('document', 'q', 'a'))
    assert lynx.execute(client, req, tmp_path, 8000)['status'] == 'CONTEXT_NOT_FIT'
    assert calls == [] and json.loads(next((tmp_path/'packets').glob('*.json')).read_text()) == req
    monkeypatch.setattr(lynx, 'prompt_tokens', lambda endpoint, request: 100)
    client.call = lambda *args, **kwargs: dict(transport={'status': 429}, finish_reason='stop',
                                             content='{"REASONING":[],"SCORE":"PASS"}')
    assert lynx.execute(client, req, tmp_path, 8000)['verdict'] is None


def test_accusations_keep_am_and_b2_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(lynx, 'ROOT', tmp_path)
    root = tmp_path / 'reviewer'
    (root / 'dev').mkdir(parents=True)
    (root/'dev/AM_rep1.jsonl').write_text(json.dumps({'id':'one', 'accusation_rfix':{'text':'AM reason'}}))
    (root/'dev/B2_rep1.jsonl').write_text(json.dumps({'id':'one', 'accusation':{'text':'B2 reason'}}))
    result = lynx.saved_accusations(root, 'dev', ['one'], ['A', 'B2'])
    assert [(r['arm'], r['text']) for r in result['one']] == [('A','AM reason'), ('B2','B2 reason')]


def test_explicit_partial_accusations_preserve_missing_reviewer_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(lynx, 'ROOT', tmp_path)
    root = tmp_path / 'reviewer'
    (root / 'dev').mkdir(parents=True)
    (root / 'dev/B2_rep1.jsonl').write_text('')
    with pytest.raises(ValueError, match='INCOMPLETE_ACCUSATION_INPUTS'):
        lynx.saved_accusations(root, 'dev', ['one'], ['B2'])
    result = lynx.saved_accusations(root, 'dev', ['one'], ['B2'], allow_partial=True)
    assert result['one'] == [dict(arm='B2', text=None, status='REVIEWER_ROW_NOT_EXECUTED')]
