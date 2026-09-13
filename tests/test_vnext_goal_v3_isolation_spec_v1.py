"""Pre-inference integrity of the Goal-only 24-pair/12-stress source corpus."""

from copy import deepcopy
from collections import Counter

from benchmarks.vnext.goal_v3_isolation_cases_v1 import cases


def test_exact_60_case_inventory_and_sixteen_required_families():
    rows = cases()
    assert len(rows) == len({row["case_id"] for row in rows}) == 60
    paired = [row for row in rows if row["pair_id"]]
    stress = [row for row in rows if not row["pair_id"]]
    assert len(paired) == 48 and len(stress) == 12
    assert len({row["pair_id"] for row in paired}) == 24
    assert all(value == 2 for value in Counter(row["pair_id"] for row in paired).values())
    assert {f"F{index}" for index in range(1, 17)} <= {
        row["family"].split("_")[0] for row in paired}


def test_each_pair_changes_only_its_declared_meaningful_source_factor():
    by_pair = {}
    for row in cases():
        if row["pair_id"]:
            by_pair.setdefault(row["pair_id"], {})[row["variant"]] = row
    for pair_id, rows in by_pair.items():
        left, right = rows["a"], rows["b"]
        assert left["mutation_path"] == right["mutation_path"]
        restored = deepcopy(right["input"])
        original = left["input"]
        target, source = restored, original
        for part in left["mutation_path"][:-1]:
            target, source = target[part], source[part]
        leaf = left["mutation_path"][-1]
        assert target[leaf] != source[leaf], pair_id
        target[leaf] = deepcopy(source[leaf])
        assert restored == original, pair_id


def test_source_is_goal_only_and_gold_keeps_separate_behavioral_axes():
    for row in cases():
        source, gold = row["input"], row["gold"]
        assert "policy" not in source and "gold" not in source and "reference" not in source
        assert set(source) == {"user_messages", "assistant_plan", "tool_catalog", "target_action",
            "history_prefix", "history_complete", "session_complete", "unrelated_state"}
        assert source["user_messages"][0]["role"] == "user"
        assert source["target_action"]["actor"] == "assistant"
        assert gold["expected_status"] in {"PROVED_ERROR", "PROVED_NO_ERROR", "UNRESOLVED", "INCONSISTENT"}
        assert gold["expected_alignment"] in {"DIRECT_GOAL", "PERMITTED_AUXILIARY",
            "PROVED_OUT_OF_SCOPE", "AMBIGUOUS_ALIGNMENT"}
        assert gold["expected_obligation_status"] in {"NOT_APPLICABLE", "NOT_DUE_YET", "SATISFIED",
            "VIOLATED", "UNKNOWN"}
        assert gold["expected_decisive_violation"] is None or gold["expected_status"] == "PROVED_ERROR"
        assert gold["expected_status"] != "PROVED_ERROR" or gold["expected_decisive_violation"]
        assert gold["expected_status"] != "UNRESOLVED" or gold["expected_unknowns"]


def test_invariant_pairs_are_predeclared_not_accidental_same_label():
    by_id = {row["case_id"]: row for row in cases()}
    for pair_id in ("P02", "P07", "P14", "P21"):
        left, right = by_id[pair_id + ":a"], by_id[pair_id + ":b"]
        assert (left["gold"]["expected_status"], left["gold"]["expected_alignment"]) == (
            right["gold"]["expected_status"], right["gold"]["expected_alignment"])
