"""Freeze committed mechanism specification before v3 implementation; no API."""

import json
from pathlib import Path
import subprocess

from guardian_truth.vnext.integrity import digest, file_digest, write_new

ROOT = Path(__file__).resolve().parents[1]
PATHS = (
    "benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json",
    "docs/vnext/GOAL_PLAN_V3_DESIGN.md",
    "docs/vnext/GOAL_PLAN_V3_MECHANISM_PROTOCOL_V1.md",
    "tests/test_vnext_goal_v3_specification.py",
    "scripts/freeze_vnext_goal_v3_spec.py",
)


def main():
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "experiment/guardian-vnext-from-0199bf9":
        raise ValueError("new vNext branch required")
    for relative in PATHS:
        subprocess.run(["git", "ls-files", "--error-unmatch", relative], cwd=ROOT, capture_output=True, check=True)
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *PATHS], cwd=ROOT).returncode:
        raise ValueError("commit mechanism specification before freezing")
    spec = json.loads((ROOT / PATHS[0]).read_text(encoding="utf-8"))
    ids = [case["id"] for case in spec["cases"]]
    if len(ids) != len(set(ids)) or len(ids) != 36:
        raise ValueError("complete unique mechanism inventory required")
    result = {
        "schema_version": "guardian-preimplementation-spec-freeze-v1",
        "experiment": "goal_alignment_v3_mechanisms_v1",
        "scope": spec["scope"],
        "specification_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "case_ids": ids,
        "case_ids_sha256": digest(ids),
        "source_sha256": {relative: file_digest(ROOT / relative) for relative in PATHS},
        "v3_implementation": "NOT_RUN",
        "v3_inference": "NOT_RUN",
        "independent_reference_validation": "NOT_RUN",
        "blind_gold_opened": False,
        "api_requests": 0,
        "next": "independent fixture reference validation; separate new modules only after frozen Policy stage audit; separate architecture freeze before inference",
    }
    write_new(ROOT / "outputs/vnext/goal_alignment_v3_mechanisms_v1_spec_freeze.json", result)
    print(json.dumps({"case_count": len(ids), "status": "SPECIFICATION_FROZEN_NOT_EVALUATED", "api_requests": 0}))


if __name__ == "__main__":
    main()
