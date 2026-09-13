"""Required final-package summaries link existing frozen DEV reports only."""

import importlib.util
import json
from pathlib import Path

from guardian_truth.vnext.integrity import file_digest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("semantic_stage_summary", ROOT / "scripts/summarize_vnext_completed_semantic_stages_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_claim_summary_preserves_failed_typed_gain_and_absent_contextual_gold():
    actual = json.loads((ROOT / "outputs/vnext/claim_graph_results.json").read_text(encoding="utf-8"))
    assert actual == MODULE.claim_summary(ROOT)
    assert actual["admission"]["span_gate"] is True
    assert actual["admission"]["shared_typed_gain_gate"] is False
    assert actual["unsupported_claim_recall"].startswith("NOT_ESTABLISHED")
    assert actual["downstream_core_gain"] == "NOT_RUN" and actual["blind_cases_read"] == 0
    assert actual["source_report_sha256"] == file_digest(ROOT / "outputs/vnext/claim_graph_v1_results.json")


def test_tool_summary_preserves_t1_applicability_and_t2_low_recall():
    actual = json.loads((ROOT / "outputs/vnext/tool_semantics_results.json").read_text(encoding="utf-8"))
    assert actual == MODULE.tool_summary(ROOT)
    assert actual["T1"]["evaluated"] == actual["T1"]["correct"] == 16
    assert actual["T1"]["not_applicable_missing_contract"] == 2
    assert actual["T2"]["known_true_candidate_recall"]["correct"] == 1
    assert actual["T2"]["known_true_candidate_recall"]["eligible"] == 4
    assert actual["T2"]["full_candidate_precision"].startswith("NOT_ESTABLISHED")
    assert actual["T2"]["unsafe_trusted_effects"]["count"] == 0
    assert actual["joint_downstream_core_gain"] == "NOT_RUN"
