"""Selftest for scripts/c_alr_stage_a.py.

All fixtures are EXPLICITLY SYNTHETIC (case ids prefixed SYNTHETIC_SELFTEST_).
They exist only to verify tool mechanics: quadrant counting, attribution from
sealed-style logs, catalog-restricted recoverability classification, oracle
computation and the preregistered STOP gate. They are NOT V6 data and must never
be reported as experimental results.
"""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "c_alr_stage_a.py"
PREREG = REPO / "docs" / "vnext" / "C_ALR_PREREG_GATES_V1.json"

spec = importlib.util.spec_from_file_location("c_alr_stage_a", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def case(cid, family, c_ok, b4_ok, c_fields=None, gold_fields=None, stage_logs=None):
    gold = {}
    if gold_fields is not None or True:
        gold["semantic_fields"] = gold_fields or {}
        gold["worlds"] = []
    return {
        "case_id": cid,
        "family": family,
        "gold": gold,
        "c": {"semantic_fields": c_fields or {}, "case_correct": c_ok, "world_results": []},
        "b4": {"semantic_fields": {}, "case_correct": b4_ok, "world_results": [],
               **({"stage_logs": stage_logs} if stage_logs else {})},
    }


def synth_bundle(cases):
    return {"experiment": "SYNTHETIC_SELFTEST_ONLY", "benchmark_name": "synthetic",
            "case_count": len(cases), "cases": cases}


def test_quadrants_attribution_recoverability_oracle_pass():
    cases = []
    # 10 both correct
    for i in range(10):
        cases.append(case(f"SYNTHETIC_SELFTEST_both_{i}", "scope", True, True))
    # 2 C-correct / B4-wrong: one attributed, one unattributed
    cases.append(case("SYNTHETIC_SELFTEST_attr_slot", "only_if", True, False,
                      stage_logs={"declared_error_stage": "slot_primary"}))
    cases.append(case("SYNTHETIC_SELFTEST_attr_nologs", "exceptions", True, False))
    # 4 recoverable: catalog-covered diffs (1,1,1,2 mutations)
    cases.append(case("SYNTHETIC_SELFTEST_rec_modality", "only_if", False, True,
                      c_fields={"modality": "IF"}, gold_fields={"modality": "ONLY_IF"}))
    cases.append(case("SYNTHETIC_SELFTEST_rec_exc", "exceptions", False, True,
                      c_fields={"exception_attachment": "clause_a"}, gold_fields={"exception_attachment": "clause_b"}))
    cases.append(case("SYNTHETIC_SELFTEST_rec_temporal", "temporal", False, True,
                      c_fields={"temporal": "BEFORE"}, gold_fields={"temporal": "AFTER"}))
    cases.append(case("SYNTHETIC_SELFTEST_rec_two", "scope", False, True,
                      c_fields={"quantification": "ANY", "scope_attachment": "node_x"},
                      gold_fields={"quantification": "ALL", "scope_attachment": "node_y"}))
    # 1 global reparse: non-catalog field diff
    cases.append(case("SYNTHETIC_SELFTEST_global", "actor", False, True,
                      c_fields={"regulated_kind": "kind_x"}, gold_fields={"regulated_kind": "kind_y"}))
    # 1 uncertain: no field-level representations
    cases.append(case("SYNTHETIC_SELFTEST_uncertain", "cardinality", False, True,
                      c_fields=None, gold_fields=None))
    # 2 both wrong
    for i in range(2):
        cases.append(case(f"SYNTHETIC_SELFTEST_none_{i}", "coordination", False, False))

    report = mod.run_stage_a(synth_bundle(cases), json.loads(PREREG.read_text()))

    q = report["quadrants"]
    assert q["both_correct"]["count"] == 10
    assert q["c_correct_b4_wrong"]["count"] == 2
    assert q["c_wrong_b4_correct"]["count"] == 6
    assert q["both_wrong"]["count"] == 2

    attr = report["b4_failure_stage_attribution"]
    assert attr["per_case"]["SYNTHETIC_SELFTEST_attr_slot"] == "slot_primary"
    assert attr["per_case"]["SYNTHETIC_SELFTEST_attr_nologs"] == "UNATTRIBUTED_NO_LOGS"
    assert attr["counts"] == {"slot_primary": 1, "UNATTRIBUTED_NO_LOGS": 1}

    rec = report["b4_gain_recoverability"]
    assert rec["counts"] == {"LOCAL_PATCH_RECOVERABLE": 4, "REQUIRES_GLOBAL_REPARSE": 1, "UNCERTAIN": 1}
    per = rec["per_case"]
    assert per["SYNTHETIC_SELFTEST_rec_modality"]["label"] == "LOCAL_PATCH_RECOVERABLE"
    assert per["SYNTHETIC_SELFTEST_rec_two"]["label"] == "LOCAL_PATCH_RECOVERABLE"
    assert per["SYNTHETIC_SELFTEST_global"]["label"] == "REQUIRES_GLOBAL_REPARSE"
    assert per["SYNTHETIC_SELFTEST_global"]["reason"] == "diff_outside_catalog_or_too_many"
    assert per["SYNTHETIC_SELFTEST_uncertain"]["label"] == "UNCERTAIN"

    oracle = report["oracle"]
    assert oracle["n"] == 20
    assert oracle["c_correct"] == 12
    assert oracle["c_accuracy"] == 0.6
    assert oracle["local_patch_recoverable"] == 4
    assert oracle["recoverable_corpus_share"] == 0.2
    assert oracle["oracle_accuracy"] == 0.8
    assert oracle["oracle_gain"] == 0.2

    assert report["gates"]["decision"] == "PASS"
    assert report["verdict"] == "PROCEED_TO_C_ALR_DESIGN"


def test_stop_gate_triggers_reject_early():
    cases = []
    for i in range(38):
        cases.append(case(f"SYNTHETIC_SELFTEST_stop_both_{i}", "scope", True, True))
    cases.append(case("SYNTHETIC_SELFTEST_stop_none", "temporal", False, False))
    cases.append(case("SYNTHETIC_SELFTEST_stop_rec", "only_if", False, True,
                      c_fields={"modality": "IF"}, gold_fields={"modality": "ONLY_IF"}))

    report = mod.run_stage_a(synth_bundle(cases), json.loads(PREREG.read_text()))

    assert report["oracle"]["n"] == 40
    assert report["oracle"]["local_patch_recoverable"] == 1
    assert report["oracle"]["recoverable_corpus_share"] == 0.025
    assert report["gates"]["evaluated"]["recoverable_corpus_share_below_min"] is True
    assert report["gates"]["decision"] == "STOP"
    assert report["verdict"] == "REJECT_EARLY_STOP"


def test_too_many_catalog_mutations_requires_global_reparse():
    cases = [case("SYNTHETIC_SELFTEST_three", "scope", False, True,
                  c_fields={"modality": "IF", "temporal": "BEFORE", "quantification": "ANY"},
                  gold_fields={"modality": "ONLY_IF", "temporal": "AFTER", "quantification": "ALL"})]
    report = mod.run_stage_a(synth_bundle(cases), json.loads(PREREG.read_text()))
    per = report["b4_gain_recoverability"]["per_case"]["SYNTHETIC_SELFTEST_three"]
    assert per["label"] == "REQUIRES_GLOBAL_REPARSE"
    assert per["reason"] == "too_many_mutations"
    assert len(per["diffs"]) == 3


def test_missing_boolean_marks_incomplete():
    cases = [
        case("SYNTHETIC_SELFTEST_ok", "scope", True, True),
        {"case_id": "SYNTHETIC_SELFTEST_broken", "family": "scope",
         "gold": {}, "c": {"case_correct": True}, "b4": {"case_correct": "maybe"}},
    ]
    report = mod.run_stage_a(synth_bundle(cases), json.loads(PREREG.read_text()))
    assert report["inputs"]["analyzed_complete_cases"] == 1
    assert report["inputs"]["incomplete_cases"] == [
        {"case_id": "SYNTHETIC_SELFTEST_broken", "reason": "missing_boolean_case_correct"}
    ]
