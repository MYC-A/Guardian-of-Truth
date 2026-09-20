"""Analyze A1 suspicions quality: quote grounding rate, label deltas vs A0.

Local-only analysis over already-fetched results.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import parse_trace
from arch_b.fact_ledger import locate_quote

RES = Path(__file__).resolve().parents[1] / "results"
A0 = RES / "arch_a" / "A0"
A1 = RES / "arch_a" / "A1"


def main():
    labels = json.loads((RES.parent / "data" / "public46" / "labels_local.json").read_text())
    data = {}
    for line in (RES.parent / "data" / "public46" / "public46.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        data[r["id"]] = r

    a0 = {}
    for f in A0.glob("*.json"):
        rec = json.loads(f.read_text())
        if rec.get("ok"):
            a0[rec["id"]] = rec.get("label")
    a1 = {}
    a1_files = {}
    for f in A1.glob("*.json"):
        rec = json.loads(f.read_text())
        if rec.get("ok"):
            a1[rec["id"]] = rec.get("label")
            a1_files[rec["id"]] = rec

    common = sorted(set(a0) & set(a1))
    print(f"A0 done: {len(a0)}, A1 done: {len(a1)}, common: {len(common)}")

    # A0 vs A1 confusion deltas
    flips = {"0to1": [], "1to0": []}
    for cid in common:
        if a0[cid] != a1[cid]:
            flips[f"{a0[cid]}to{a1[cid]}"].append((cid, labels.get(cid)))

    # suspicion grounding analysis
    tot_sus = tot_r_found = tot_s_found = tot_both = 0
    n_cases_with_sus = 0
    for cid, rec in a1_files.items():
        sus = rec.get("suspicions", [])
        if sus:
            n_cases_with_sus += 1
        row = data[cid]
        trace = parse_trace(row["prompt"], row["response"])
        resp_seg = trace.response_segment
        for s in sus:
            tot_sus += 1
            r_found = bool(resp_seg and locate_quote(resp_seg.text, s.get("response_quote", ""))["found"])
            s_found = locate_quote(trace.full_text, s.get("source_quote", ""))["found"]
            tot_r_found += r_found
            tot_s_found += s_found
            tot_both += r_found and s_found

    print(f"suspicions total: {tot_sus}; response_quote found: {tot_r_found}; "
          f"source_quote found: {tot_s_found}; both: {tot_both}")
    print(f"cases with >=1 suspicion: {n_cases_with_sus}/{len(a1_files)}")
    print(f"label flips A0->A1: {flips}")

    # quick per-case view of disagreements with gold
    print("\nA1 vs gold mismatches (common cases):")
    for cid in common:
        if cid in labels and a1[cid] != labels[cid]:
            print(f"  {cid}: A0={a0[cid]} A1={a1[cid]} gold={labels[cid]}")


if __name__ == "__main__":
    main()
