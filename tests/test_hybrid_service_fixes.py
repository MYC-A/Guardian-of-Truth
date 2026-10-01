"""Regression tests for the Stage-A service and native checker adapters."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
sys.path.insert(0, str(ROOT / "experiments/searh_23/hybrid_service_v1"))

from runtime import GuardianServiceRuntime, _judge_findings, _judge_stage  # noqa: E402
from smoke_native_adapters import _acc, BANK  # noqa: E402
from factcg_native import INSTRUCTION_TEMPLATE  # noqa: E402
from modular_helpers import (advisory_for, evidence_subgraph,  # noqa: E402
                             policy_surface_graph)
from structural_v02 import parse_case_v02  # noqa: E402


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


@pytest.mark.parametrize("labels,expected,n_findings", [
    ((1, 1), "ERROR", 2),
    ((0, 0), "NO_ERROR", 0),
    ((1, 0, 1), "ERROR", 1),
    ((1, 0, 0), "NO_ERROR", 0),
    ((1, 0, None), "UNKNOWN", 0),
])
def test_judge_stage_routing_contract(monkeypatch, labels, expected, n_findings):
    positive = {"label": 1, "type": "UNSUPPORTED",
                "response_quote": "An invented amount", "policy_quote": "",
                "history_quote": "", "catalog_quote": "", "source_refs": [],
                "explanation": "No observation supports this amount."}
    negative = {"label": 0, "type": "NONE",
                "response_quote": "", "policy_quote": "", "history_quote": "",
                "catalog_quote": "", "source_refs": [],
                "explanation": "The target is supported."}
    pending = iter(labels)

    def ask_vote(model, ctx, **_):
        label = next(pending)
        return {"model": model, "valid": label is not None,
                "vote": positive if label == 1 else negative if label == 0
                else None, "attempts": [{"attempt": 1}],
                "usage": {"total_tokens": 10}}

    monkeypatch.setitem(sys.modules, "judge", types.SimpleNamespace(
        ask_vote=ask_vote))
    monkeypatch.setitem(sys.modules, "llm", types.SimpleNamespace(
        available=lambda: {}, chat=lambda *a, **kw: None))
    cfg = {"j1_model": "gemma", "j2_model": "mistral",
           "third_model": "gpt-oss"}
    ctx = types.SimpleNamespace(response_raw="An invented amount",
                                policy_text="", prompt_raw="", system="")
    decision, findings, usage, degraded, _ = _judge_stage(cfg, ctx)
    assert decision == expected
    assert len(findings) == n_findings
    assert usage["calls"] == len(labels)
    assert degraded is (expected == "UNKNOWN")
    if expected == "ERROR":
        assert all(f["checked"]["statement"] == "An invented amount"
                   for f in findings)


def test_ge_retains_positive_and_other_entity_observations():
    prompt = (
        "⟦SYSTEM⟧\nReport the latest account balance.\n"
        "[AVAILABLE TOOLS]\n- get_balance — reports balances.\n"
        "    account_id: string!\n"
        "⟦USER⟧\nPlease check A-77.\n"
        "⟦ASSISTANT⟧\n→ TOOL_CALL get_balance: {\"account_id\": \"A-77\"}\n"
        "← TOOL_RESPONSE get_balance: {\"account_id\": \"A-77\", \"balance\": 120.5}\n"
        "⟦ASSISTANT⟧\n→ TOOL_CALL get_balance: {\"account_id\": \"B-22\"}\n"
        "← TOOL_RESPONSE get_balance: {\"account_id\": \"B-22\", \"balance\": 999}\n"
    )
    response = "The balance of A-77 is 120.5."
    graph = evidence_subgraph(prompt, response)
    assert graph["status"] == "MECHANICAL_OBSERVATIONS_ONLY"
    assert graph["coverage"]["facts_total"] >= 4
    assert any(f["field"] == "balance" and f["value"] == 120.5
               for f in graph["facts"])
    assert any(f["field"] == "balance" and f["value"] == 999
               for f in graph["facts"])
    for fact in graph["facts"]:
        for source in fact["sources"]:
            assert source["document"] == "prompt"
            assert 0 <= source["start"] < source["end"] <= len(prompt)


def test_gp_surface_and_advisory_preserve_raw_context():
    prompt = ("⟦SYSTEM⟧\nBefore publish_record, check approval. "
              "You may read_record at any time.\n"
              "[AVAILABLE TOOLS]\n- publish_record — publishes.\n"
              "- read_record — reads.\n"
              "⟦USER⟧\nRead record R-1.\n")
    response = "→ TOOL_CALL read_record: {}"
    ctx = parse_case_v02("surface", prompt, response)
    gp = policy_surface_graph(ctx.policy_text, ctx.catalog.tools)
    assert gp["status"] == "SURFACE_ONLY"
    assert gp["coverage"]["semantic_complete"] is False
    assert all(node["quote"] in ctx.policy_text for node in gp["nodes"])
    ctx.advisory_context, coverage = advisory_for(ctx, "ge_gp")
    import judge
    user, trim = judge.build_judge_user(ctx, max_chars=12000)
    assert trim is None
    assert prompt in user and response in user
    assert "ADVISORY VIEW" in user and coverage["ge"] is not None
