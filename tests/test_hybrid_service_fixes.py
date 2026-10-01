"""Regression tests for the Stage-A service and native checker adapters."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
sys.path.insert(0, str(ROOT / "experiments/searh_23/hybrid_service_v1"))

from runtime import GuardianServiceRuntime, _judge_findings  # noqa: E402
from smoke_native_adapters import _acc, BANK  # noqa: E402
from factcg_native import INSTRUCTION_TEMPLATE  # noqa: E402


def test_judge_flat_vote_becomes_grounded_finding():
    vote = {"label": 1, "type": "CONTRADICTION",
            "response_quote": "I refunded ORD-1",
            "policy_quote": "Approval is required before a refund",
            "history_quote": "No approval was recorded",
            "catalog_quote": "", "source_refs": ["r1", "c2"],
            "explanation": "A refund was claimed without approval."}
    finding, = _judge_findings([{"valid": True, "vote": vote,
                                 "model": "test-model"}])
    assert finding["type"] == "CONTRADICTION"
    assert finding["checked"]["statement"] == vote["response_quote"]
    assert finding["quotes"] == [
        {"source": "response", "text": vote["response_quote"]},
        {"source": "policy", "text": vote["policy_quote"]},
        {"source": "history", "text": vote["history_quote"]},
    ]
    assert finding["binding"]["source_refs"] == ["r1", "c2"]
    assert finding["status"] == "JUDGED"


def test_judge_unsupported_and_zero_votes():
    vote = {"label": 1, "type": "UNSUPPORTED",
            "response_quote": "The balance is 500", "policy_quote": "",
            "history_quote": "", "catalog_quote": "", "source_refs": [],
            "explanation": "The amount has no source."}
    out = _judge_findings([{"valid": True, "vote": vote, "model": "judge"},
                           {"valid": True, "vote": {"label": 0}},
                           {"valid": False, "vote": vote}])
    assert len(out) == 1
    assert out[0]["quotes"] == [{"source": "response",
                                  "text": "The balance is 500"}]


def test_acc_preserves_indices_after_invalid_prediction():
    preds = [e for _, _, e in BANK]
    preds[0] = None
    result = _acc(preds)
    assert result["format_success"] == f"{len(BANK)-1}/{len(BANK)}"
    assert result["smoke_acc_on_valid"] == 1.0
    assert result["smoke_acc_invalid_as_wrong"] == round(
        (len(BANK)-1) / len(BANK), 3)


def test_factcg_uses_author_instruction_string():
    assert INSTRUCTION_TEMPLATE.format(text_a="Document.", text_b="Claim") == (
        'Document.\n\nChoose your answer: based on the paragraph above '
        'can we conclude that "Claim"?\n\nOPTIONS:\n- Yes\n- No\n'
        'I think the answer is ')


def test_readiness_probe_is_cached_and_has_no_inference(monkeypatch):
    runtime = GuardianServiceRuntime("structural-v02")
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.get_method(), timeout))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert runtime._probe_backend("example", "https://example.org/v1", "secret") == (
        True, "http_200")
    assert runtime._probe_backend("example", "https://example.org/v1", "secret") == (
        True, "http_200")
    assert calls == [("https://example.org/v1/models", "GET", 4)]
