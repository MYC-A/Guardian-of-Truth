"""Explicit provider/model must retain a successful response during logging."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "experiments/searh_23/three_architectures"))
import llm


def test_unregistered_model_provider_survives_completion_and_cost_log(monkeypatch):
    request, costs = [], []

    def create(**kw):
        request.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"ok":true}'))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4, total_tokens=16))

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(llm._clients, "ollama", client)
    monkeypatch.setattr(llm, "_cache_get", lambda _: (None, False))
    monkeypatch.setattr(llm, "_cache_put", lambda *args: None)
    monkeypatch.setattr(llm, "_log_cost", costs.append)
    result = llm.chat("ollama/new-code-model", [{"role": "user", "content": "JSON"}],
                      transport_retries=0)
    assert result["content"] == '{"ok":true}'
    assert result["usage"]["total_tokens"] == 16
    assert request[0]["model"] == "new-code-model"
    assert costs[0]["provider"] == llm.PROVIDERS["ollama"][0]
    assert "error" not in result


def test_bounded_transport_attempts_are_recorded(monkeypatch):
    calls, costs, sleeps = [], [], []

    class RateLimit(Exception):
        status_code = 429

    def create(**kw):
        calls.append(kw)
        raise RateLimit("controlled failure")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(llm._clients, "ollama", client)
    monkeypatch.setattr(llm, "_cache_get", lambda _: (None, False))
    monkeypatch.setattr(llm, "_log_cost", costs.append)
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    result = llm.chat("ollama/controlled", [], transport_retries=1)
    assert len(calls) == result["transport_attempts"] == 2
    assert result["content"] is None and result["http_status"] == 429
    assert sleeps == [2]  # no sleep after exhausting the budget
    assert [c["transport_attempt"] for c in costs if "transport_attempt" in c] == [1, 2]


def test_sdk_retries_disabled(monkeypatch):
    construction = []
    monkeypatch.delitem(llm._clients, "ollama", raising=False)
    monkeypatch.setattr(llm, "OpenAI", lambda **kw: construction.append(kw) or object())
    llm._client("ollama/controlled")
    assert construction[0]["max_retries"] == 0
