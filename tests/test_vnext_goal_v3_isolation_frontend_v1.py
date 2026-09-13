"""One-call Goal-only proposal schema and non-authoritative grounding boundary."""

import json
from pathlib import Path

from guardian_truth.vnext.goal_v3_isolation_frontend_v1 import (
    SCHEMA, SCHEMA_SHA256, PROMPT_SHA256, SYSTEM_PROMPT, ground_candidate, prompt_messages,
)
from guardian_truth.vnext.integrity import digest


ROOT = Path(__file__).resolve().parents[1]
INPUTS = json.loads((ROOT / "outputs/vnext/goal_v3_isolation_v1_inputs.json").read_text(encoding="utf-8"))


def source(case_id):
    return next(row["source"] for row in INPUTS if row["case_id"] == case_id)


def candidate(**changes):
    value = {"alignment": "DIRECT_GOAL", "goal_entity": "SH-804",
        "obligation_status": "NOT_APPLICABLE", "temporal_status": "CURRENT_STEP",
        "violation_kind": "NONE", "evidence_actor": "assistant",
        "effect_status": "NOT_ESTABLISHED", "unknowns": [], "evidence_ids": ["user:0", "target:0"]}
    value.update(changes)
    return value


def test_prompt_and_schema_are_stable_compact_and_gold_policy_free():
    assert digest(SCHEMA) == SCHEMA_SHA256 and digest(SYSTEM_PROMPT) == PROMPT_SHA256
    assert "explanation" not in SCHEMA["properties"] and "reasoning" not in SCHEMA["properties"]
    for row in INPUTS:
        messages = prompt_messages(row["source"])
        assert len(messages) == 2 and messages[0]["content"] == SYSTEM_PROMPT
        assert "expected_status" not in messages[1]["content"]
        assert '"policy":' not in messages[1]["content"]
        assert row["case_id"] not in messages[1]["content"]


def test_valid_semantic_candidate_is_not_mistaken_for_a_certificate():
    checked = ground_candidate(source("P01:a"), candidate())
    assert checked.valid_schema and checked.source_ids_valid and checked.entity_grounded
    assert checked.candidate_status == "PROVED_NO_ERROR"
    assert checked.scope == "MODEL_SEMANTIC_CANDIDATE_NOT_CERTIFIED_GOAL_OR_CORE_VERDICT"


def test_unbound_evidence_entity_or_actor_stays_unresolved():
    assert ground_candidate(source("P01:a"), candidate(evidence_ids=["fake"])).candidate_status == "UNRESOLVED"
    assert ground_candidate(source("P01:a"), candidate(goal_entity="SH-905")).candidate_status == "UNRESOLVED"
    assert ground_candidate(source("P01:a"), candidate(evidence_actor="tool")).candidate_status == "UNRESOLVED"


def test_out_of_scope_without_violation_kind_is_not_a_proved_error():
    assert ground_candidate(source("P01:a"), candidate(alignment="PROVED_OUT_OF_SCOPE")).candidate_status == "UNRESOLVED"
    assert ground_candidate(source("P01:a"), candidate(alignment="PROVED_OUT_OF_SCOPE",
        violation_kind="SCOPE")).candidate_status == "PROVED_ERROR"


def test_confirmed_effect_requires_cited_source_t1_success():
    valid = source("P16:a")
    checked = ground_candidate(valid, candidate(effect_status="CONFIRMED",
        evidence_ids=["user:0", "target:0", "event:0"]))
    assert checked.effect_grounded
    failed = source("P16:b")
    denied = ground_candidate(failed, candidate(effect_status="CONFIRMED",
        evidence_ids=["user:0", "target:0", "event:0"]))
    assert not denied.effect_grounded and denied.candidate_status == "UNRESOLVED"
