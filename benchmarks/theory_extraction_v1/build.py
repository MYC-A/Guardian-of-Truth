"""Freeze the existing semantic synthetic cases for controlled B comparisons.

This adapter only prepares data.  Sentence boundaries are frozen into the
artifact and are never used as a production semantic parser.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from experiments.semantic_pipeline_v1.synthetic_cases import load_synthetic_cases


ROOT = Path(__file__).resolve().parent
POLICY_OPEN = "<policy>\n"
POLICY_CLOSE = "\n</policy>"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy_source(prompt: str) -> tuple[str, int]:
    start = prompt.index(POLICY_OPEN) + len(POLICY_OPEN)
    end = prompt.index(POLICY_CLOSE, start)
    block = prompt[start:end]
    # The controlled fixtures use one Markdown heading followed by the actual
    # policy paragraph.  Excluding that structural heading avoids pretending
    # it is a semantic clause while retaining exact prompt coordinates.
    if "\n\n" in block:
        heading, body = block.split("\n\n", 1)
        if heading.lstrip().startswith("#"):
            start += len(heading) + 2
            block = body
    return block, start


def _frozen_sentences(text: str) -> list[tuple[int, int, str]]:
    boundaries = [0]
    for match in re.finditer(r"(?<=[.!?])\s+(?=\S)", text):
        boundaries.append(match.end())
    boundaries.append(len(text))
    rows = []
    for left, right in zip(boundaries, boundaries[1:]):
        quote = text[left:right].strip()
        if not quote:
            continue
        start = text.index(quote, left, right)
        rows.append((start, start + len(quote), quote))
    return rows


def build() -> dict:
    cases = load_synthetic_cases()
    inputs, gold = [], []
    for case in cases:
        source, document_start = _policy_source(case["prompt"])
        clauses = [
            {"clause_id": f"{case['id']}:policy:{index}", "source_id": "policy",
             "start": start, "end": end, "quote": quote}
            for index, (start, end, quote) in enumerate(_frozen_sentences(source), 1)
        ]
        inputs.append({
            "case_id": case["id"],
            "sources": [{"source_id": "policy", "text": source,
                         "document": "prompt", "document_start": document_start}],
            "clauses": clauses,
        })
        gold.append({"case_id": case["id"], "label": case["label"],
                     "expected": case["expected"],
                     "required_contains": case["required_contains"]})

    input_path = ROOT / "input.jsonl"
    gold_path = ROOT / "gold.jsonl"
    csv_path = ROOT / "competition_input.csv"
    input_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                  for row in inputs), encoding="utf-8")
    gold_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                 for row in gold), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "prompt", "response"],
                                lineterminator="\n")
        writer.writeheader()
        for case in cases:
            writer.writerow({"id": case["id"], "prompt": case["prompt"],
                             "response": case["response"]})

    for row in inputs:
        source = row["sources"][0]
        original = next(case["prompt"] for case in cases if case["id"] == row["case_id"])
        assert original[source["document_start"]:
                        source["document_start"] + len(source["text"])] == source["text"]
        for clause in row["clauses"]:
            assert source["text"][clause["start"]:clause["end"]] == clause["quote"]

    manifest = {
        "source": "experiments/semantic_pipeline_v1/synthetic_cases.py",
        "status": "SYNTHETIC_SEEN_CONTROLLED_DIAGNOSTIC",
        "cases": len(inputs),
        "clauses": sum(len(row["clauses"]) for row in inputs),
        "input_sha256": _sha(input_path),
        "competition_input_sha256": _sha(csv_path),
        "gold_sha256": _sha(gold_path),
        "gold_firewall": "input.jsonl and competition_input.csv contain no labels or expected semantics",
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
