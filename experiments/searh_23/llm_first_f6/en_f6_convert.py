"""F6: convert the FROZEN compact F6 files into the level_f full case
format used by the W1 chain (frontend/hygiene/bnorm/pipe3/score read
IE/frozen/level_f*_cases.json).

Deterministic, mirrors en_f5_convert.py. Adds the F6 sem_type and
embeds fields to every mention (they are ignored by the frozen W1
chain and consumed by the F6 mention/typing scorers).

Run ONCE before any F6 inference; outputs committed before inference.
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
SRC = HERE / "f6_frozen"


def to_full(c: dict, nonunique: list) -> dict:
    policy = c["policy"]
    for m in c["mentions"]:
        s = m[0]
        assert s in policy, f"{c['case_id']}: span not verbatim: {s!r}"
        if policy.count(s) > 1:
            nonunique.append(f"{c['case_id']}:{s!r}")
    sents = []
    pos = 0
    for s in [x.strip() for x in
              re.split(r"(?<=[.!?])\s+", policy) if x]:
        start = policy.find(s, pos)
        sents.append({"start": start, "end": start + len(s), "text": s})
        pos = start + len(s)
    mentions = []
    for i, m in enumerate(c["mentions"]):
        span, typ, cid, sem = m[0], m[1], m[2], m[3]
        extra = m[4] if len(m) > 4 else {}
        start = policy.find(span)
        sent_idx = next((k for k, s in enumerate(sents)
                         if s["start"] <= start < s["end"]), 0)
        rec = {"mid": f"m{i+1:02d}", "span": span,
               "start": start, "end": start + len(span),
               "type": typ, "cid": cid, "sem_type": sem,
               "sentence_index": sent_idx}
        if extra.get("embeds"):
            estart = policy.find(extra["embeds"])
            rec["embeds"] = {"span": extra["embeds"],
                             "start": estart,
                             "end": estart + len(extra["embeds"])}
        mentions.append(rec)
    cids = sorted({m[2] for m in c["mentions"] if m[2]})
    canonical = [{"cid": c_, "types": sorted({m[1] for m in c["mentions"]
                                              if m[2] == c_}),
                  "sem_types": sorted({m[3] for m in c["mentions"]
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
    shas = {}
    nonunique: list[str] = []
    for src_name, dst_name in (
            ("f6_cases.json", "level_f6_cases.json"),
            ("f6_cases_renamed.json", "level_f6r_cases.json")):
        cases = json.loads((SRC / src_name).read_text(encoding="utf-8")
                           )["cases"]
        out = [to_full(c, nonunique) for c in cases]
        (FROZEN / dst_name).write_text(
            json.dumps(out, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8")
        blob = json.dumps(out, sort_keys=True, ensure_ascii=False)
        shas[dst_name] = hashlib.sha256(blob.encode()).hexdigest()
        print(f"[f6c] {dst_name}: {len(out)} cases "
              f"sha {shas[dst_name][:12]}")
    if nonunique:
        print("[f6c] non-unique spans (first-occurrence offsets used):")
        for n in nonunique:
            print("   -", n)
    (HERE / "f6_frozen" / "f6_convert_manifest.json").write_text(
        json.dumps({"converted_at": "2026-09-29", "shas": shas,
                    "nonunique": nonunique}, indent=1) + "\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
