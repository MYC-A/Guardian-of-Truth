from __future__ import annotations

import json
from dataclasses import replace

from experiments.architectures_v2.b_theory.b3_cycle import run_b3_cycle
from experiments.architectures_v2.b_theory.contracts import (
    CaseInput, TheoryCandidate, TheoryCritique)
from experiments.architectures_v2.b_theory.langextract_grounder import MistralLangExtractGrounder
from experiments.architectures_v2.b_theory.run_b3_cycle import parse_args, run


TEXT = "Verify identity before refund."


def _case(case_id="c1"):
    return CaseInput.parse({"case_id": case_id,
        "sources": [{"source_id": "policy:0", "text": TEXT}], "clauses": []})


def _theory(provider, candidate_id, interpretation="verify identity", parent=None):
    return TheoryCandidate.parse({
        "candidate_id": candidate_id, "provider": provider,
        "parent_candidate_id": parent,
        "elements": [{"element_id": "e1", "interpretation": interpretation,
                      "source_links": [{"source_id": "policy:0", "start": 0,
                                        "end": len(TEXT), "quote": TEXT}],
                      "rule_ir": None}], "clause_accounts": []})


def _critique(reviewer, target, critique_id):
    return TheoryCritique.parse({
        "critique_id": critique_id, "reviewer_provider": reviewer,
        "target_candidate_id": target,
        "issues": [{"issue_id": critique_id + ":1", "target_element_id": "e1",
                    "problem_type": "missing_condition",
                    "source_link": {"source_id": "policy:0", "start": 0,
                                    "end": len(TEXT), "quote": TEXT},
                    "explanation": "The before-refund condition must remain explicit."}],
        "unresolved": ["whether identity method is specified"]})


def test_bidirectional_cycle_keeps_originals_and_own_repairs_with_diff():
    m = _theory("mistral", "m")
    n = _theory("nuextract", "n")
    mr = _theory("mistral", "mr", "verify identity before refund", "m")
    nr = _theory("nuextract", "nr", "verify identity before refund", "n")
    result = run_b3_cycle(_case(), [m, n],
                          [_critique("nuextract", "m", "n-to-m"),
                           _critique("mistral", "n", "m-to-n")], [mr, nr])
    assert result["cycle_status"] == "READY_FOR_FORMAL_HANDOFF"
    assert [item["alternative_kind"] for item in result["candidates"]] == [
        "ORIGINAL", "ORIGINAL", "REPAIR", "REPAIR"]
    assert all(item["status"] == "PRESERVATION_CHECK_PASSED"
               for item in result["repair_diffs"])
    assert result["preservation_policy"] == \
        "ORIGINALS_IMMUTABLE_NO_DELETION_NO_AUTOMATIC_MERGE"


def test_repair_cannot_delete_parent_element_or_use_other_author():
    m, n = _theory("mistral", "m"), _theory("nuextract", "n")
    bad = TheoryCandidate.parse({"candidate_id": "bad", "provider": "nuextract",
                                 "parent_candidate_id": "m", "elements": []})
    nr = _theory("nuextract", "nr", parent="n")
    result = run_b3_cycle(_case(), [m, n],
                          [_critique("nuextract", "m", "n-to-m"),
                           _critique("mistral", "n", "m-to-n")], [bad, nr])
    diff = result["repair_diffs"][0]
    assert "REPAIR_REMOVED_PARENT_ELEMENT" in diff["invariant_violations"]
    assert "REPAIR_AUTHOR_MUST_MATCH_PARENT_AUTHOR" in diff["invariant_violations"]
    assert result["cycle_status"] == "UNRESOLVED"


def test_critique_requires_exact_original_fragment_and_offset():
    m, n = _theory("mistral", "m"), _theory("nuextract", "n")
    bad_wire = {"critique_id": "bad", "reviewer_provider": "nuextract",
                "target_candidate_id": "m", "issues": [{
                    "issue_id": "bad:1", "target_element_id": "e1",
                    "problem_type": "wrong_scope",
                    "source_link": {"source_id": "policy:0", "start": 1,
                                    "end": len(TEXT), "quote": TEXT},
                    "explanation": "scope mismatch"}]}
    mr, nr = _theory("mistral", "mr", parent="m"), _theory("nuextract", "nr", parent="n")
    result = run_b3_cycle(_case(), [m, n], [TheoryCritique.parse(bad_wire),
                          _critique("mistral", "n", "good")], [mr, nr])
    assert result["critiques"][0]["status"] == "UNRESOLVED"
    assert "bad:1:QUOTE_OFFSET_MISMATCH" in result["critiques"][0]["validation_issues"]
    assert "REPAIR_LACKS_VALID_GROUNDED_CROSS_CRITIQUE" in \
        result["repair_diffs"][0]["invariant_violations"]


def test_direct_langextract_is_gap_evidence_with_mistral_dependency(monkeypatch):
    monkeypatch.setenv("TEST_MISTRAL_KEY", "secret")
    grounder = MistralLangExtractGrounder(
        api_key_env="TEST_MISTRAL_KEY", model_factory=lambda **kwargs: object(),
        extract_fn=lambda **kwargs: {"extractions": [{
            "extraction_text": TEXT, "char_interval": {
                "start_pos": 0, "end_pos": len(TEXT)}}]})
    evidence = grounder.extract_original(_case())
    assert evidence[0]["quote_validity"] == "EXACT"
    assert evidence[0]["interpretation"] == "UNVERIFIED_MODEL_PROPOSAL"
    assert evidence[0]["relation_correctness"] == "UNVERIFIED"
    assert evidence[0]["dependency"]["marker"] == \
        "LANGEXTRACT_DEPENDS_ON_MISTRAL_BACKEND"


def test_three_case_runner_is_resumable_and_preserves_raw_artifacts(tmp_path):
    cases, m_rows, n_rows, mr_rows, nr_rows, critique_rows = [], [], [], [], [], []
    for index in range(3):
        case_id = f"c{index}"
        cases.append({"case_id": case_id,
                      "sources": [{"source_id": "policy:0", "text": TEXT}],
                      "clauses": []})
        m, n = _theory("mistral", f"m{index}"), _theory("nuextract", f"n{index}")
        mr = _theory("mistral", f"mr{index}", "verify identity before refund", f"m{index}")
        nr = _theory("nuextract", f"nr{index}", "verify identity before refund", f"n{index}")
        m_rows.append({"case_id": case_id, "candidates": [_wire(m)],
                       "raw_responses": [{"completion_content": "raw-m"}]})
        n_rows.append({"case_id": case_id, "candidates": [_wire(n)],
                       "raw_responses": [{"decoded_text": "raw-n"}]})
        mr_rows.append({"case_id": case_id, "candidates": [_wire(mr)],
                        "raw_responses": [{"completion_content": "raw-mr"}]})
        nr_rows.append({"case_id": case_id, "candidates": [_wire(nr)],
                        "raw_responses": [{"decoded_text": "raw-nr"}]})
        critique_rows.append({"case_id": case_id, "critiques": [
            _critique("nuextract", f"m{index}", f"n-m-{index}").__dict__ | {
                "issues": [_issue_wire(_critique("nuextract", f"m{index}", f"n-m-{index}"))]},
            _critique("mistral", f"n{index}", f"m-n-{index}").__dict__ | {
                "issues": [_issue_wire(_critique("mistral", f"n{index}", f"m-n-{index}"))]},
        ], "raw_response": {"content": "raw critique"}})
    paths = {}
    for name, rows in (("cases", cases), ("m", m_rows), ("n", n_rows),
                       ("mr", mr_rows), ("nr", nr_rows), ("cr", critique_rows)):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row, default=lambda value: value.value) + "\n"
                                for row in rows), encoding="utf-8")
        paths[name] = path
    args = parse_args(["--input", str(paths["cases"]),
        "--original-output", f"mistral={paths['m']}",
        "--original-output", f"nuextract={paths['n']}",
        "--critique-output", str(paths["cr"]),
        "--repair-output", f"mistral={paths['mr']}",
        "--repair-output", f"nuextract={paths['nr']}",
        "--output-dir", str(tmp_path / "out")])
    assert run(args) == 0
    first = (tmp_path / "out" / "records.jsonl").read_text(encoding="utf-8")
    assert run(args) == 0
    assert (tmp_path / "out" / "records.jsonl").read_text(encoding="utf-8") == first
    assert len(json.loads(first.splitlines()[0])["raw_artifacts"]) == 5


def _wire(candidate):
    return {"candidate_id": candidate.candidate_id, "provider": candidate.provider,
            "parent_candidate_id": candidate.parent_candidate_id,
            "elements": [{"element_id": item.element_id,
                          "interpretation": item.interpretation,
                          "source_links": [link.__dict__ for link in item.source_links],
                          "rule_ir": item.rule_ir} for item in candidate.elements],
            "clause_accounts": []}


def _issue_wire(critique):
    item = critique.issues[0]
    return {"issue_id": item.issue_id, "target_element_id": item.target_element_id,
            "problem_type": item.problem_type.value, "source_link": item.source_link.__dict__,
            "explanation": item.explanation}
