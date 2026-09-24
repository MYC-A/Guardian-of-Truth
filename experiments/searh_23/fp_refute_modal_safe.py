#!/usr/bin/env python3
"""Gold-free replay replacing v4's unsound no-modal inference.

A policy imperative can be binding without "must". Only a mechanically
observed not-yet-due precondition is refuted; other no-modal cards stay UNKNOWN.
This variant was written after the service-desk score and must be treated as
post-inspection development, not as an independent result on that suite.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import fp_refute_layer_v4 as v4
from fast_followup_run import (card_decisions, frozen, read_jsonl,
                               source_safe_guard)

UNSOUND_MODAL_EVIDENCE = "card quote contains no obligation modal; non-obligation span"


def refute_card(card: dict | None, sig: dict, reason: str = "") -> tuple[str, str]:
    verdict, evidence = v4.refute_card(card, sig, reason)
    if verdict != "REFUTED" or evidence != UNSOUND_MODAL_EVIDENCE:
        return verdict, evidence
    return "UNKNOWN", "absence of an obligation modal does not disprove an imperative"


def replay(run_dir: Path) -> dict:
    manifest, cases = frozen(run_dir)
    records = read_jsonl(run_dir / "pgjudge/pgjudge/records.jsonl", require_ok=True)
    cards = read_jsonl(run_dir / "pgjudge/extract/cards.jsonl", require_ok=True)
    case_map = {case["id"]: case for case in cases}
    if set(records) != set(case_map) or set(cards) != set(case_map):
        raise RuntimeError("pgjudge/card coverage incomplete")
    output = {"layer": "v4-source-safe with sound modal fallback",
              "input_sha256": manifest["cases_sha256"], "per_case": []}
    for cid in sorted(case_map):
        base = records[cid]
        row = {"id": cid, "pgjudge": base["label"], "new_label": base["label"]}
        if base["label"] == 1:
            case = case_map[cid]
            grounded = [card for card in cards[cid].get("cards", [])
                        if card.get("quote_grounded")]
            sig = v4.case_signals(case["prompt"], case["response"])
            guard = source_safe_guard(v4.structural_violation(
                case["prompt"], case["response"]))
            row["new_label"], row["verdicts"] = card_decisions(
                base, grounded, sig, refute_card, structural_guard=guard)
            row["source_safe_guard"] = guard
        output["per_case"].append(row)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.run_dir / "refute_modal_safe.json"
    if output.exists():
        raise FileExistsError(output)
    data = replay(args.run_dir)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    removed = sum(row["pgjudge"] == 1 and row["new_label"] == 0
                  for row in data["per_case"])
    print(f"modal-safe replay: {len(data['per_case'])} cases, {removed} alarms removed")


if __name__ == "__main__":
    main()
