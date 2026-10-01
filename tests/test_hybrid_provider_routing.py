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
