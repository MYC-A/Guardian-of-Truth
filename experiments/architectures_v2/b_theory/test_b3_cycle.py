from __future__ import annotations

import json
from dataclasses import replace

from experiments.architectures_v2.b_theory.b3_cycle import run_b3_cycle
from experiments.architectures_v2.b_theory.contracts import (
    CaseInput, TheoryCandidate, TheoryCritique)
from experiments.architectures_v2.b_theory.langextract_grounder import MistralLangExtractGrounder
from experiments.architectures_v2.b_theory.run_b3_cycle import parse_args, run
from experiments.architectures_v2.b_theory.mutual_model_runner import (
    ModelResult, _build_repair, _critique as parse_model_critique,
    generate_case, parse_args as model_parse_args,
    run_cli as run_model_cli)


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
    calls = []

    def extract_fn(**kwargs):
        calls.append(kwargs)
        return {"extractions": [{
            "extraction_text": TEXT, "char_interval": {
                "start_pos": 0, "end_pos": len(TEXT)}}]}

    grounder = MistralLangExtractGrounder(
        api_key_env="TEST_MISTRAL_KEY", model_factory=lambda **kwargs: object(),
        extract_fn=extract_fn, example_factory=lambda: "neutral-example")
    evidence = grounder.extract_original(_case())
    assert len(calls) == 1
    assert calls[0]["examples"] == ["neutral-example"]
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


class _FakeReviewBackend:
    dependency = "FAKE_TEST_ONLY"

    def __init__(self, provider, fail_critique=False):
        self.provider, self.model_id = provider, f"fake-{provider}"
        self.fail_critique = fail_critique

    def critique(self, case, target):
        if self.fail_critique:
            return ModelResult(None, None, "unsupported template")
        parsed = {"issues": [{"target_element_id": "e1",
                              "problem_type": "missing_condition",
                              "source_id": "policy:0", "start": 0, "end": len(TEXT),
                              "quote": TEXT, "explanation": "condition omitted"}],
                  "unresolved": []}
        return ModelResult(parsed, {"model_text": json.dumps(parsed)})

    def repair(self, case, parent, critique):
        parsed = {"changes": [{"element_id": "e1",
            "interpretation": "verify identity before refund",
            "source_links": [{"source_id": "policy:0", "start": 0,
                              "end": len(TEXT), "quote": TEXT}],
            "rule_ir": None, "unresolved_components": []}],
            "additions": [{"element_id": f"{self.provider}:added",
                "interpretation": "explicit refund scope",
                "source_links": [{"source_id": "policy:0", "start": 0,
                                  "end": len(TEXT), "quote": TEXT}],
                "rule_ir": None, "unresolved_components": []}], "unresolved": []}
        return ModelResult(parsed, {"model_text": json.dumps(parsed)})


def test_model_cycle_generates_both_directions_and_constrained_repairs():
    result = generate_case(_case(), [_theory("mistral", "m"),
                           _theory("nuextract", "n")],
                           mistral=_FakeReviewBackend("mistral"),
                           nuextract=_FakeReviewBackend("nuextract"))
    assert result["cycle_generation_status"] == "BIDIRECTIONAL_COMPLETE"
    assert len(result["critiques"]) == len(result["repairs"]) == 2
    assert all(build["changed_element_ids"] == ["e1"] for build in result["repair_builds"])
    assert all(not build["added_elements"] for build in result["repair_builds"])
    assert all(any(item.startswith("INVALID_OR_UNGROUNDED_ADDITION")
                   for item in build["rejected_operations"])
               for build in result["repair_builds"])
    assert all(repair.elements[0].element_id == "e1" for repair in result["repairs"])


def test_capability_failure_stays_one_sided_without_fake_repair():
    result = generate_case(_case(), [_theory("mistral", "m"),
                           _theory("nuextract", "n")],
                           mistral=_FakeReviewBackend("mistral"),
                           nuextract=_FakeReviewBackend("nuextract", fail_critique=True))
    assert result["cycle_generation_status"] == "ONE_SIDED_OR_UNRESOLVED"
    assert {item.provider for item in result["repairs"]} == {"nuextract"}
    assert any(item["reason"] == "NO_VALID_CROSS_PROVIDER_CRITIQUE"
               for item in result["capability_failures"])
    failed = [item for item in result["model_runs"]
              if item["provider"] == "nuextract" and item["operation"] == "CRITIQUE"]
    assert failed[0]["status"] == "CAPABILITY_FAILURE"
    assert failed[0]["raw_response"] is None


def test_model_runner_resumes_and_writes_consumer_files(tmp_path):
    cases, m_rows, n_rows = [], [], []
    for index in range(3):
        case_id = f"mc{index}"
        cases.append({"case_id": case_id,
                      "sources": [{"source_id": "policy:0", "text": TEXT}], "clauses": []})
        m_rows.append({"case_id": case_id,
                       "candidates": [_wire(_theory("mistral", f"m{index}"))]})
        n_rows.append({"case_id": case_id,
                       "candidates": [_wire(_theory("nuextract", f"n{index}"))]})
    paths = {}
    for name, rows in (("cases", cases), ("m", m_rows), ("n", n_rows)):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        paths[name] = path
    args = model_parse_args(["--input", str(paths["cases"]),
        "--original-output", f"mistral={paths['m']}",
        "--original-output", f"nuextract={paths['n']}",
        "--output-dir", str(tmp_path / "model")])
    kwargs = {"mistral": _FakeReviewBackend("mistral"),
              "nuextract": _FakeReviewBackend("nuextract")}
    assert run_model_cli(args, **kwargs) == 0
    first = (tmp_path / "model" / "model_cycle.jsonl").read_text(encoding="utf-8")
    assert run_model_cli(args, **kwargs) == 0
    assert (tmp_path / "model" / "model_cycle.jsonl").read_text(encoding="utf-8") == first
    assert (tmp_path / "model" / "critiques.jsonl").exists()
    assert (tmp_path / "model" / "mistral_repairs.jsonl").exists()
    assert (tmp_path / "model" / "nuextract_repairs.jsonl").exists()


class _NoIssuesBackend(_FakeReviewBackend):
    def critique(self, case, target):
        return ModelResult({"issues": [], "unresolved": []},
                           {"model_text": '{"issues":[]}'})

    def repair(self, case, parent, critique):
        raise AssertionError("empty valid critique must not trigger repair")


def test_empty_bidirectional_critiques_are_success_and_skip_repairs():
    result = generate_case(_case(), [_theory("mistral", "m"),
                           _theory("nuextract", "n")],
                           mistral=_NoIssuesBackend("mistral"),
                           nuextract=_NoIssuesBackend("nuextract"))
    assert result["cycle_generation_status"] == "BIDIRECTIONAL_COMPLETE"
    assert len(result["critiques"]) == 2
    assert result["repairs"] == []
    repair_runs = [item for item in result["model_runs"] if item["operation"] == "REPAIR"]
    assert all(item["status"] == "SKIPPED_NOT_NEEDED" for item in repair_runs)

    empty_reviews = [TheoryCritique.parse({"critique_id": "n-m",
                     "reviewer_provider": "nuextract", "target_candidate_id": "m",
                     "issues": []}), TheoryCritique.parse({"critique_id": "m-n",
                     "reviewer_provider": "mistral", "target_candidate_id": "n",
                     "issues": []})]
    validated = run_b3_cycle(_case(), [_theory("mistral", "m"),
                             _theory("nuextract", "n")], empty_reviews, [])
    assert validated["cycle_status"] == "READY_FOR_FORMAL_HANDOFF"
    assert all(item["outcome"] == "NO_ISSUES_FOUND" for item in validated["critiques"])


class _WrongOffsetsBackend(_FakeReviewBackend):
    def critique(self, case, target):
        parsed = {"issues": [{"target_element_id": "e1",
                              "problem_type": "wrong_scope", "source_id": "policy:0",
                              "start": 999, "end": 1000, "quote": TEXT,
                              "explanation": "scope"}], "unresolved": []}
        return ModelResult(parsed, {"model_text": "raw"})


def test_unique_verbatim_quote_recovers_wrong_model_offsets():
    result = generate_case(_case(), [_theory("mistral", "m"),
                           _theory("nuextract", "n")],
                           mistral=_WrongOffsetsBackend("mistral"),
                           nuextract=_WrongOffsetsBackend("nuextract"))
    assert all(item.source_link.start == 0 for critique in result["critiques"]
               for item in critique.issues)
    assert all(item["status"] == "UNIQUE_QUOTE_OFFSETS_RECOVERED"
               for item in result["critique_binding_results"])


def test_multitype_model_issue_keeps_each_grounded_criticism():
    result = ModelResult({"issues": [{"target_element_id": "e1",
        "problem_type": ["wrong_modality", "wrong_relation"],
        "source_id": "policy:0", "start": 0, "end": len(TEXT),
        "quote": TEXT, "explanation": "Two separate suspected errors"}],
        "unresolved": []}, {"model_text": "raw"})
    critique, bindings = parse_model_critique(_case(), _FakeReviewBackend("mistral"),
                                  _theory("nuextract", "n"), result)
    assert [item.problem_type.value for item in critique.issues] == [
        "wrong_modality", "wrong_relation"]
    assert len({item.issue_id for item in critique.issues}) == 2
    assert bindings[0]["technical"] is False


class _AmbiguousQuoteBackend(_FakeReviewBackend):
    def critique(self, case, target):
        return ModelResult({"issues": [{"target_element_id": "e1",
            "problem_type": "wrong_scope", "source_id": "policy:0",
            "quote": "Repeat.", "explanation": "scope"}], "unresolved": []},
            {"model_text": "raw"})


def test_ambiguous_quote_is_technical_binding_issue_not_semantic_no_issues():
    repeated = CaseInput.parse({"case_id": "repeat", "sources": [{
        "source_id": "policy:0", "text": "Repeat. Repeat."}], "clauses": []})
    originals = [TheoryCandidate.parse({"candidate_id": provider, "provider": provider,
                  "elements": [{"element_id": "e1", "interpretation": "repeat",
                  "source_links": [], "rule_ir": None}]})
                 for provider in ("mistral", "nuextract")]
    result = generate_case(repeated, originals,
                           mistral=_AmbiguousQuoteBackend("mistral"),
                           nuextract=_AmbiguousQuoteBackend("nuextract"))
    assert result["critiques"] == []
    assert result["capability_failures"] == []
    assert len([item for item in result["technical_issues"]
                if item["operation"] == "CRITIQUE"]) == 2
    critique_runs = [item for item in result["model_runs"] if item["operation"] == "CRITIQUE"]
    assert all(item["status"] == "TECHNICAL_BINDING_ISSUE" for item in critique_runs)


def test_theory_level_grounded_omission_authorizes_addition_only_repair():
    parent = TheoryCandidate.parse({"candidate_id": "empty", "provider": "mistral",
                                    "elements": [], "clause_accounts": []})
    critique = TheoryCritique.parse({"critique_id": "missing", "reviewer_provider": "nuextract",
        "target_candidate_id": "empty", "issues": [{"issue_id": "missing:1",
        "target_element_id": "__theory__", "problem_type": "other",
        "source_link": {"source_id": "policy:0", "start": 0, "end": len(TEXT),
                        "quote": TEXT}, "explanation": "missing policy element"}]})
    result = ModelResult({"changes": [], "additions": [{
        "element_id": "added:1", "interpretation": "identity required before refund",
        "source_links": [{"source_id": "policy:0", "start": 0, "end": len(TEXT),
                          "quote": TEXT}], "rule_ir": None,
        "unresolved_components": []}], "unresolved": []}, {"model_text": "raw"})
    repair, build = _build_repair(_case(), parent, critique, result)
    assert repair is not None and [item.element_id for item in repair.elements] == ["added:1"]
    assert build["changed_element_ids"] == []
    assert build["added_elements"] == [{"element_id": "added:1",
                                         "marker": "MODEL_PROPOSED_ADDITION"}]
