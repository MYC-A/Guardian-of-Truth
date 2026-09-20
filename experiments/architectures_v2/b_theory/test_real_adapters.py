from __future__ import annotations

from dataclasses import replace

from guardian_truth.semantic_pipeline_v1.rule_ir import rule_digest
from guardian_truth.semantic_pipeline_v1.types import RuleCandidate, RuleIR, RuleTerm, SourceSpan

from experiments.architectures_v2.b_theory.contracts import CaseInput, TheoryCandidate, Variant
from experiments.architectures_v2.b_theory.formal_handoff import run_formal_handoff
from experiments.architectures_v2.b_theory.langextract_grounder import MistralLangExtractGrounder
from experiments.architectures_v2.b_theory.orchestrator import run_case
from experiments.architectures_v2.b_theory.provider_runner import run_provider_batch
from experiments.architectures_v2.b_theory.raw_capture import CapturedExtraction


TEXT = "Verify identity before refund."


def _case(case_id="c1"):
    return CaseInput.parse({"case_id": case_id,
        "sources": [{"source_id": "policy:0", "text": TEXT}], "clauses": []})


def _wire_candidate(candidate_id="wire1"):
    rule = RuleIR("REQUIRE", "assistant", RuleTerm("ACTION", name="Verify identity"))
    return RuleCandidate(candidate_id, rule, (SourceSpan("policy:0", 0, 15, TEXT[:15]),),
                         ("policy:0",), ("fake",), canonical_digest=rule_digest(rule))


def test_nuextract_loads_once_for_whole_batch():
    calls = {"load": 0, "extract": 0}

    def loader(model_name, device):
        calls["load"] += 1
        return object(), object()

    class FakeExtractor:
        def extract(self, **kwargs):
            calls["extract"] += 1
            return (_wire_candidate(f"wire{calls['extract']}"),)

    rows = run_provider_batch([_case("c1"), _case("c2")], ["nuextract"],
        mistral_model="ministral-14b-latest", nuextract_model="fake-nuextract",
        gliner_model="fake-gliner", gliner_python="fake-python",
        nuextract_loader=loader, nuextract_factory=lambda model, processor: FakeExtractor())
    assert calls == {"load": 1, "extract": 2}
    assert all(row["provider_runs"]["nuextract"]["batch_model_load_count"] == 1
               for row in rows)
    assert all(row["candidates"][0]["provider"] == "nuextract" for row in rows)


def test_mistral_factory_is_injected_and_wire_is_hashed():
    class FakeClient:
        def validate_configuration(self):
            return None

    class FakeExtractor:
        client = FakeClient()
        def extract_with_raw(self, **kwargs):
            return CapturedExtraction((_wire_candidate(),), {
                "kind": "MISTRAL_COMPLETION_PRE_NORMALIZATION",
                "completion_content": '{"rules": []}', "parsed_object": {"rules": []}})

    rows = run_provider_batch([_case()], ["mistral"],
        mistral_model="ministral-14b-latest", nuextract_model="unused",
        gliner_model="unused", gliner_python="unused",
        mistral_factory=FakeExtractor)
    run = rows[0]["provider_runs"]["mistral"]
    assert run["status"] == "EXECUTED"
    assert len(run["wire_sha256"]) == 64
    assert run["raw_available"] is True
    assert run["raw_responses"][0]["response"]["completion_content"] == '{"rules": []}'
    assert len(run["raw_sha256"]) == 64
    assert "api" not in str(run).casefold()


def test_langextract_injection_only_attaches_one_exact_span(monkeypatch):
    monkeypatch.setenv("TEST_MISTRAL_KEY", "secret-never-serialized")
    theory = TheoryCandidate.parse({"candidate_id": "t1", "provider": "mistral",
        "elements": [{"element_id": "e1", "interpretation": "identity is required",
                      "source_links": [], "rule_ir": None}]})
    factory_args = {}

    def factory(**kwargs):
        factory_args.update(kwargs)
        return object()

    def extract_fn(**kwargs):
        assert kwargs["examples"] == ["example"]
        return {"extractions": [{"extraction_text": "Verify identity",
                                  "char_interval": {"start_pos": 0, "end_pos": 15}}]}

    grounder = MistralLangExtractGrounder(
        api_key_env="TEST_MISTRAL_KEY", model_factory=factory,
        extract_fn=extract_fn, example_factory=lambda: "example")
    grounded = grounder.ground(_case(), theory)
    assert grounded.elements[0].source_links[0].quote == "Verify identity"
    assert factory_args["model_id"] == "ministral-14b-latest"
    assert factory_args["base_url"] == "https://api.mistral.ai/v1"
    assert factory_args["api_key"] == "secret-never-serialized"


def test_gliner_is_evidence_only_even_with_exact_span():
    candidate = TheoryCandidate.parse({"candidate_id": "g", "provider": "gliner",
        "elements": [{"wire_candidate": {
            "candidate_id": "gliner:1", "rule": {
                "modality": "REQUIRE", "subject": "assistant",
                "target": {"kind": "ACTION", "name": "Verify identity"},
                "source_spans": [],
            }, "source_spans": [{"segment_id": "policy:0", "start": 0, "end": 15,
                                  "quote": "Verify identity"}],
            "unresolved_components": []}}]})
    result = run_case(_case(), [candidate], Variant.B1)
    boundary = result["candidates"][0]["elements"][0]["ruleir_boundary"]
    assert boundary["status"] == "EVIDENCE_ONLY"
    assert result["proof_handoff"]["eligible_ruleir_count"] == 0


def test_formal_handoff_runs_alternatives_separately(monkeypatch):
    base = TheoryCandidate.parse({"candidate_id": "t1", "provider": "mistral",
        "elements": [{"wire_candidate": {
            "candidate_id": "mistral:1", "rule": {
                "modality": "REQUIRE", "subject": "assistant",
                "target": {"kind": "ACTION", "name": "Verify identity"},
                "source_spans": [],
            }, "source_spans": [{"segment_id": "policy:0", "start": 0, "end": 15,
                                  "quote": "Verify identity"}],
            "unresolved_components": []}}]})
    other = replace(base, candidate_id="t2", provider="nuextract")
    b_record = run_case(_case(), [base, other], Variant.B1)
    calls = []

    def fake_run(case, phi, arm):
        calls.append(phi)
        assert arm == "N5"
        assert len(phi["candidates"]) == 1
        assert phi["candidates"][0]["binding"]["status"] == "BOUND"
        return {"status": "UNRESOLVED", "binary": 0, "checker_ok": True,
                "checker_failures": [], "markers": [], "rules_lowered": 1,
                "interpretations": 1, "runtime_s": 0.01}

    monkeypatch.setattr(
        "experiments.architectures_v2.b_theory.formal_handoff._tool_names",
        lambda prompt: ("Verify identity",))
    result = run_formal_handoff(
        {"id": "c1", "prompt": TEXT, "response": ""}, b_record, run_arm_fn=fake_run)
    assert len(calls) == 2
    assert result["combination_policy"] == "NO_UNION_EACH_THEORY_RUN_SEPARATELY"
    assert all(item["exact_bound_rules"] == 1 for item in result["alternatives"])


def test_formal_handoff_does_not_run_unresolved_theory():
    record = {"case_id": "c1", "variant": Variant.B2.value,
              "candidates": [{"candidate_id": "t1", "provider": "mistral",
                              "candidate_status": "UNRESOLVED", "elements": []}]}
    result = run_formal_handoff(
        {"id": "c1", "prompt": TEXT, "response": ""}, record,
        run_arm_fn=lambda *args: (_ for _ in ()).throw(AssertionError("must not run")))
    alternative = result["alternatives"][0]
    assert alternative["n5"]["status"] == "UNRESOLVED"
    assert alternative["losses"][0]["reason"] == "THEORY_NOT_ELIGIBLE"
