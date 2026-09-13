"""Freeze 60 Goal-only source cases/gold/stages before any semantic API call."""

import json
from pathlib import Path
import subprocess

from benchmarks.vnext.goal_v3_isolation_cases_v1 import cases
from guardian_truth.vnext.integrity import digest, file_digest, write_new


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"
PREFIX = "goal_v3_isolation_v1"
FILES = (
    "benchmarks/vnext/goal_v3_isolation_cases_v1.py",
    "tests/test_vnext_goal_v3_isolation_spec_v1.py",
    "docs/vnext/GOAL_V3_ISOLATION_PROTOCOL_V1.md",
    "scripts/freeze_goal_v3_isolation_benchmark_v1.py",
)
SMOKE_IDS = ("P01:b", "P02:b", "P03:a", "P05:b", "P06:b", "P08:b",
             "P11:a", "P12:a", "P13:a", "P14:b", "P16:b", "P24:b")


def main():
    inputs_path = OUT / f"{PREFIX}_inputs.json"
    gold_path = OUT / f"{PREFIX}_gold.json"
    freeze_path = OUT / f"{PREFIX}_benchmark_freeze.json"
    if any(path.exists() for path in (inputs_path, gold_path, freeze_path)):
        raise FileExistsError("Goal-only benchmark v1 is immutable; use a new version")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *FILES], cwd=ROOT).returncode:
        raise ValueError("commit benchmark/protocol/freeze implementation first")
    for relative in FILES:
        if subprocess.run(["git", "ls-files", "--error-unmatch", relative], cwd=ROOT,
                          capture_output=True).returncode:
            raise ValueError("all benchmark source files must be tracked")
    rows = cases()
    inputs = [{"case_id": row["case_id"], "source": row["input"]} for row in rows]
    gold = {row["case_id"]: row["gold"] for row in rows}
    core_ids = [row["case_id"] for row in rows if row["pair_id"]]
    stress_ids = [row["case_id"] for row in rows if not row["pair_id"]]
    if (len(rows) != 60 or len(gold) != 60 or len(core_ids) != 48 or len(stress_ids) != 12
            or not set(SMOKE_IDS) <= set(core_ids) or len(set(SMOKE_IDS)) != 12):
        raise ValueError("exact preselected 24-pair/12-stress stage inventory required")
    if any("policy" in row["source"] or "gold" in row["source"] for row in inputs):
        raise ValueError("Policy/gold cannot enter Goal-only source inputs")
    write_new(inputs_path, inputs)
    write_new(gold_path, gold)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout.strip()
    stage_ids = {"S1_smoke": list(SMOKE_IDS),
        "S2_remaining_core": [case_id for case_id in core_ids if case_id not in SMOKE_IDS],
        "S3_stress": stress_ids}
    manifest = {"schema_version": "guardian-goal-v3-isolation-benchmark-freeze-v1",
        "scope": "GOAL_ONLY_CONTROLLED_60_CASE_PREINFERENCE_NOT_BLIND_EXTERNAL",
        "benchmark_commit": commit,
        "source_sha256": {relative: file_digest(ROOT / relative) for relative in FILES},
        "case_ids": [row["case_id"] for row in rows],
        "case_inventory": [{key: row[key] for key in ("case_id", "pair_id", "family", "variant", "mutation_path")}
            for row in rows],
        "case_source_sha256": {row["case_id"]: digest(row["input"]) for row in rows},
        "inputs_sha256": file_digest(inputs_path), "gold_sha256": file_digest(gold_path),
        "stages": stage_ids, "stage_inventory_sha256": digest(stage_ids),
        "random_seed": 260913, "experimental_llm_calls_before_freeze": 0,
        "metric_and_gate_protocol": "docs/vnext/GOAL_V3_ISOLATION_PROTOCOL_V1.md",
        "candidate_prompt_schema_provider": "SEPARATELY_FROZEN_BEFORE_FIRST_REQUEST",
        "gold_join_rule": "PREDICTIONS_SEALED_BEFORE_SCORER_OPENS_GOLD"}
    write_new(freeze_path, manifest)
    print(json.dumps({"status": "BENCHMARK_FROZEN_NOT_RUN", "cases": 60,
        "pairs": 24, "stress": 12, "experimental_api_requests": 0}))


if __name__ == "__main__":
    main()
