"""Reproducible unit/integrity checkpoint. NOT semantic or blind evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from guardian_truth.vnext.integrity import file_digest, verify_files, write_new


ROOT = Path(__file__).resolve().parents[1]


def git_head(path: Path) -> str:
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


def pytest_run(paths: list[str]) -> dict:
    import sys
    command = [sys.executable, "-m", "pytest", *paths, "-q"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    count = re.findall(r"(\d+) passed", completed.stdout)
    return {"command": ["python", "-m", "pytest", *paths, "-q"],
            "exit_code": completed.returncode, "passed": int(count[-1]) if count else 0,
            "status": "PASSED" if completed.returncode == 0 else "FAILED"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-name", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"checkpoint_checks_v[1-9][0-9]*\.json", args.output_name):
        raise ValueError("use a new versioned checkpoint basename")
    output = ROOT / "outputs/vnext" / args.output_name
    if output.exists():
        raise FileExistsError("checkpoint cannot be overwritten")
    manifest = json.loads((ROOT / "outputs/vnext/freeze_manifest.json").read_text(encoding="utf-8"))
    t1 = json.loads((ROOT / "outputs/vnext/tool_t1_freeze_v1.json").read_text(encoding="utf-8"))
    integrity = verify_files(ROOT, manifest["frozen_input_sha256"])
    integrity += verify_files(ROOT, manifest["regression_input_sha256"])
    integrity += verify_files(ROOT, t1["source_sha256"])
    protected = {"production": ("Guardian of Truth", manifest["baseline_commits"]["X0"]),
        "Cycle1": ("Guardian of Truth Next", manifest["baseline_commits"]["Cycle1"]),
        "Cycle2": ("Guardian of Truth Cycle2", manifest["cycle2_base"])}
    protected_heads = {name: {"actual": git_head(ROOT.parent / directory), "expected": expected}
                       for name, (directory, expected) in protected.items()}
    checks = {"proof_and_decision_units": pytest_run(["tests/test_vnext_proofs.py", "tests/test_vnext_decision.py"]),
              "full_project_units": pytest_run(["tests"])}
    good = not integrity and all(item["actual"] == item["expected"] for item in protected_heads.values()) and all(item["exit_code"] == 0 for item in checks.values())
    report = {"schema_version": "guardian-vnext-unit-checkpoint-v1", "architecture_commit": git_head(ROOT),
        "status": "UNIT_AND_INTEGRITY_VALIDATED_ONLY" if good else "FAILED",
        "scope": "unit tests and frozen-input integrity; not model semantics, full integration or blind gain",
        "test_checks": checks, "integrity_errors": integrity, "protected_heads": protected_heads,
        "protocol_manifest_sha256": file_digest(ROOT / "outputs/vnext/freeze_manifest.json"),
        "T1_stage_freeze_sha256": file_digest(ROOT / "outputs/vnext/tool_t1_freeze_v1.json"),
        "api_requests": 0, "full_frontend_core_integration": "PENDING",
        "model_semantic_stages": "NOT_RUN", "blind_end_to_end": "NOT_RUN"}
    write_new(output, report)
    print(json.dumps({"status": report["status"], "tests": checks, "integrity_errors": len(integrity), "api_requests": 0}))
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
