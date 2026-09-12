import importlib.util
import json
from pathlib import Path

import pytest

from guardian_truth.vnext.integrity import (digest, file_digest, load_gold_after_seal,
                                            prediction_seal, verify_files, write_new)


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_order_and_no_nan():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    with pytest.raises(ValueError):
        digest(float("nan"))


def test_frozen_outputs_cannot_be_overwritten(tmp_path):
    path = tmp_path / "value.json"
    write_new(path, {"v": 1})
    with pytest.raises(FileExistsError):
        write_new(path, {"v": 2})


def test_verify_detects_changes_and_outside_root(tmp_path):
    path = tmp_path / "value.json"
    write_new(path, {"v": 1})
    assert verify_files(tmp_path, {"value.json": file_digest(path)}) == []
    assert verify_files(tmp_path, {"value.json": "0" * 64}) == ["value.json:HASH_MISMATCH"]
    assert verify_files(tmp_path, {"../outside": "0" * 64}) == ["../outside:OUTSIDE_ROOT"]


@pytest.mark.parametrize("rows", [[{"case_id": "a"}, {"case_id": "a"}], [], [{"case_id": "b"}]])
def test_predictions_require_exact_full_coverage(rows):
    with pytest.raises(ValueError):
        prediction_seal(rows, ["a"], architecture_commit="a" * 40, configuration_sha256="b" * 64)


def test_gold_is_not_opened_without_matching_seal(tmp_path):
    rows, ids = [{"case_id": "a", "core_status": "UNRESOLVED"}], ["a"]
    seal = prediction_seal(rows, ids, architecture_commit="a" * 40, configuration_sha256="b" * 64)
    with pytest.raises(ValueError):
        load_gold_after_seal(tmp_path / "nonexistent.json", expected_gold_sha256="c" * 64,
                             rows=rows + rows, case_ids=ids, seal=seal,
                             architecture_commit="a" * 40, configuration_sha256="b" * 64)


def test_gold_join_accepts_only_unchanged_predictions(tmp_path):
    rows, ids = [{"case_id": "a", "core_status": "UNRESOLVED"}], ["a"]
    path = tmp_path / "gold.json"
    write_new(path, {"labels": {"a": {"label": 1}}})
    seal = prediction_seal(rows, ids, architecture_commit="a" * 40, configuration_sha256="b" * 64)
    args = dict(expected_gold_sha256=file_digest(path), case_ids=ids, seal=seal,
                architecture_commit="a" * 40, configuration_sha256="b" * 64)
    assert load_gold_after_seal(path, rows=rows, **args)["labels"]["a"]["label"] == 1
    with pytest.raises(ValueError):
        load_gold_after_seal(path, rows=[{"case_id": "a", "core_status": "PROVED_ERROR"}], **args)


def test_frozen_benchmark_hashes_and_tool_gold():
    manifest_path = ROOT / "outputs/vnext/freeze_manifest.json"
    if not manifest_path.exists():
        pytest.skip("protocol bootstrap has not been run yet")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert verify_files(ROOT, manifest["frozen_input_sha256"]) == []
    assert verify_files(ROOT, manifest["regression_input_sha256"]) == []
    spec = importlib.util.spec_from_file_location("tool_reference", ROOT / "benchmarks/vnext/tool_reference_v1.py")
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    for path in (ROOT / "benchmarks/vnext").glob("*_v1.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["cases_sha256"] == digest(data["cases"])
        assert len({case["case_id"] for case in data["cases"]}) == len(data["cases"])
        if data["stage"] == "tool_semantics":
            for case in data["cases"]:
                assert reference.reference_effect(case["input"]) == (case["gold"]["effect_status"], case["gold"]["archived"])


def test_holdout_is_label_free_and_nonoverlapping():
    path = ROOT / "outputs/vnext/blind_cases.json"
    if not path.exists():
        pytest.skip("protocol bootstrap has not been run yet")
    # Inspect keys/IDs only, never blind text, rationale or decisions.
    blind = json.loads(path.read_text(encoding="utf-8"))
    old = json.loads((ROOT / "outputs/cycle2/external_manifest.json").read_text(encoding="utf-8"))
    old_ids = {case["case_id"] for case in old["cases"]}
    assert len(blind["cases"]) == 150
    assert not ({case["case_id"] for case in blind["cases"]} & old_ids)
    assert blind["cases_sha256"] == digest(blind["cases"])
    for case in blind["cases"]:
        assert set(case) == {"case_id", "policy_or_normative_context", "history_prefix", "tool_schemas", "target_assistant_turn"}
        assert set(case["target_assistant_turn"]) == {"thought", "action"}
