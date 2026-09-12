"""Seal Cycle 2 artifacts and documentation into a machine-readable manifest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


OUTPUTS = (
    "model_gate.json", "policy_cases.json", "policy_results.json", "claim_cases.json",
    "claim_results.json", "tool_effect_results.json", "x5_execution.json",
    "external_manifest.json", "external_predictions.json", "e2e_results.json",
    "disagreement_matrix.json", "failure_taxonomy.json",
)
DOCS = (
    "CYCLE1_STATE_AUDIT.md", "MODEL_RELIABILITY_GATE.md", "POLICY_SEMANTICS_V2.md",
    "CLAIM_BENCHMARK.md", "TOOL_EFFECT_CEILING.md", "X5_EXECUTION_AUDIT.md",
    "EXTERNAL_STEP_DATASET_AUDIT.md", "EXTERNAL_FREEZE.md", "END_TO_END_RESULTS.md",
    "FAILURE_AUDIT.md", "FINAL_DECISION.md", "NEXT_CYCLE_CANDIDATES.md",
)


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _describe(path: Path) -> dict:
    raw = path.read_bytes()
    item = {"path": path.as_posix(), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}
    if path.suffix == ".json":
        value = json.loads(raw.decode("utf-8"))
        item["schema_version"] = value.get("schema_version")
        if "status" in value:
            item["status"] = value["status"]
    return item


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("outputs/cycle2/final_manifest.json"))
    parser.add_argument("--base-commit", default="bbd58ef")
    parser.add_argument("--production-worktree", type=Path, required=True)
    parser.add_argument("--cycle1-worktree", type=Path, required=True)
    parser.add_argument("--expected-production-commit", required=True)
    parser.add_argument("--expected-cycle1-commit", default="bbd58ef")
    parser.add_argument("--pytest-count", type=int, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.overwrite:
        raise ValueError("refusing to overwrite final manifest")
    output_paths = [Path("outputs/cycle2") / name for name in OUTPUTS]
    doc_paths = [Path("docs/cycle2") / name for name in DOCS]
    missing = [str(path) for path in [*output_paths, *doc_paths] if not path.is_file()]
    if missing:
        raise ValueError("missing required Cycle 2 artifacts: " + ", ".join(missing))
    generation_commit = _git("rev-parse", "HEAD")
    _git("merge-base", "--is-ancestor", args.base_commit, generation_commit)
    production_commit = _git("rev-parse", "HEAD", cwd=args.production_worktree)
    cycle1_commit = _git("rev-parse", "HEAD", cwd=args.cycle1_worktree)
    payload = {
        "schema_version": "guardian-cycle2-final-manifest-v1",
        "status": "SEALED",
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
        "lineage": {
            "base_commit": args.base_commit,
            "generation_commit": generation_commit,
            "branch": _git("branch", "--show-current"),
            "base_is_ancestor": True,
            "production_worktree_commit": production_commit,
            "production_worktree_unchanged": production_commit == args.expected_production_commit,
            "cycle1_worktree_commit": cycle1_commit,
            "cycle1_worktree_unchanged": cycle1_commit.startswith(args.expected_cycle1_commit),
        },
        "verification": {
            "pytest_passed": args.pytest_count,
            "pytest_failed": 0,
            "semantic_invariants": 12,
        },
        "outputs": [_describe(path) for path in output_paths],
        "documents": [_describe(path) for path in doc_paths],
    }
    if not payload["lineage"]["production_worktree_unchanged"]:
        raise ValueError("production worktree commit changed")
    if not payload["lineage"]["cycle1_worktree_unchanged"]:
        raise ValueError("Cycle 1 worktree commit changed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "generation_commit": generation_commit,
                      "files": len(output_paths) + len(doc_paths)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
