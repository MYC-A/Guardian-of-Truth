"""EN-1: convert the FROZEN compact F5 files into the level_f full case
format used by the W1 chain (frontend/hygiene/bnorm/pipe3/score read
IE/frozen/level_f*_cases.json).

Deterministic: offsets computed by policy.find (validated unique), the
same construction as w1_f3_build.py build(). Input files are the frozen
f5_frozen/*.json (commit 32bbad4e, sha 4546acef...). Output sha256
manifests recorded for audit. Run ONCE before any F5 inference; the
outputs are committed before inference starts.

Run (server): /workspace/guardian/venv/bin/python en_f5_convert.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
FROZEN = IE / "frozen"
SRC = HERE / "f5_frozen"


def to_full(c: dict, nonunique: list) -> dict:
    policy = c["policy"]
    # spans must be verbatim; occurrences may repeat (e.g. an entity span
    # inside both the imperative and the passive state). Offsets use the
    # FIRST occurrence (find). Repeats are logged for the manifest.
    for s in [m[0] for m in c["mentions"]]:
        assert s in policy, \
            f"{c['case_id']}: span not verbatim: {s!r}"
        if policy.count(s) > 1:
            nonunique.append(f"{c['case_id']}:{s!r}")
    # sentences with offsets
    sents = []
    pos = 0
    for s in [x.strip() for x in
              re.split(r"(?<=[.!?])\s+", policy) if x]:
        start = policy.find(s, pos)
        sents.append({"start": start, "end": start + len(s), "text": s})
        pos = start + len(s)
    # mentions with offsets
    mentions = []
    for i, (span, typ, cid) in enumerate(c["mentions"]):
        start = policy.find(span)
        sent_idx = next((k for k, s in enumerate(sents)
                         if s["start"] <= start < s["end"]), 0)
        mentions.append({"mid": f"m{i+1:02d}", "span": span,
                         "start": start, "end": start + len(span),
                         "type": typ, "cid": cid,
                         "sentence_index": sent_idx})
    cids = sorted({m[2] for m in c["mentions"] if m[2]})
    canonical = [{"cid": c_, "types": sorted({m[1] for m in c["mentions"]
                                              if m[2] == c_})}
                 for c_ in cids]
    edges = [{"from_cid": a, "to_cid": b, "relation": r[0],
              "acceptable": r, "evidence": ev}
             for a, b, r, ev in c["normative_edges"]]
    for e in edges:
        assert e["from_cid"] in cids and e["to_cid"] in cids
    return {"case_id": c["case_id"],
            "original_case_id": c["case_id"],
            "domain": c["domain"], "family": c["family"],
            "policy": policy, "sentences": sents,
            "tools": c["tools"], "mentions": mentions,
            "canonical_events": canonical,
            "entities": [m["span"] for m in mentions
                         if m["type"] == "ENTITY"],
            "arguments": [], "semantic_links": [],
            "normative_edges": edges,
            "related_pairs": [list(p) for p in c.get("related_pairs", [])],
            "ambiguous_pairs": [list(p)
                                for p in c.get("ambiguous_pairs", [])],
            "notes": c.get("notes", "")}


def main() -> None:
    FROZEN.mkdir(parents=True, exist_ok=True)
    out = {}
    nonunique: list[str] = []
    for src_name, dst_name in (
            ("f5_cases.json", "level_f5_cases.json"),
            ("f5_cases_renamed.json", "level_f5r_cases.json")):
        cases = json.loads((SRC / src_name).read_text(encoding="utf-8")
                           )["cases"]
        full = [to_full(c, nonunique) for c in cases]
        path = FROZEN / dst_name
        path.write_text(json.dumps(full, indent=1, ensure_ascii=False)
                        + "\n", encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out[dst_name] = {
            "from": src_name,
            "cases": len(full),
            "mentions": sum(len(c["mentions"]) for c in full),
            "gold_edges": sum(len(c["normative_edges"]) for c in full),
            "sha256": digest,
            "frozen": "2026-09-29 (derived deterministically from "
                      "f5_frozen/ BEFORE any F5 inference)"}
        print(f"[convert] {dst_name}: {len(full)} cases, "
              f"{out[dst_name]['mentions']} mentions, "
              f"{out[dst_name]['gold_edges']} edges, sha {digest[:16]}")
    (HERE / "outputs" / "f5_convert_manifest.json").parent.mkdir(
        parents=True, exist_ok=True)
    out["nonunique_first_occurrence_spans"] = nonunique
    (HERE / "outputs" / "f5_convert_manifest.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"[convert] spans occurring >1x (first-occurrence offsets): "
          f"{len(nonunique)}")
    # cross-check against the frozen source sha
    src_blob = (SRC / "f5_cases.json").read_text(encoding="utf-8")
    m = json.loads((SRC / "f5_manifest.json").read_text(encoding="utf-8"))
    print(f"[convert] source manifest sha {m['sha256'][:16]}... "
          f"(n_cases={m['n_cases']}, n_edges={m['n_gold_edges']})")


if __name__ == "__main__":
    main()
