import os
from unittest.mock import patch

import pytest

from guardian_truth.vnext.e2e.backend_v1 import (E2ECachingBackend, LiveBackendBlocked,
                                                  build_live_backend)
from guardian_truth.vnext.e2e.competition_adapter_v1 import adapt_competition_input
from guardian_truth.vnext.e2e.real_valid_v1 import (case_outcome, competition_view,
                                                     premise_rows, score)
from guardian_truth.vnext.semantic import Proposal


AUDIT_PROMPT = """⟦SYSTEM⟧
<policy>Do not alter records.</policy>
[AVAILABLE TOOLS]
- inspect_record — Read a record.
    record_id: string! — Record identifier.
⟦USER⟧
Inspect R-7.
⟦ASSISTANT_TOOL_CALL name="inspect_record"⟧
{"record_id":"R-7"}
⟦TOOL_RESULT name="inspect_record" requestor="assistant"⟧
{"record_id":"R-7","status":"present"}
⟦USER⟧
Describe R-7.""".strip()
AUDIT_RESPONSE = "⟦ASSISTANT⟧\nR-7 is present."


def test_gold_firewall_ignores_label_explanation_and_domain():
    base = {"id": "x", "prompt": "p", "response": "r", "label": 0,
            "explanation": "gold", "domain": "airline"}
    changed = {**base, "label": 1, "explanation": "different", "domain": "retail"}
    assert competition_view(base) == competition_view(changed) == {
        "id": "x", "prompt": "p", "response": "r"}


def test_binary_scoring_keeps_internal_status_metrics():
    rows = [
        {"id": "a", "label": 1, "core_status": "PROVED_ERROR", "certificate_valid": True},
        {"id": "b", "label": 0, "core_status": "UNRESOLVED", "certificate_valid": None},
    ]
    result = score(rows, {"a": 1, "b": 1})
    assert (result["TP"], result["FN"]) == (1, 1)
    assert result["statuses"]["PROVED_ERROR"] == 1
    assert result["statuses"]["UNRESOLVED"] == 1
    assert case_outcome(1, 1) == "TP"
    assert case_outcome(1, 0) == "FP"
    assert case_outcome(0, 1) == "FN"
    assert case_outcome(0, 0) == "TN"


def test_premise_inventory_separates_explicit_schema_from_untrusted_semantics():
    adapted = adapt_competition_input({"id": "x", "prompt": AUDIT_PROMPT,
                                       "response": AUDIT_RESPONSE})
    rows = premise_rows(adapted)
    schema = [row for row in rows if row["premise"] == "argument_existence"]
    effects = [row for row in rows if row["premise"] == "effect_guarantee"]
    assert schema and all(row["origin"] == "EXPLICIT_SCHEMA" and row["trusted"] for row in schema)
    assert effects and all(row["origin"] == "AMBIGUOUS" and not row["trusted"] for row in effects)
    assert all(row["derivation"] != "tool_name_inference" for row in rows)


def test_live_backend_can_bind_groq_model_and_credential_name():
    with patch.dict(os.environ, {"GROQ_API_KEY": "synthetic-groq-key"}, clear=True):
        backend = build_live_backend(provider="groq", model="qwen/qwen3.8-27b",
                                     api_key_env="GROQ_API_KEY", interval_seconds=0,
                                     max_output_tokens=1024, reasoning_effort=None)
    config = backend.inner.client.config
    assert config.base_url == "https://api.groq.com/openai/v1"
    assert config.model == "qwen/qwen3.8-27b"
    assert config.api_key_env == "GROQ_API_KEY"
    assert config.max_output_tokens == 1024
    assert backend.inner.reasoning_effort is None


def test_rate_limit_fail_fast_does_not_poison_semantic_cache():
    class Limited:
        def propose(self, task, payload, schema):
            return Proposal(None, "ERROR", "NOT_EVALUATED", "rate_limit")

    backend = E2ECachingBackend(Limited(), fail_fast_error_categories=("rate_limit",))
    with pytest.raises(LiveBackendBlocked, match="rate_limit"):
        backend.propose("task", {"x": 1}, {"type": "object"})
    assert backend.cache == {}
