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
