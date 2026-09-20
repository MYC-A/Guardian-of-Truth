from __future__ import annotations

import json

import pytest

from experiments.architectures_v2.b_theory.contracts import (CaseInput, TheoryCandidate,
                                                               Variant)
from experiments.architectures_v2.b_theory.orchestrator import run_case
from experiments.architectures_v2.b_theory.adapters import run_with_adapters
from experiments.architectures_v2.b_theory.run_b_theory import _candidate_map, parse_args, run


TEXT = "Verify identity before refund. Manager approval is required."


def _case():
    return CaseInput.parse({
        "case_id": "c1",
        "sources": [{"source_id": "policy:0", "document": "prompt", "text": TEXT}],
        "clauses": [
            {"clause_id": "cl0", "source_id": "policy:0", "start": 0, "end": 30,
             "quote": TEXT[:30]},
            {"clause_id": "cl1", "source_id": "policy:0", "start": 31, "end": len(TEXT),
             "quote": TEXT[31:]},
        ],
    })


def _wire(candidate_id="mistral:1", *, start=0, end=15, temporal="NONE",
          target_kind="ACTION"):
    return {
        "candidate_id": candidate_id,
        "rule": {
            "modality": "REQUIRE", "subject": "assistant",
            "target": {"kind": target_kind, "name": "Verify identity"},
            "relation": "NONE", "condition": None, "exception": None,
            "temporal": temporal, "values": [], "entity_references": [],
            "unresolved_references": [],
        },
        "source_spans": [{"segment_id": "policy:0", "start": start, "end": end,
                          "quote": TEXT[start:end]}],
        "source_segment_ids": ["policy:0"], "extractors": ["mistral:test"],
        "unresolved_components": [], "canonical_digest": "digest",
    }


def _candidate(provider="mistral", candidate_id="mistral-theory", *, wire=None,
               accounts=None, parent=None):
    wire = wire or _wire()
    return TheoryCandidate.parse({
        "candidate_id": candidate_id, "provider": provider,
        "parent_candidate_id": parent,
        "elements": [{"wire_candidate": wire}],
        "clause_accounts": accounts or [],
    })


def test_b0_accepts_donor_wire_but_does_not_admit_a_premise():
    result = run_case(_case(), [_candidate()], Variant.B0)
    element = result["candidates"][0]["elements"][0]
    assert element["grounding_status"] == "ANCHORED"
    assert element["ruleir_boundary"]["status"] == "BINDING_REQUIRED"
    assert result["formal_status"] == "UNRESOLVED"
    assert result["selection_policy"] == "ALTERNATIVES_RETAINED_NO_NAIVE_UNION"


def test_b1_rejects_bad_exact_offset():
    wire = _wire()
    wire["source_spans"][0]["quote"] = "wrong"
    candidate = _candidate(wire=wire)
    result = run_case(_case(), [candidate], Variant.B1)
    element = result["candidates"][0]["elements"][0]
    assert element["grounding_status"] == "UNANCHORED"
    assert element["ruleir_boundary"]["status"] == "REJECTED"
    assert "UNANCHORED_ELEMENT" in result["candidates"][0]["issues"]


def test_b2_never_turns_missing_clause_account_into_coverage():
    accounts = [{"clause_id": "cl0", "status": "accounted_for",
                 "element_ids": ["mistral:1"]}]
    result = run_case(_case(), [_candidate(accounts=accounts)], Variant.B2)
    ledger = result["candidates"][0]["clause_ledger"]
    assert ledger[0]["status"] == "accounted_for"
    assert ledger[1]["status"] == "unresolved"
    assert result["candidates"][0]["candidate_status"] == "UNRESOLVED"


def test_b2_non_policy_requires_reason():
    with pytest.raises(ValueError, match="requires a reason"):
        _candidate(accounts=[{"clause_id": "cl0", "status": "non_policy_with_reason"}])


def test_b3_preserves_parent_and_own_author_repair_as_alternatives():
    parent = _candidate()
    repair = _candidate("mistral", "mistral-repair", parent=parent.candidate_id,
                        wire=_wire("mistral:2"))
    result = run_case(_case(), [parent], Variant.B3, repairs=[repair])
    assert [row["candidate_id"] for row in result["candidates"]] == [
        "mistral-theory", "mistral-repair"]
    assert "B3_REPAIR_AUTHOR_MUST_MATCH_PARENT_AUTHOR" not in result["candidates"][1]["issues"]
    assert "B3_REPAIR_REQUIRES_PARENT" not in result["candidates"][0]["issues"]


def test_b3_rejects_repair_authored_by_other_provider():
    parent = _candidate()
    repair = _candidate("nuextract", "repair", parent=parent.candidate_id,
                        wire=_wire("nuextract:2"))
    result = run_case(_case(), [parent], Variant.B3, repairs=[repair])
    assert "B3_REPAIR_AUTHOR_MUST_MATCH_PARENT_AUTHOR" in result["candidates"][1]["issues"]


def test_fullarch_boundary_reports_temporal_anchor_loss():
    candidate = _candidate(wire=_wire(temporal="BEFORE"))
    result = run_case(_case(), [candidate], Variant.B1)
    boundary = result["candidates"][0]["elements"][0]["ruleir_boundary"]
    assert boundary["status"] == "UNREPRESENTABLE"
    assert "temporal-anchor" in boundary["reason"]


def test_unless_operand_in_donor_condition_becomes_exception_only():
    wire = _wire("nuextract:unless")
    wire["rule"]["modality"] = "FORBID"
    wire["rule"]["relation"] = "UNLESS"
    wire["rule"]["condition"] = {
        "operator": "ATOM", "term": {"kind": "STATE", "name": "Manager approval"}
    }
    boundary = run_case(_case(), [_candidate("nuextract", wire=wire)], Variant.B1)[
        "candidates"][0]["elements"][0]["ruleir_boundary"]
    assert boundary["status"] == "BINDING_REQUIRED"
    assert boundary["rule_ir"].get("conditions") is None
    assert len(boundary["rule_ir"]["exceptions"]) == 1


def test_segment_relative_span_is_rebased_for_fullarch():
    raw = {
        "case_id": "c-offset",
        "sources": [{"source_id": "policy:0", "document": "prompt", "text": TEXT,
                     "document_start": 100}],
        "clauses": [],
    }
    result = run_case(CaseInput.parse(raw), [_candidate()], Variant.B1)
    span = result["candidates"][0]["elements"][0]["ruleir_boundary"]["rule_ir"][
        "source_spans"][0]
    assert (span["start"], span["end"]) == (100, 115)


def test_cli_append_resume_and_fingerprint(tmp_path):
    case_path = tmp_path / "cases.jsonl"
    candidate_path = tmp_path / "mistral.jsonl"
    out = tmp_path / "out"
    raw_case = {
        "case_id": "c1", "sources": [{"source_id": "policy:0", "text": TEXT}],
        "clauses": [{"clause_id": "cl0", "source_id": "policy:0", "start": 0,
                     "end": len(TEXT), "quote": TEXT}],
    }
    raw_candidate = {
        "case_id": "c1", "candidates": [{"candidate_id": "t1", "provider": "mistral",
            "elements": [{"wire_candidate": _wire()}], "clause_accounts": []}],
    }
    case_path.write_text(json.dumps(raw_case) + "\n", encoding="utf-8")
    candidate_path.write_text(json.dumps(raw_candidate) + "\n", encoding="utf-8")
    args = parse_args(["--input", str(case_path), "--variant", Variant.B0.value,
                       "--provider-output", f"mistral={candidate_path}",
                       "--output-dir", str(out)])
    assert run(args) == 0
    first = (out / "records.jsonl").read_text(encoding="utf-8")
    assert run(args) == 0
    assert (out / "records.jsonl").read_text(encoding="utf-8") == first
    changed = parse_args(["--input", str(case_path), "--variant", Variant.B1.value,
                          "--provider-output", f"mistral={candidate_path}",
                          "--output-dir", str(out)])
    with pytest.raises(ValueError, match="fingerprint"):
        run(changed)


def test_model_execution_is_injectable_and_fake_only():
    candidate = _candidate()

    class FakeProvider:
        def extract(self, case):
            assert case.case_id == "c1"
            return [candidate]

    result = run_with_adapters(_case(), Variant.B0, providers=[FakeProvider()])
    assert result["providers"] == ["mistral"]


def test_combined_provider_output_is_deterministically_filtered_by_spec(tmp_path):
    combined = tmp_path / "combined.jsonl"
    candidates = []
    for provider in ("mistral", "nuextract", "gliner"):
        candidates.append({
            "candidate_id": f"{provider}:theory", "provider": provider,
            "elements": [{"wire_candidate": _wire(f"{provider}:element")}],
            "clause_accounts": [],
        })
    combined.write_text(json.dumps({
        "case_id": "c1", "candidates": candidates,
        "provider_runs": {provider: {"status": "EXECUTED"}
                          for provider in ("mistral", "nuextract", "gliner")},
    }) + "\n", encoding="utf-8")
    loaded, hashes = _candidate_map([
        f"mistral={combined}", f"nuextract={combined}", f"gliner={combined}"])
    assert [item.provider for item in loaded["c1"]] == [
        "mistral", "nuextract", "gliner"]
    assert set(hashes) == {"mistral", "nuextract", "gliner"}


def test_combined_provider_output_rejects_unknown_and_duplicate_specs(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"case_id": "c1", "candidates": [{
        "candidate_id": "x", "provider": "unknown-backend", "elements": []}]}) + "\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="unknown candidate provider"):
        _candidate_map([f"mistral={bad}"])
    with pytest.raises(ValueError, match="duplicate provider output spec"):
        _candidate_map([f"mistral={bad}", f"mistral={bad}"])
