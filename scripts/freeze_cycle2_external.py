"""Freeze a label-blind category-stratified step-level external sample."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess


CATEGORIES = (
    "agent_coercion", "capability_laundering", "goal_shift",
    "plan_exec_divergence", "tool_call_abuse",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_commit(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def tier(sample: dict) -> str:
    return (sample.get("provenance") or {}).get("tier", "gold")


def signatures(steps: list[dict]) -> list[dict]:
    def json_type(value):
        if isinstance(value, bool): return "boolean"
        if isinstance(value, int): return "integer"
        if isinstance(value, float): return "number"
        if isinstance(value, list): return "array"
        if isinstance(value, dict): return "object"
        return "string"

    result = {}
    for step in steps:
        action = step["action"]
        key = action["name"]
        result[key] = {
            "name": key,
            "action_class": action["class"],
            "arg_fields": [
                {"name": name, "type": json_type(action["args"][name]), "required": True}
                for name in sorted(action["args"])
            ],
            "basis": "SOURCE_DERIVED_SIGNATURE_NOT_EFFECT_DOCUMENTATION",
        }
    return [result[key] for key in sorted(result)]


def adapt(sample: dict, *, commit: str, relative_path: str) -> dict:
    ground = sample["ground_truth"]
    target = ground["drift_step"]
    steps = sample["trajectory"]
    decision = ground["expected_decision_at_drift"]
    return {
        "case_id": "aart::" + sample["id"],
        "source": "Alkur123/agentic-redteam-benchmark",
        "source_commit": commit,
        "trajectory_id": sample["id"],
        "domain": sample["category"],
        "policy_family": "declared_goal_and_plan",
        "error_family": sample["subcategory"],
        "tool_family": steps[target]["action"]["class"],
        "policy_or_normative_context": {
            "declared_goal": sample["declared_goal"],
            "declared_plan": sample["declared_plan"],
        },
        "history_prefix": steps[:target],
        "tool_schemas": signatures(steps[:target + 1]),
        "target_assistant_turn": {
            "thought": steps[target]["thought"],
            "action": steps[target]["action"],
        },
        "gold": {
            "verdict": "NO_ERROR" if decision == "CONTINUE" else "ERROR",
            "target_step": target,
            "source_decision": decision,
            "localization_basis": "source_ground_truth.drift_step_and_expected_decision_at_drift",
            "source_fields": [
                "ground_truth.drift_step",
                "ground_truth.expected_decision_at_drift",
                "ground_truth.drift_signals_expected",
                "ground_truth.rationale",
            ],
        },
        "provenance": {
            "tier": tier(sample),
            "source_path": relative_path.replace("\\", "/"),
            "source_file_sha256": None,
            "language": sample["language"],
            "difficulty": sample["difficulty"],
            "agent_runtime": sample["agent_runtime"],
            "author": sample["metadata"]["author"],
            "reviewed_by": sample["metadata"]["reviewed_by"],
            "iaa_subset": sample["metadata"]["iaa_subset"],
            "human_review_status": "SOURCE_TIER_GOLD_BUT_RECORD_REVIEWER_IDS_EMPTY",
        },
    }


def build(root: Path, *, expected_commit: str, per_category: int, seed: int,
          guardian_commit: str, adapter_path: Path) -> dict:
    actual_commit = source_commit(root)
    if actual_commit != expected_commit:
        raise ValueError("external source is not at the declared commit")
    grouped = {category: [] for category in CATEGORIES}
    for path in sorted((root / "v0.1" / "samples").glob("**/*.json")):
        sample = json.loads(path.read_text(encoding="utf-8"))
        if tier(sample) == "gold" and sample["category"] in grouped:
            grouped[sample["category"]].append((path, sample))
    selected = []
    for category in CATEGORIES:
        rows = sorted(grouped[category], key=lambda pair: pair[1]["id"])
        category_seed = seed + int(hashlib.sha256(category.encode()).hexdigest()[:8], 16)
        random.Random(category_seed).shuffle(rows)
        if len(rows) < per_category:
            raise ValueError("insufficient gold rows in category")
        selected.extend(rows[:per_category])
    cases = []
    for path, sample in selected:
        relative = str(path.relative_to(root))
        case = adapt(sample, commit=actual_commit, relative_path=relative)
        case["provenance"]["source_file_sha256"] = sha(path)
        cases.append(case)
    cases.sort(key=lambda row: row["case_id"])
    canonical = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "guardian-cycle2-external-manifest-v1",
        "frozen_before_predictions": True,
        "benchmark_role": "EXTERNAL_INDEPENDENT_STEP_LEVEL_WITH_SOURCE_REVIEW_LIMITATION",
        "source_repository": "https://github.com/Alkur123/agentic-redteam-benchmark",
        "source_commit": actual_commit,
        "source_validation": "2288/2288 source samples passed upstream validator",
        "source_license": "CC-BY-4.0",
        "selection": {
            "seed": seed,
            "strategy": "tier_gold_then_equal_category_sample_without_using_ground_truth",
            "per_category": per_category,
            "sample_ids": [case["trajectory_id"] for case in cases],
        },
        "guardian_research_base": "bbd58ef",
        "guardian_selection_commit": guardian_commit,
        "adapter_sha256": sha(adapter_path),
        "model_ids": ["tokenharbor=deepseek-v4-flash:free"],
        "binary_mapping": {"ERROR": 1, "NO_ERROR": 0},
        "no_tuning_after_label_join": True,
        "known_limitations": [
            "All selected records declare/inherit tier=gold, but metadata.reviewed_by is empty.",
            "The source repository's README says gold is human-reviewed; reviewer identity is not recorded per sample.",
            "Training-data contamination for the remote model cannot be ruled out.",
            "Tool schemas are source-derived signatures because the source does not ship executable tool schemas.",
        ],
        "cases_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--guardian-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=20)
    parser.add_argument("--seed", type=int, default=260912)
    args = parser.parse_args()
    payload = build(
        args.source_root, expected_commit=args.source_commit,
        per_category=args.per_category, seed=args.seed,
        guardian_commit=args.guardian_commit, adapter_path=Path(__file__),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(payload["cases"]), "cases_sha256": payload["cases_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
