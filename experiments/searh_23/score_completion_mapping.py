#!/usr/bin/env python3
"""Post-inspection audit of claim-to-tool proposals; never used at inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/searh_23"))

import action_state_probe as actions  # noqa: E402
import completion_frame_probe as completion_probe  # noqa: E402
import completion_witness as completion  # noqa: E402

# Human audit of the *event meant by the claim*, written after inspecting v1.
# This is a scorer rubric only. It never conditions a model request or verdict.
TOOL_GOLD = {
    "desk_v1__text_bad_done": ("execute_replacement", "perform_swap"),
    "desk_v1__text_bad_wrong_case_auth": ("check_authorization", "lookup_approval"),
    "desk_v1__text_bad_wrong_amount_auth": ("check_authorization", "lookup_approval"),
    "desk_v1__text_bad_audit_claim": ("record_audit", "log_completion"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def audit_run(records: Path, *, variant: str, cases_file: Path,
              fresh_gold: dict | None = None) -> dict:
    source = {row["id"]: row for row in actions.cases(cases_file)}
    scored = []
    for row in rows(records):
        cid = row["id"]
        if fresh_gold is None:
            base_id = cid.removeprefix("renamed__")
            expected_tool = TOOL_GOLD[base_id][int(variant == "renamed")]
            expected_verdict = "UNSUPPORTED_COMPLETION_CANDIDATE"
        else:
            expected_tool = fresh_gold[cid]["tool"]
            expected_verdict = fresh_gold[cid]["verdict"]
        proposal = row.get("proposal") or {}
        item = {"id": cid, "tool": proposal.get("tool"),
                "expected_tool": expected_tool,
                "tool_correct": proposal.get("tool") == expected_tool,
                "verdict": row.get("verdict"), "expected_verdict": expected_verdict,
                "verdict_correct": row.get("verdict") == expected_verdict,
                "issues": row.get("issues", [])}
        # Exactly one policy clause exists in the authored fresh suite. Replacing
        # an abbreviated quote with that clause is an oracle serialization
        # replay, never a valid general policy-selection procedure.
        if fresh_gold is not None and row.get("issues") == ["invalid_policy_quote"]:
            policy, _ = completion_probe.policy_and_tools(source[cid])
            if "\n-" not in policy and len(policy.strip().splitlines()) == 1:
                repaired = {**proposal, "policy_quote": policy.strip()}
                verdict, issues, _ = completion.validate_v2(source[cid], repaired)
                item["one_clause_replay"] = {"verdict": verdict, "issues": issues}
        scored.append(item)
    return {"records_sha256": digest(records), "n": len(scored),
            "tool_correct": sum(item["tool_correct"] for item in scored),
            "verdict_correct": sum(item["verdict_correct"] for item in scored),
            "one_clause_replay_verdict_correct": sum(
                item.get("one_clause_replay", {}).get("verdict", item["verdict"])
                == item["expected_verdict"] for item in scored),
            "per_case": scored}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    artifacts = Path(args.artifacts)
    old = ROOT / "experiments/searh_23"
    fresh = old / "completion_fresh_v1"
    fresh_gold = json.loads((fresh / "gold.json").read_text(encoding="utf-8"))
    result = {}
    for version in ("", "v2_"):
        for name, suite in (("original", "service_desk_v1"),
                            ("renamed", "service_desk_v1_renamed")):
            key = ("v1_" if not version else "v2_") + name
            result[key] = audit_run(artifacts / f"completion_{version}{name}.jsonl",
                                    variant=name, cases_file=old / suite / "cases.csv")
    result["v2_fresh"] = audit_run(artifacts / "completion_v2_fresh.jsonl",
                                   variant="fresh", cases_file=fresh / "cases.csv",
                                   fresh_gold=fresh_gold)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(json.dumps({key: {k: item[k] for k in ("n", "tool_correct",
                  "verdict_correct", "one_clause_replay_verdict_correct")}
                      for key, item in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
