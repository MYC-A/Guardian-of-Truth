"""Replay proposed pgjudge flips on identical IDs and inspect their anchors.

Input JSONL: {"id": ..., "label": 0|1, "evidence": [{"source":
"prompt"|"response", "quote": "exact substring", "operation": "..."}]}.
Exact anchoring checks transport only; source interpretation remains unaudited.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from experiments.recheck_2026.shared import (
    DEFAULT_CASES, DEFAULT_GOLD, REPO, cases, digest, jsonl, labels,
    new_output, score, write_json, write_jsonl,
)

PG = REPO / "outputs/big_researh/p_api/pgjudge/records.jsonl"
OPERATIONS = {"action_kind", "confirmation_question", "quote_entailment",
              "trigger_present", "last_observation", "operator_request_count",
              "pre_transfer_attempts", "required_data_requested"}


def audit_evidence(case: dict, evidence: object) -> tuple[bool, list[dict]]:
    if not isinstance(evidence, list) or not evidence:
        return False, [{"error": "missing evidence"}]
    checked = []
    for item in evidence:
        if not isinstance(item, dict):
            checked.append({"error": "evidence item is not an object"})
            continue
        source, quote, operation = (item.get("source"), item.get("quote"),
                                    item.get("operation"))
        valid = (source in {"prompt", "response"} and isinstance(quote, str)
                 and bool(quote) and quote in case[source]
                 and operation in OPERATIONS)
        checked.append({"source": source, "quote": quote,
                        "operation": operation, "exact_anchor": valid})
    return all(x.get("exact_anchor") for x in checked), checked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    case_map = cases(args.cases)
    base_rows = jsonl(PG)
    base = {r["id"]: r.get("label", r.get("pred")) for r in base_rows}
    incoming = jsonl(args.candidate)
    proposed = {r["id"]: r for r in incoming}
    if len(proposed) != len(incoming):
        raise ValueError("duplicate candidate ids")
    if set(proposed) != set(base) or set(base) != set(case_map):
        raise ValueError("candidate, pgjudge and case ID sets must match exactly")
    gold = labels(args.gold)
    output = new_output(args.out)
    write_json(output / "config.json", {"experiment": "pgjudge_fp_replay_v1",
        "candidate_sha256": digest(args.candidate), "pgjudge_sha256": digest(PG),
        "case_sha256": digest(args.cases), "gold_sha256": digest(args.gold),
        "anchor_check": "exact substring only; no semantic entailment claim"})
    records = []
    for cid in sorted(base):
        row = proposed[cid]
        predicted = row.get("label")
        if type(predicted) is not int or predicted not in (0, 1):
            raise ValueError(f"invalid candidate label for {cid}")
        old = int(base[cid])
        anchored, checked = audit_evidence(case_map[cid], row.get("evidence"))
        if predicted != old and not anchored:
            raise ValueError(f"flip lacks exact anchored evidence: {cid}")
        records.append({"id": cid, "gold": gold.get(cid), "base": old,
                        "candidate": predicted, "flip": predicted != old,
                        "anchor_valid": anchored, "evidence": checked})
    write_jsonl(output / "records.jsonl", records)
    write_json(output / "summary.json", {"base": score(records, "base"),
        "candidate": score(records, "candidate"),
        "n_flips": sum(r["flip"] for r in records),
        "flips": [{"id": r["id"], "gold": r["gold"], "base": r["base"],
                   "candidate": r["candidate"], "evidence": r["evidence"]}
                  for r in records if r["flip"]],
        "limitation": "exact quotes validate provenance, not semantic correctness"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
