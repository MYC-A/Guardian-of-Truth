import json
import urllib.error
from guardian_truth.policy_table_v11.transport import Transport


class Reply:
    def __init__(self, tokens=7): self.tokens = tokens
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps({'choices': [{'message': {'content': '{"atoms":[],"empty_reason":"No applicable precondition."}'}}],
        'usage': {'total_tokens': self.tokens}}).encode()


def test_shared_budget_for_different_providers_and_secret_not_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv('OLLAMA_API_KEY', 'test-secret-value')
    monkeypatch.setenv('MISTRAL_API_KEY', 'test-secret-value')
    monkeypatch.setattr('urllib.request.urlopen', lambda *args, **kw: Reply())
    a = Transport(tmp_path, 'ollama', 'test', max_calls=1)
    b = Transport(tmp_path, 'mistral', 'test', max_calls=1)
    assert a([{'role': 'user', 'content': 'test'}])['status'] == 'OK'
    assert b([{'role': 'user', 'content': 'test'}])['status'] == 'BUDGET_STOP'
    assert b.snapshot()['http_attempts'] == 1
    assert not any('test-secret-value' in p.read_text() for p in tmp_path.rglob('*.json'))


def test_provider_quota_breaker_does_not_block_other_provider(tmp_path, monkeypatch):
    monkeypatch.setenv('OLLAMA_API_KEY', 'test-secret-value')
    monkeypatch.setenv('MISTRAL_API_KEY', 'test-secret-value')
    seen = []
    def call(req, **kwargs):
        seen.append(req.full_url)
        if 'ollama.com' in req.full_url: raise urllib.error.HTTPError(req.full_url, 429, 'quota', {}, None)
        return Reply()
    monkeypatch.setattr('urllib.request.urlopen', call)
    a, b = Transport(tmp_path, 'ollama', 'test'), Transport(tmp_path, 'mistral', 'test')
    assert a([{'role': 'user', 'content': 'first'}])['http_status'] == 429
    assert a([{'role': 'user', 'content': 'second'}])['status'] == 'PROVIDER_STOP'
    assert b([{'role': 'user', 'content': 'other'}])['status'] == 'OK'
    assert len(seen) == 2 and b.snapshot()['http_attempts'] == 2


def test_auth_stops_all_and_GET_counts_HTTP_not_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv('MISTRAL_API_KEY', 'test-secret-value')
    def call(req, **kwargs): raise urllib.error.HTTPError(req.full_url, 401, 'auth', {}, None)
    monkeypatch.setattr('urllib.request.urlopen', call)
    a = Transport(tmp_path, 'mistral', 'test')
    assert a.list_models()['http_status'] == 401
    assert a.snapshot()['http_attempts'] == 1 and a.snapshot()['unknown_upper_bound'] == 0
    assert a([{'role': 'user', 'content': 'test'}])['status'] == 'AUTH_STOP'
