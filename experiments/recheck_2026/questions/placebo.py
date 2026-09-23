"""Swap verified Q candidates across cases to test generic prompt effects."""
from __future__ import annotations

import argparse
from pathlib import Path

from experiments.recheck_2026.questions.run import JUDGE_SYSTEM, judge_input, strict_label
from experiments.recheck_2026.shared import (
    DEFAULT_CASES, Mistral, MistralRateLimit, cases, digest, jsonl,
    mistral_settings, prepare_run, score, write_json, write_jsonl,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q-records", type=Path, required=True)
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--context-chars", type=int, default=18000)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    source = jsonl(args.q_records)
    if len(source) < 2 or len({r["id"] for r in source}) != len(source):
        raise ValueError("need at least two distinct Q cases")
    if any(r.get("baseline") not in (0, 1) or r.get("repair") not in (0, 1)
           or r.get("status") != "probabilistic_candidate" for r in source):
        raise ValueError("Q source must have complete matched pairs")
    case_map = cases(args.cases)
    if any(r["id"] not in case_map for r in source):
        raise ValueError("Q case missing from input")
    config = {"experiment": "q_cross_domain_placebo_v2",
              "q_records_sha256": digest(args.q_records),
              "case_sha256": digest(args.cases),
              "ids": [r["id"] for r in source],
              "context_chars": args.context_chars,
              "model": mistral_settings()["MISTRAL_MODEL"],
              "system": JUDGE_SYSTEM,
              "placebo": "next selected case from a different domain"}
    rows = prepare_run(args.out, config, args.resume)
    by_id = {r["id"]: r for r in rows}
    client = Mistral()
    for index, original in enumerate(source):
        cid = original["id"]
        if cid in by_id and by_id[cid].get("placebo") in (0, 1):
            continue
        domain = cid.split("__", 1)[0]
        donor = next((source[(index + offset) % len(source)]
                      for offset in range(1, len(source))
                      if source[(index + offset) % len(source)]["id"].split(
                          "__", 1)[0] != domain), None)
        if donor is None:
            raise ValueError("no cross-domain donor for placebo")
        candidate = {"source_quote": donor["source_quote"],
                     "situation": donor["question"]["value"].get("situation"),
                     "answer": donor["question"]["value"].get("proposed_answer")}
        user, meta = judge_input(case_map[cid], candidate, args.context_chars)
        record = {"id": cid, "gold": original["gold"],
                  "baseline": original["baseline"], "repair": original["repair"],
                  "placebo": None, "donor_id": donor["id"], "input_meta": meta}
        try:
            response = client.ask(JUDGE_SYSTEM, user, max_tokens=1000)
            record["placebo"] = strict_label(response)
            record["result"] = response
        except MistralRateLimit:
            raise
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        by_id[cid] = record
        rows = [by_id[r["id"]] for r in source if r["id"] in by_id]
        write_jsonl(args.out / "records.jsonl", rows)
    rows = [by_id[r["id"]] for r in source if r["id"] in by_id]
    paired = [r for r in rows if r.get("placebo") in (0, 1)]
    write_json(args.out / "summary.json", {
        "n_paired": len(paired),
        "baseline": score(paired, "baseline"),
        "repair": score(paired, "repair"),
        "placebo": score(paired, "placebo"),
        "baseline_fp_removed_by_repair": [r["id"] for r in paired
            if r["gold"] == 0 and r["baseline"] == 1 and r["repair"] == 0],
        "baseline_fp_removed_by_placebo": [r["id"] for r in paired
            if r["gold"] == 0 and r["baseline"] == 1 and r["placebo"] == 0],
        "note": "cross-case candidate tests prompt sensitivity, not formal entailment"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
