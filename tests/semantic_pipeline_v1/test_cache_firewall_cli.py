import json
from pathlib import Path

from guardian_truth.semantic_pipeline_v1.cache import ContentAddressedCache, content_key
from guardian_truth.semantic_pipeline_v1.config import SemanticPipelineConfig
from guardian_truth.semantic_pipeline_v1.runner import load_input_records, run_experiment


def test_content_cache_is_deterministic_and_label_free(tmp_path):
    first = content_key(stage="x", model="m", config={"a": 1}, payload={"prompt": "p"})
    second = content_key(stage="x", model="m", config={"a": 1}, payload={"prompt": "p"})
    assert first == second
    cache = ContentAddressedCache(tmp_path)
    cache.put("x", first, {"answer": 1})
    assert cache.get("x", second) == {"answer": 1}


def test_gold_is_split_before_inference_objects(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text(json.dumps({"id": "x", "prompt": "p", "response": "r", "label": 1}) + "\n",
                    encoding="utf-8")
    records, gold = load_input_records(input_file=path)
    assert records[0].__dict__ == {"case_id": "x", "prompt": "p", "response": "r"}
    assert gold == {"x": 1}
    assert "label" not in records[0].__dict__


def test_cpu_safe_dry_run_creates_artifacts_and_resumes(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps([{"id": "case:1", "prompt": "plain prompt",
                                   "response": "plain response", "label": 0}]), encoding="utf-8")
    output = tmp_path / "out"
    config = SemanticPipelineConfig.for_ablation("A5", cache_dir=str(tmp_path / "cache"))
    first = run_experiment(input_file=source, output_dir=output, config=config,
                           resume=True, dry_run=True, case_id="case:1")
    second = run_experiment(input_file=source, output_dir=output, config=config,
                            resume=True, dry_run=True, case_id="case:1")
    assert first["predictions"] == second["predictions"]
    assert (output / "run_manifest.json").is_file()
    assert (output / "predictions.csv").is_file()
    assert (output / "metrics.json").is_file()
    assert list((output / "cases").glob("*/source_segments.json"))
    assert list((output / "traces").glob("*/summary.txt"))


def test_ablation_flags_match_declared_architectures():
    assert SemanticPipelineConfig.for_ablation("A0").use_current_frontend
    assert not SemanticPipelineConfig.for_ablation("A1").use_nuextract
    assert not SemanticPipelineConfig.for_ablation("A3").use_nli
    assert SemanticPipelineConfig.for_ablation("A5").use_binding
    assert SemanticPipelineConfig.for_ablation("A6").enable_gliner
    assert SemanticPipelineConfig.for_ablation("A7").enable_langextract
    assert SemanticPipelineConfig.for_ablation("A8").enable_gliner
    assert SemanticPipelineConfig.for_ablation("A2").core_backend == "unavailable"
    assert not SemanticPipelineConfig.for_ablation("A2").use_mistral
    assert not SemanticPipelineConfig.for_ablation("A5").enable_gliner
    assert not SemanticPipelineConfig.for_ablation("A5").enable_langextract
    assert SemanticPipelineConfig.for_ablation("A6").quality_evaluation_eligible
    assert not SemanticPipelineConfig.for_ablation("A7").quality_evaluation_eligible
    assert not SemanticPipelineConfig.for_ablation("A8").quality_evaluation_eligible
    assert SemanticPipelineConfig.for_ablation("A7").experiment_class == "diagnostic-only"


def test_a7_is_diagnostic_and_does_not_emit_quality_metrics(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps([{"id": "diagnostic", "prompt": "plain prompt",
                                   "response": "plain response", "label": 1}]), encoding="utf-8")
    result = run_experiment(input_file=source, output_dir=tmp_path / "out",
        config=SemanticPipelineConfig.for_ablation("A7", cache_dir=str(tmp_path / "cache")),
        resume=False, dry_run=True)
    assert result["manifest"]["experiment_class"] == "diagnostic-only"
    assert result["manifest"]["quality_evaluation_eligible"] is False
    assert "post_inference_evaluation" not in result["metrics"]
    assert result["metrics"]["post_inference_evaluation_skipped_reason"] == \
        "DIAGNOSTIC_ONLY_LANGEXTRACT"


def test_a2_non_dry_does_not_construct_hidden_mistral_client(tmp_path, monkeypatch):
    import guardian_truth.semantic_pipeline_v1.runner as runner
    from guardian_truth.semantic_pipeline_v1.models.embeddings import BGEEmbedder
    from guardian_truth.semantic_pipeline_v1.models.nuextract import NuExtractRuleExtractor

    class ForbiddenMistral:
        def __init__(self, **kwargs):
            raise AssertionError("A2 constructed a hidden Mistral client")

    original_retrieve = runner.retrieve_fragments

    def lexical_retrieve(*args, **kwargs):
        kwargs.pop("embedder", None)
        return original_retrieve(*args, **kwargs)

    monkeypatch.setattr(runner, "MistralRuleExtractor", ForbiddenMistral)
    monkeypatch.setattr(runner, "retrieve_fragments", lexical_retrieve)
    monkeypatch.setattr(BGEEmbedder, "load", staticmethod(lambda model, device: object()))
    monkeypatch.setattr(NuExtractRuleExtractor, "load",
                        staticmethod(lambda model, device: (object(), object())))
    monkeypatch.setattr(NuExtractRuleExtractor, "extract", lambda self, **kwargs: ())
    source = tmp_path / "input.jsonl"
    source.write_text("".join(json.dumps({"id": f"a2-{index}", "prompt": "plain prompt",
        "response": f"plain response {index}"}) + "\n" for index in range(3)), encoding="utf-8")
    result = run_experiment(input_file=source, output_dir=tmp_path / "out",
        config=SemanticPipelineConfig.for_ablation("A2", cache_dir=str(tmp_path / "cache")),
        resume=False, dry_run=False)
    assert result["manifest"]["core_semantic_backend"] == "unavailable"
    assert "mistral-small-latest" not in result["manifest"]["model_load_counts"]
    assert result["manifest"]["model_load_counts"] == {
        "BAAI/bge-m3": 1, "numind/NuExtract3-W4A16": 1}
    assert result["manifest"]["stage_load_counts"] == {
        "embedding_retrieval": 1, "nuextract": 1}


def test_a6_gliner_candidates_reach_nli_and_phi(tmp_path, monkeypatch):
    import guardian_truth.semantic_pipeline_v1.runner as runner
    from guardian_truth.semantic_pipeline_v1.models.embeddings import BGEEmbedder
    from guardian_truth.semantic_pipeline_v1.models.gliner_optional import GLiNER2Sidecar
    from guardian_truth.semantic_pipeline_v1.models.nli import NLIFirewall

    original_retrieve = runner.retrieve_fragments

    def lexical_retrieve(*args, **kwargs):
        kwargs.pop("embedder", None)
        return original_retrieve(*args, **kwargs)

    def fake_gliner(self, items, *, device):
        rows = []
        for item in items:
            text = item["text"]
            token = text.split()[0] if text.split() else ""
            rows.append({"id": item["id"], "entities": {"entities": {"action": [{
                "text": token, "start": 0, "end": len(token), "confidence": 0.7}]}},
                "relations": {"relation_extraction": {}}})
        return {"status": "EXECUTED", "model": self.model_name, "device": device,
                "architecture": "boundary", "load_duration_s": 0.1,
                "execution_duration_s": 0.1, "rows": rows}

    class FakeNLI:
        class Inner:
            class Config:
                id2label = {0: "contradiction", 1: "entailment", 2: "neutral"}
            config = Config()
        model = Inner()

        def predict(self, pairs, *, apply_softmax):
            return [[0.0, 2.0, 1.0] for _ in pairs]

    sidecar_python = tmp_path / "python"
    sidecar_python.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(runner, "retrieve_fragments", lexical_retrieve)
    monkeypatch.setattr(BGEEmbedder, "load", staticmethod(lambda model, device: object()))
    monkeypatch.setattr(GLiNER2Sidecar, "extract_batch", fake_gliner)
    monkeypatch.setattr(NLIFirewall, "load", staticmethod(lambda model, device: FakeNLI()))
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps({"id": "a6", "prompt": "Never close the account.",
                                  "response": "I will not close it."}) + "\n", encoding="utf-8")
    config = SemanticPipelineConfig.for_ablation(
        "A6", use_mistral=False, use_nuextract=False, use_binding=False,
        core_backend="unavailable", gliner_python=str(sidecar_python),
        cache_dir=str(tmp_path / "cache"))
    result = run_experiment(input_file=source, output_dir=tmp_path / "out",
                            config=config, resume=False, dry_run=False)
    row = result["predictions"][0]
    assert row["gliner_candidates"] > 0
    assert row["nli_entailment"] == row["gliner_candidates"]
    phi_files = list((tmp_path / "out" / "cases").glob("*/phi.json"))
    phi = json.loads(phi_files[0].read_text(encoding="utf-8"))
    assert any(extractor.startswith("gliner2:")
               for item in phi["interpretations"] for extractor in item["extractors"])
