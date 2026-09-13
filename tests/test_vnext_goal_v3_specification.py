"""Validate a preimplementation fixture specification, not model predictions."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / "benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json").read_text(encoding="utf-8"))


def test_case_ids_references_and_template_links_are_explicit():
    spec = fixture()
    cases, templates = spec["cases"], spec["event_templates"]
    assert len(cases) == len({case["id"] for case in cases}) == 36
    assert spec["scope"] == "CONTROLLED_PREIMPLEMENTATION_DEV_SPEC_NOT_BLIND"
    for event in templates.values():
        assert "extends" not in event or event["extends"] in templates
    for case in cases:
        assert case["reference"]["status"] in {"PROVED_ERROR", "PROVED_NO_ERROR", "UNRESOLVED", "INCONSISTENT"}
        assert set(case.get("obligations", [])) <= set(spec["obligation_templates"])
        for event in case.get("history", []):
            if isinstance(event, str):
                assert event in templates
            elif "extends" in event:
                assert event["extends"] in templates


def test_spec_distinguishes_optional_order_and_explicit_mandatory_order():
    cases = {case["id"]: case for case in fixture()["cases"]}
    assert cases["gav3:optional-cache-skipped"]["reference"]["status"] == "PROVED_NO_ERROR"
    assert cases["gav3:optional-cache-reordered"]["reference"]["status"] == "PROVED_NO_ERROR"
    assert cases["gav3:mandatory-order-skipped"]["reference"]["status"] == "PROVED_ERROR"


def test_unknown_guards_open_meanings_and_independent_witness_have_distinct_expectations():
    cases = {case["id"]: case for case in fixture()["cases"]}
    assert cases["gav3:independent-error-unrelated-unknown"]["reference"]["status"] == "PROVED_ERROR"
    for key in ("exception-unknown-blocks-witness", "open-no-permission-not-prohibited", "open-no-violation-not-safe"):
        assert cases["gav3:" + key]["reference"]["status"] == "UNRESOLVED"
    assert cases["gav3:guard-skipped-core-catches"]["reference"]["status"] == "PROVED_ERROR"
    assert cases["gav3:guard-skipped-partial"]["reference"]["status"] == "UNRESOLVED"


def test_partial_history_and_session_deadlines_are_not_guessed():
    cases = {case["id"]: case for case in fixture()["cases"]}
    assert cases["gav3:mandatory-verification-missing-full"]["reference"]["status"] == "PROVED_ERROR"
    assert cases["gav3:mandatory-verification-missing-partial"]["reference"]["status"] == "UNRESOLVED"
    assert cases["gav3:deadline-not-due"]["reference"]["obligation_status"] == "PENDING_NOT_VIOLATED"
    assert cases["gav3:deadline-due-missing"]["reference"]["status"] == "PROVED_ERROR"
