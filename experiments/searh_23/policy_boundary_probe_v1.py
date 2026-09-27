"""Choose code-enumerated source cuts instead of generating source quotes.

The candidate cuts and expected selected cuts are frozen before Mistral calls.
Code constructs exhaustive disjoint source segments from returned cut IDs.
This is still a post-hoc component probe, not a full policy compiler.
"""
from __future__ import annotations

import argparse
import json
import re

import staged_policy_tree_v1 as v1
from policy_model_ab_v1 import sha
from policy_segmentation_probe_v1 import BASE as SOURCE_BASE


BASE = v1.ROOT / "experiments/searh_23/policy_boundary_probe_v1"
OUT = v1.ROOT / "outputs/searh_23/policy_boundary_probe_v1"
EXPECTED_CUT_HINTS = {
    "retail_cancel": ["and you should"],
    "retail_modify": ["and you should"],
    "retail_exchange": ["and you should", "In particular"],
    "airline_baggage": ["but not"],
    "airline_passenger_count": ["but cannot"],
    "telecom_resume": [],
    "telecom_payment_request": ["You should always"],
    "records_dev": ["Submitting a publication"],
    "hotel_cancellation_order": ["never refund"],
    "parcel_handover_transfer": ["Filing a handover"],
    "credit_preview_new": ["but you must"],
    "archive_release_new": ["Release through either", "filing a release request"],
}

SYSTEM = """You see ONE original policy and a CODE-ENUMERATED list of possible
cut IDs with left/right source context. Choose ONLY IDs where a new independent
directive or descriptive assertion begins. Return one JSON object only:
{"split_ids":["candidate id",...]}.
Keep IDs sorted in original source order. Never invent a new boundary.
Split contrasting permission/prohibition and independent instructions.
Do not separate an action from its IF/ONLY IF/AFTER condition. Do not split
an AND between prerequisites of the SAME action. Do not split a first and
second business operation if they form ONE ordering rule. A later sentence
that merely restates an earlier rule may remain separate as a source assertion;
do not derive any NEW rule from it. Do not choose tools or judge a case.
"""


def candidate_cuts(policy: str) -> list[dict]:
    offsets = {match.start() for match in re.finditer(r"\b(?:and|but|or)\b", policy, re.I)}
    offsets.update(match.end() for match in re.finditer(r"[.!?;]\s+(?=\S)", policy))
    offsets = sorted(position for position in offsets if 0 < position < len(policy))
    return [{"id": f"b{index}", "offset": position,
             "left": policy[max(0, position - 55):position],
             "right": policy[position:min(len(policy), position + 70)]}
            for index, position in enumerate(offsets)]


def segments_from_ids(policy: str, candidates: list[dict], selected: object) -> list[dict] | None:
    ids = [candidate["id"] for candidate in candidates]
    if (not isinstance(selected, list) or any(not isinstance(item, str) for item in selected)
            or len(set(selected)) != len(selected) or any(item not in ids for item in selected)
            or selected != sorted(selected, key=ids.index)):
        return None
    offsets = [next(candidate["offset"] for candidate in candidates if candidate["id"] == item)
               for item in selected]
    positions = [0, *offsets, len(policy)]
    return [{"start": left, "end": right, "source_quote": policy[left:right]}
            for left, right in zip(positions, positions[1:])]


def freeze() -> None:
    old = json.loads((SOURCE_BASE / "frozen.json").read_text(encoding="utf-8"))
    tasks = []
    for row in old["tasks"]:
        policy = row["query"]["policy"]
        candidates = candidate_cuts(policy)
        expected_offsets = []
        for hint in EXPECTED_CUT_HINTS[row["id"]]:
            if policy.count(hint) != 1:
                raise ValueError("gold boundary hint missing or duplicated: " + row["id"])
            expected_offsets.append(policy.index(hint))
        expected_ids = [candidate["id"] for candidate in candidates
                        if candidate["offset"] in expected_offsets]
        if len(expected_ids) != len(expected_offsets):
            raise ValueError("gold split not offered by candidate generator: " + row["id"])
        tasks.append({"id": row["id"], "query": {"policy": policy, "candidate_cuts": candidates},
                      "expected_split_ids": expected_ids})
    if {task["id"] for task in tasks} != set(EXPECTED_CUT_HINTS):
        raise ValueError("expected cut set does not cover source")
    protocol = {"systems": {"boundaries": SYSTEM}, "tasks": tasks, "max_tokens": 160,
                "note": "post-hoc viewed clauses; original bytes are preserved by construction"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen boundary protocol changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


def run() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    model = v1.Mistral()
    v1.OUT = OUT
    for task in protocol["tasks"]:
        v1._ask(model, protocol, task, "boundaries", task["query"], "__boundaries")


def score() -> dict:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    rows = []
    for task in protocol["tasks"]:
        record = json.loads((OUT / (task["id"] + "__boundaries.json")).read_text(encoding="utf-8"))
        if record["protocol_sha256"] != sha(protocol) or record["query_sha256"] != sha(task["query"]):
            raise ValueError("boundary source/prompt mismatch")
        answer = record["answer"]
        selected = answer.get("split_ids")
        segments = segments_from_ids(task["query"]["policy"], task["query"]["candidate_cuts"], selected)
        valid = record["finish_reason"] == "stop" and set(answer) == {"split_ids"} and segments is not None
        rows.append({"id": task["id"], "selected": selected, "expected": task["expected_split_ids"],
                     "valid": valid, "exact": valid and selected == task["expected_split_ids"],
                     "segments": segments if valid else None, "global_verdict": "UNKNOWN"})
    result = {"protocol_sha256": sha(protocol), "rows": rows,
              "valid": sum(row["valid"] for row in rows),
              "exact": sum(row["exact"] for row in rows), "total": len(rows)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in result.items() if key != "rows"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    phase = parser.parse_args().phase
    if phase == "freeze":
        freeze()
    elif phase == "run":
        run()
    else:
        print(json.dumps(score()))
