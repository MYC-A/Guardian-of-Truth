#!/usr/bin/env python3
"""Gold-free stress test for the conditional replacement obligation.

Each variant removes exactly one source prerequisite from an authored positive
refusal/handoff case. This suite was designed after inspecting v2 outputs and
is a diagnostic challenge, not an independent quality benchmark.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = (ROOT / "service_desk_v1/cases.csv",
           ROOT / "service_desk_v1_renamed/cases.csv")
OUTPUT = ROOT / "service_desk_precondition_ablation/cases.csv"

ABLATIONS = {
    "no_stock": (r'("available": )true', r'\1false'),
    "no_identity": (r'("match": )true', r'\1false'),
    "no_authorization": (r'("authorization_status": )"granted"',
                         r'\1"declined"'),
    "no_confirmation": (r"(?m)^Да, подтверждаю", "Пока не подтверждаю"),
}


def build() -> list[dict[str, str]]:
    result = []
    for source in SOURCES:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            cases = list(csv.DictReader(handle))
        targets = [row for row in cases if row["id"].endswith(
            ("__text_bad_refusal", "__text_bad_handoff"))]
        if len(targets) != 2:
            raise ValueError(f"expected two target cases in {source}")
        for case in targets:
            for name, (pattern, replacement) in ABLATIONS.items():
                changed, count = re.subn(pattern, replacement, case["prompt"],
                                         count=1)
                if count != 1:
                    raise ValueError(f"{case['id']}: {name} did not match once")
                result.append({"id": case["id"] + "__" + name,
                               "prompt": changed, "response": case["response"]})
    if len(result) != 16 or len({r["id"] for r in result}) != 16:
        raise ValueError("ablation IDs or coverage invalid")
    return result


def main() -> None:
    rows = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("id", "prompt", "response"))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} label-free prerequisite ablations to {OUTPUT}")


if __name__ == "__main__":
    main()
