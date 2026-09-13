"""Verify source freeze and safe candidate-input hashes, not candidate accuracy."""

import importlib.util
import json
from pathlib import Path

from guardian_truth.vnext.integrity import digest, verify_files

ROOT = Path(__file__).resolve().parents[1]


def test_preimplementation_binding_sources_and_scope_are_preserved():
    freeze = json.loads((ROOT / "outputs/vnext/binding_temporal_v2_spec_freeze.json").read_text(encoding="utf-8"))
    assert verify_files(ROOT, freeze["source_sha256"]) == []
    assert freeze["candidate_implementation"] == "NOT_RUN"
    assert freeze["candidate_predictions"] == "NOT_RUN"
    assert freeze["core_certificate_validation"] == "NOT_ESTABLISHED"
    assert freeze["api_requests"] == 0 and freeze["blind_gold_opened"] is False
    assert freeze["independent_reference_validation"]["matching_outcomes"] == 34


def test_all_34_safe_input_projection_hashes_reproduce():
    freeze = json.loads((ROOT / "outputs/vnext/binding_temporal_v2_spec_freeze.json").read_text(encoding="utf-8"))
    spec = json.loads((ROOT / "benchmarks/vnext/binding_temporal_v2.spec.json").read_text(encoding="utf-8"))
    module_spec = importlib.util.spec_from_file_location("binding_ref_freeze", ROOT / "benchmarks/vnext/binding_fixture_reference_v2.py")
    reference = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(reference)
    hashes = [{"case_id": case["id"], "input_sha256": digest(reference.candidate_input(reference.execute_fixture(case["input"])))}
        for case in spec["cases"]]
    assert hashes == freeze["candidate_input_hashes"]
    assert digest(hashes) == freeze["candidate_inputs_sha256"]
