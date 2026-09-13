"""Independent source/gold/stage inventory checks for Goal-only freeze."""

import json
from pathlib import Path

from benchmarks.vnext.goal_v3_isolation_cases_v1 import cases
from guardian_truth.vnext.integrity import digest, file_digest, verify_files


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"
PREFIX = "goal_v3_isolation_v1"


def read(suffix):
    return json.loads((OUT / f"{PREFIX}_{suffix}.json").read_text(encoding="utf-8"))


def test_frozen_source_gold_and_stages_match_preimplementation_spec():
    manifest, inputs, gold = read("benchmark_freeze"), read("inputs"), read("gold")
    rows = cases()
    assert not verify_files(ROOT, manifest["source_sha256"])
    assert manifest["inputs_sha256"] == file_digest(OUT / f"{PREFIX}_inputs.json")
    assert manifest["gold_sha256"] == file_digest(OUT / f"{PREFIX}_gold.json")
    assert [row["case_id"] for row in inputs] == manifest["case_ids"]
    assert set(gold) == set(manifest["case_ids"])
    assert inputs == [{"case_id": row["case_id"], "source": row["input"]} for row in rows]
    assert gold == {row["case_id"]: row["gold"] for row in rows}
    assert manifest["case_source_sha256"] == {row["case_id"]: digest(row["input"]) for row in rows}
    assert manifest["stage_inventory_sha256"] == digest(manifest["stages"])
    assert [len(manifest["stages"][name]) for name in ("S1_smoke", "S2_remaining_core", "S3_stress")] == [12, 36, 12]
    assert set().union(*(set(ids) for ids in manifest["stages"].values())) == set(manifest["case_ids"])
    assert manifest["experimental_llm_calls_before_freeze"] == 0


def test_model_source_file_contains_no_gold_or_policy_payload():
    for row in read("inputs"):
        source = row["source"]
        assert "gold" not in source and "policy" not in source and "reference" not in source
        assert "expected_status" not in json.dumps(source)
