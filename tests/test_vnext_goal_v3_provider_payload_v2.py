"""Verify proposed v2 Groq wire shape offline with an injected transport."""

import json

from guardian_truth.llm_client import ChatClient, ClientConfig, HTTPResponse
from guardian_truth.runtime import provider_config


def test_groq_qwen_payload_is_json_mode_and_completion_capped(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-dummy-key")
    captured = []

    def transport(request, timeout):
        captured.append((request.full_url, json.loads(request.data), timeout))
        body = {"choices": [{"finish_reason": "stop",
            "message": {"content": '{"alignment":"UNKNOWN"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "qwen/qwen3.8-27b"}
        return HTTPResponse(200, json.dumps(body).encode("utf-8"))

    config = provider_config(ClientConfig(max_output_tokens=512, max_retries=0,
        response_format_mode="auto"), "groq", model="qwen/qwen3.8-27b")
    completion = ChatClient(config, transport=transport).complete(
        [{"role": "user", "content": "Return one compact JSON object."}], schema=None)
    assert completion.usage["total_tokens"] == 15
    assert len(captured) == 1
    url, payload, timeout = captured[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert payload["model"] == "qwen/qwen3.8-27b"
    assert payload["max_completion_tokens"] == 512 and "max_tokens" not in payload
    assert payload["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in payload
    assert timeout == config.timeout_seconds
