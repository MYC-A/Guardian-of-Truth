#!/usr/bin/env python3
"""Freeze a label-preserving lexical robustness pair before model readout."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "experiments/searh_23/service_desk_v1"
OUT = REPO / "experiments/searh_23/service_desk_v1_renamed"
RENAME = {
    "SD-5101": "CS-7824", "SD-9999": "CS-9136", "DV-7": "HW-43",
    "get_case": "load_ticket", "check_inventory": "lookup_stock",
    "verify_requester": "match_contact", "check_authorization": "lookup_approval",
    "execute_replacement": "perform_swap", "record_audit": "log_completion",
    "refund_fee": "issue_fee_credit", "transfer_specialist": "route_to_expert",
    "run_device_test": "user_self_test",
}


def translate(text: str) -> str:
    for before, after in RENAME.items():
        text = text.replace(before, after)
    return text


def main() -> None:
    if OUT.exists() and any(OUT.iterdir()):
        raise FileExistsError(f"frozen suite already exists: {OUT}")
    with (SOURCE / "cases.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 32 or set(rows[0]) != {"id", "prompt", "response"}:
        raise RuntimeError("source suite differs from the frozen 32-case schema")
    gold = json.loads((SOURCE / "expected.json").read_text(encoding="utf-8"))
    rubric = json.loads((SOURCE / "rubric.json").read_text(encoding="utf-8"))
    source_hash = hashlib.sha256((SOURCE / "cases.csv").read_bytes()).hexdigest()
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    if source_hash != manifest["cases_sha256"] or set(gold) != {row["id"] for row in rows}:
        raise RuntimeError("source suite seal or labels changed")
    transformed = [{"id": "renamed__" + row["id"],
                    "prompt": translate(row["prompt"]),
                    "response": translate(row["response"])} for row in rows]
    if any(row["prompt"] == old["prompt"] and row["response"] == old["response"]
           for row, old in zip(transformed, rows)):
        raise RuntimeError("lexical transformation left a case unchanged")
    OUT.mkdir(parents=True)
    with (OUT / "cases.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("id", "prompt", "response"))
        writer.writeheader()
        writer.writerows(transformed)
    expected = {"renamed__" + cid: value for cid, value in gold.items()}
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    translated_rubric = [{**entry, "id": "renamed__" + entry["id"]}
                         for entry in rubric]
    (OUT / "rubric.json").write_text(
        json.dumps(translated_rubric, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps({
        "suite": "service-desk-v1-renamed", "n": len(rows),
        "source_cases_sha256": source_hash,
        "cases_sha256": hashlib.sha256((OUT / "cases.csv").read_bytes()).hexdigest(),
        "gold_sha256": hashlib.sha256((OUT / "expected.json").read_bytes()).hexdigest(),
        "purpose": "paired lexical robustness, not independent-domain accuracy"},
        indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} paired renamed cases")


if __name__ == "__main__":
    main()
