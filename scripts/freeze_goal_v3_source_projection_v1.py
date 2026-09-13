"""Freeze the gold-free source projection inventory before Goal v3 inference."""

import json
from pathlib import Path

from benchmarks.vnext.goal_alignment_source_adapter_v1 import project_goal_alignment_source
from guardian_truth.vnext.integrity import digest, file_digest, write_new


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json"
ADAPTER = ROOT / "benchmarks/vnext/goal_alignment_source_adapter_v1.py"
OUTPUT = ROOT / "outputs/vnext/goal_alignment_v3_source_projection_v1_freeze.json"


def build_manifest(spec):
    rows = [{"case_id": case["id"],
             "source_sha256": project_goal_alignment_source(spec, case)["source_sha256"]}
            for case in spec["cases"]]
    if len(rows) != 36 or len({row["case_id"] for row in rows}) != 36:
        raise ValueError("expected exactly 36 distinct controlled source projections")
    return {"schema_version": "guardian-goal-v3-source-projection-freeze-v1",
        "scope": "CONTROLLED_SOURCE_ONLY_PREINFERENCE_NOT_PREDICTIONS_OR_GOLD_EVALUATION",
        "spec_sha256": file_digest(SPEC), "adapter_sha256": file_digest(ADAPTER),
        "case_source_hashes": rows, "case_source_inventory_sha256": digest(rows),
        "case_count": len(rows), "model_requests": 0, "v3_predictions": "NOT_RUN"}


def main():
    manifest = build_manifest(json.loads(SPEC.read_text(encoding="utf-8")))
    if OUTPUT.exists():
        if json.loads(OUTPUT.read_text(encoding="utf-8")) != manifest:
            raise ValueError("frozen source projection changed; create a new version")
    else:
        write_new(OUTPUT, manifest)
    print(json.dumps({"status": "SOURCE_PROJECTION_FROZEN_NOT_RUN", "cases": manifest["case_count"],
        "model_requests": 0}))


if __name__ == "__main__":
    main()
