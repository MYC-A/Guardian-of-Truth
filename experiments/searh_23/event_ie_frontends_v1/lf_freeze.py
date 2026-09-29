"""Freeze the Level F / F2 / certificate datasets BEFORE any inference.

Validation performed here is purely structural (spans exist, references
resolve, evidence quotes exist, every canonical event used by an edge has
at least one anchored mention). If any assertion fails the freeze aborts
and nothing is written.

Outputs (frozen/):
  level_f_cases.json          main suite, 15 cases
  level_f_cases_renamed.json  same policies, opaque tool ids
  level_f2_cases.json         sealed validation suite (5 cases)
  level_f2_cases_renamed.json
  certificate_cases.json      22 endpoint-certificate unit items
  manifest.json               sha256 of every frozen file

Run:  python3 lf_freeze.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from lf_cases import CASES as MAIN_CASES
from lf_cases_f2 import CASES as F2_CASES
from lf_certificate_cases import ITEMS as CERT_ITEMS

MENTION_TYPES = {"EVENT", "EVENT_REFERENCE", "STATE_OR_FACET", "ARTIFACT",
                 "CHECK", "ENTITY", "UNKNOWN"}
ANCHOR_TYPES = {"EVENT", "EVENT_REFERENCE", "STATE_OR_FACET", "CHECK"}
LINK_TYPES = {"SAME_EVENT", "REFERENCE_OF", "STATE_OF", "ARTIFACT_ABOUT",
              "CHECKS"}


def split_sentences(policy: str) -> list[dict]:
    """Simple splitter on sentence-final punctuation; offsets recorded."""
    out = []
    start = 0
    for m in re.finditer(r"[.!?](\s|$)", policy):
        end = m.start() + 1
        text = policy[start:end].strip()
        if text:
            out.append({"start": start, "end": end, "text": text})
        start = m.end()
    if start < len(policy) and policy[start:].strip():
        out.append({"start": start, "end": len(policy),
                    "text": policy[start:].strip()})
    return out


def find_spans(policy: str, mentions: list) -> None:
    """Resolve char offsets sequentially; each search starts from the
    previous match START so nested/overlapping mentions stay valid."""
    cursor = 0
    resolved = []
    for (mid, span, mtype, cid) in mentions:
        idx = policy.find(span, cursor)
        assert idx >= 0, f"span not found after {cursor}: {span!r}"
        resolved.append({"mid": mid, "span": span, "start": idx,
                         "end": idx + len(span), "type": mtype, "cid": cid})
        cursor = idx
    return resolved


def build_case(case: dict, renamed: bool = False) -> dict:
    policy = case["policy"]
    sents = split_sentences(policy)

    mentions = find_spans(policy, case["mentions"])
    for m in mentions:
        sidx = None
        for i, s in enumerate(sents):
            if s["start"] <= m["start"] < s["end"]:
                sidx = i
                break
        m["sentence_index"] = sidx

    # canonical events
    events = []
    for (cid, predicate, role, tool) in case["events"]:
        events.append({"cid": cid, "predicate": predicate, "role": role,
                       "governed_tools": [tool] if tool else []})

    # tools (renamed => opaque ids, same descriptions)
    tools = []
    for i, t in enumerate(case["tools"], start=1):
        if renamed:
            tools.append({"name": f"tool_{i:02d}",
                          "description": t["description"],
                          "input": t["input"], "output": t["output"]})
        else:
            tools.append(dict(t))
    # remap governed_tools for renamed suite
    if renamed:
        name_map = {t["name"]: f"tool_{i:02d}"
                    for i, t in enumerate(case["tools"], start=1)}
        for e in events:
            e["governed_tools"] = [name_map[g] for g in e["governed_tools"]]

    # entities & arguments
    by_mid = {m["mid"]: m for m in mentions}
    entities = [{"xid": xid, "kind": kind,
                 "mention_mids": mids,
                 "spans": [by_mid[m]["span"] for m in mids]}
                for (xid, kind, mids) in case.get("entities", [])]
    arguments = [{"event_mid": emid, "role": role, "entity_xid": xid}
                 for (emid, role, xid) in case.get("arguments", [])]

    # semantic links (normalise: from mention -> mention or cid)
    links = []
    for (kind, src, dst) in case["links"]:
        assert kind in LINK_TYPES, kind
        links.append({"link": kind, "from": src, "to": dst})

    # normative edges with evidence offsets
    edges = []
    for (a, b, rel, acceptable, ev_text) in case["edges"]:
        i = policy.find(ev_text)
        assert i >= 0, f"evidence not found: {ev_text!r}"
        edges.append({"from_cid": a, "to_cid": b, "relation": rel,
                      "acceptable": acceptable,
                      "evidence": [{"start": i, "end": i + len(ev_text),
                                    "text": ev_text}]})

    # structural validation: every cid referenced by links/edges exists;
    # every event used by an edge has >=1 anchored mention or a link.
    cids = {e["cid"] for e in events}
    for m in mentions:
        if m["cid"]:
            assert m["cid"] in cids, (case["case_id"], m)
    for lk in links:
        if lk["to"].startswith("E"):
            assert lk["to"] in cids, (case["case_id"], lk)
        else:
            assert lk["to"] in by_mid, (case["case_id"], lk)
        assert lk["from"] in by_mid, (case["case_id"], lk)
    for e in edges:
        assert e["from_cid"] in cids and e["to_cid"] in cids
    for c in cids:
        anchored = any(m["cid"] == c and m["type"] in ANCHOR_TYPES
                       for m in mentions)
        assert anchored, f"{case['case_id']}: event {c} has no anchored mention"

    return {"case_id": case["case_id"] + ("_renamed" if renamed else ""),
            "original_case_id": case["case_id"],
            "domain": case["domain"], "family": case["family"],
            "policy": policy, "sentences": sents, "tools": tools,
            "mentions": mentions, "canonical_events": events,
            "entities": entities, "arguments": arguments,
            "semantic_links": links, "normative_edges": edges,
            "notes": case.get("notes", "")}


def build_cert_item(item: dict) -> dict:
    policy = item["policy"]
    for side in ("endpoint_a", "endpoint_b"):
        g = item["gold"][side]
        idx = policy.find(g["span"])
        assert idx >= 0, (item["id"], side, g["span"])
        g["start"], g["end"] = idx, idx + len(g["span"])
        chain = []
        for ch in g.get("ref_chain", []):
            cidx = policy.find(ch)
            assert cidx >= 0, (item["id"], "chain", ch)
            chain.append({"span": ch, "start": cidx, "end": cidx + len(ch)})
        g["ref_chain_spans"] = chain
    trig = item["gold"].get("relation_trigger")
    if trig:
        tidx = policy.find(trig["span"])
        assert tidx >= 0, (item["id"], "trigger", trig["span"])
        trig["start"], trig["end"] = tidx, tidx + len(trig["span"])
    return {"id": item["id"], "family": item["family"],
            "domain": item["domain"], "policy": policy,
            "edge": item["edge"], "gold": item["gold"],
            "notes": item.get("notes", "")}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    out = HERE / "frozen"
    out.mkdir(exist_ok=True)

    main_cases = [build_case(c) for c in MAIN_CASES]
    main_renamed = [build_case(c, renamed=True) for c in MAIN_CASES]
    f2_cases = [build_case(c) for c in F2_CASES]
    f2_renamed = [build_case(c, renamed=True) for c in F2_CASES]
    cert = [build_cert_item(i) for i in CERT_ITEMS]

    files = {
        "level_f_cases.json": main_cases,
        "level_f_cases_renamed.json": main_renamed,
        "level_f2_cases.json": f2_cases,
        "level_f2_cases_renamed.json": f2_renamed,
        "certificate_cases.json": cert,
    }
    manifest = {"created": "2026-09-29", "protocol": "LEVEL_F_FREEZE",
                "counts": {}}
    for name, data in files.items():
        p = out / name
        p.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n",
                     encoding="utf-8")
        manifest["counts"][name] = len(data)

    # summary statistics printed once, before any model sees anything
    n_mentions = sum(len(c["mentions"]) for c in main_cases)
    n_events = sum(len(c["canonical_events"]) for c in main_cases)
    n_edges = sum(len(c["normative_edges"]) for c in main_cases)
    n_links = sum(len(c["semantic_links"]) for c in main_cases)
    n_args = sum(len(c["arguments"]) for c in main_cases)
    types: dict[str, int] = {}
    for c in main_cases:
        for m in c["mentions"]:
            types[m["type"]] = types.get(m["type"], 0) + 1
    print("LEVEL F MAIN:", len(main_cases), "cases,", n_mentions,
          "mentions,", n_events, "events,", n_links, "links,",
          n_args, "arguments,", n_edges, "edges")
    print("mention types:", types)
    print("LEVEL F2 sealed:", len(f2_cases), "cases")
    print("CERTIFICATE items:", len(cert))

    manifest["files"] = {n: sha256(out / n) for n in files}
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("manifest written with", len(manifest["files"]), "hashes")


if __name__ == "__main__":
    main()
