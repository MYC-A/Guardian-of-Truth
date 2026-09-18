import math
import json
from contextlib import nullcontext
import sys
from types import SimpleNamespace

from guardian_truth.semantic_pipeline_v1.models.gliner_optional import (
    GLiNER2Sidecar, normalize_gliner2_evidence)
from guardian_truth.semantic_pipeline_v1.models.langextract_optional import LangExtractAligner
from guardian_truth.semantic_pipeline_v1.models.lifecycle import ModelLifecycleManager
from guardian_truth.semantic_pipeline_v1.models.nli import NLIFirewall
from guardian_truth.semantic_pipeline_v1.models.nuextract import NuExtractRuleExtractor, normalize_nuextract
from guardian_truth.semantic_pipeline_v1.integration import phi_to_policy_readings
from guardian_truth.semantic_pipeline_v1.phi import build_phi
from guardian_truth.semantic_pipeline_v1.render import render_rule


class _Config:
    id2label = {0: "contradiction", 1: "entailment", 2: "neutral"}


class _Inner:
    config = _Config()


class FakeCrossEncoder:
    model = _Inner()

    def predict(self, pairs, *, apply_softmax):
        assert pairs == [("source", "rendering")]
        assert apply_softmax is False
        return [[2.0, 1.0, 0.0]]


def test_nli_preserves_raw_logits_and_normalizes_scores():
    evidence = NLIFirewall("fake-nli", FakeCrossEncoder()).check("source", "rendering")
    assert evidence.logits == (2.0, 1.0, 0.0)
    assert evidence.label == "CONTRADICTION"
    assert math.isclose(sum(evidence.scores.values()), 1.0)
    assert evidence.scores["CONTRADICTION"] > evidence.scores["ENTAILMENT"]


def test_nuextract_normalization_grounds_only_unique_exact_quote():
    source = "Never close account ACC-1. Never close account ACC-1. Verify identity first."
    value = {"actions": [{"action": "close", "object": "ACC-1", "modality": "FORBID",
                           "source_quote": "Never close account ACC-1."}],
             "temporal_relations": [{"first": "Verify identity", "relation": "before",
                                      "second": "close account",
                                      "source_quote": "Verify identity first."}]}
    candidates = normalize_nuextract(value, extractor="test", segment_id="s", source_text=source)
    assert candidates[0].source_spans == ()
    assert "ambiguous-source-quote:2" in candidates[0].unresolved_components
    assert candidates[1].source_spans[0].quote == "Verify identity first."
    assert candidates[1].rule.temporal == "BEFORE"
    assert candidates[1].rule.target.name == "Verify identity"
    assert candidates[1].rule.condition.term.name == "close account"


def test_nuextract_action_object_is_not_rendered_as_equality_or_assumed_entity():
    source = "Do not close the account."
    candidates = normalize_nuextract({"actions": [{
        "action": "close", "object": "the account", "modality": "FORBID",
        "source_quote": source}]}, extractor="test", segment_id="s", source_text=source)
    candidate = candidates[0]
    rendering = render_rule(candidate.rule)
    assert 'equals "the account"' not in rendering
    assert candidate.rule.target.value is None
    assert candidate.rule.entity_references == ()
    assert "unbound-action-object:the account" in candidate.unresolved_components


def test_nuextract_calls_processor_with_json_string_template(monkeypatch):
    captured = {}

    class Inputs(dict):
        def to(self, device):
            captured["device"] = device
            return self

    class Output:
        def __getitem__(self, key):
            assert key[1].start == 3
            return "trimmed-token-ids"

    class Processor:
        def apply_chat_template(self, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return Inputs(input_ids=SimpleNamespace(shape=(1, 3)))

        def batch_decode(self, generated, **kwargs):
            assert generated == "trimmed-token-ids"
            return ['{"actions":[{"action":"close","object":"account",'
                    '"modality":"FORBID","source_quote":"Never close account."}]}']

    class Model:
        device = "cuda:0"

        def generate(self, **kwargs):
            assert kwargs["do_sample"] is False
            return Output()

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        inference_mode=lambda: nullcontext()))
    extractor = NuExtractRuleExtractor(model_name="fake", model=Model(), processor=Processor())
    candidates = extractor.extract(segment_id="s", source_text="Never close account.")
    assert isinstance(captured["kwargs"]["template"], str)
    assert isinstance(json.loads(captured["kwargs"]["template"]), dict)
    assert captured["kwargs"]["enable_thinking"] is False
    assert candidates[0].source_spans[0].quote == "Never close account."


def test_gliner2_adapter_uses_json_subprocess_contract(tmp_path):
    worker = tmp_path / "worker.py"
    worker.write_text("", encoding="utf-8")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["request"] = json.loads(kwargs["input"])
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
            "status": "EXECUTED", "model": "g", "device": "cuda",
            "rows": [{"id": "x", "entities": {}, "relations": {}}]}))

    adapter = GLiNER2Sidecar(model_name="g", python_executable="sidecar-python",
                             worker_path=worker, run=fake_run)
    result = adapter.extract_batch([{"id": "x", "text": "A before B"}])
    assert captured["command"] == ["sidecar-python", str(worker)]
    assert "before" in captured["request"]["relation_labels"]
    assert result["rows"][0]["id"] == "x"


def test_gliner2_plain_json_becomes_independent_candidates_before_phi():
    source = "The policy prohibits closing the account. Identity verification before closure."

    def span(text):
        start = source.index(text)
        return {"text": text, "start": start, "end": start + len(text), "confidence": 0.8}

    row = {
        "entities": {"entities": {"action": [span("closing the account")]}},
        "relations": {"relation_extraction": {
            "prohibits": [{"head": span("The policy"), "tail": span("closing the account")}],
            "before": [{"head": span("Identity verification"), "tail": span("closure")}],
        }},
    }
    candidates = normalize_gliner2_evidence(
        row, segment_id="s", source_text=source, model_name="fake-gliner2")
    assert any(item.rule.modality == "FORBID"
               and item.rule.target.name == "closing the account" for item in candidates)
    assert any(item.rule.temporal == "BEFORE" for item in candidates)
    assert all(item.extractors == ("gliner2:fake-gliner2",) for item in candidates)
    phi = build_phi(candidates, ())
    assert len(phi.interpretations) == len(candidates)
    readings, unresolved = phi_to_policy_readings(phi)
    assert readings == ()
    assert any("gliner-modal-relation-endpoints-unresolved" in item for item in unresolved)
    assert any("gliner-temporal-modality-unknown" in item for item in unresolved)


def test_langextract_without_provider_is_not_a_successful_noop(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    status = LangExtractAligner().status()
    assert status == {"state": "UNAVAILABLE", "reason": "MODEL_PROVIDER_NOT_CONFIGURED",
                      "executed": False}


def test_lifecycle_reports_one_load_for_one_stage_batch():
    lifecycle = ModelLifecycleManager("cpu")
    with lifecycle.loaded(stage="batched", model_name="checkpoint", loader=lambda _: object()):
        for _ in range(5):
            pass
    assert lifecycle.load_counts() == {"checkpoint": 1}
    assert lifecycle.stage_load_counts() == {"batched": 1}
    assert lifecycle.records[0]["load_index"] == 1
