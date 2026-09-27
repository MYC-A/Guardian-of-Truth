"""Freeze the POLICY-LICENSED RELATIONS dataset BEFORE any inference.

Validates every span/evidence verbatim against its policy, computes char
offsets, builds the full unordered pair universe (ALL events, including
descriptive), flags hard negatives by a FIXED a-priori rule, emits the
renamed suite (tool names -> neutral codes), splits manifest, CF links and
a SHA256 manifest. Fails loudly on any inconsistency.

Hard-negative rule (fixed before inference, documented):
  a negative pair is HARD iff the two event spans share a sentence
  OR the pair is role-compatible (condition-like -> operation-like, or
  operation-like -> operation-like). Everything else is EASY.

Run: python3 pl_freeze.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_cases_a import CALIB_CASES, VAL_CASES
from pl_cases_b import TEST_CASES

ROOT = Path(__file__).parent
FROZEN = ROOT / "frozen"

ALL_CASES = CALIB_CASES + VAL_CASES + TEST_CASES

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

ROLE_CONDITION_LIKE = {"PRECONDITION_CHECK", "STATE_OBSERVATION"}
ROLE_OP_LIKE = {"OPERATION_EFFECT", "COMMUNICATION"}


def resolve_tools(cases):
    by_id = {c["case_id"]: c for c in cases}
    for c in cases:
        if isinstance(c.get("tools"), str) and c["tools"].startswith("SAME_AS:"):
            src = by_id[c["tools"][len("SAME_AS:"):]]
            c["tools"] = json.loads(json.dumps(src["tools"]))
    return cases


def find_offset(policy: str, text: str):
    idx = policy.find(text)
    return idx


def sentence_index_of_span(policy: str, span: str):
    idx = policy.find(span)
    if idx < 0:
        return -1
    pos, k = 0, 0
    for s in SENT_SPLIT.split(policy):
        if span in s and policy.find(s) <= idx:
            return k
        pos += len(s) + 1
        k += 1
    return k


def is_hard_negative(ev_a, ev_b, same_sentence: bool):
    if same_sentence:
        return True
    if ev_a["role"] in ROLE_CONDITION_LIKE and ev_b["role"] in ROLE_OP_LIKE:
        return True
    if ev_a["role"] in ROLE_OP_LIKE and ev_b["role"] in ROLE_OP_LIKE:
        return True
    return False


def build_case_record(case, renamed: bool):
    policy = case["policy"]
    tools = case["tools"]
    tool_names = {t["name"] for t in tools}
    rename_map = {}
    if renamed:
        new_tools = []
        for i, t in enumerate(tools, 1):
            new_name = f"tool_{i:02d}"
            rename_map[t["name"]] = new_name
            nt = json.loads(json.dumps(t))
            nt["name"] = new_name
            new_tools.append(nt)
        tools = new_tools
        tool_names = {t["name"] for t in tools}

    events = []
    for ev in case["events"]:
        gt = [rename_map.get(n, n) for n in ev.get("governed_tools", [])]
        assert ev["span"] in policy, f"{case['case_id']}: event span not verbatim: {ev['span']!r}"
        for n in gt:
            assert n in tool_names, f"{case['case_id']}: unknown governed tool {n}"
        start = find_offset(policy, ev["span"])
        events.append({
            "eid": ev["eid"],
            "source_span": ev["span"],
            "span_start": start,
            "span_end": start + len(ev["span"]),
            "role": ev["role"],
            "governed_tools": gt,
            "sentence_index": sentence_index_of_span(policy, ev["span"]),
        })

    ev_by_eid = {e["eid"]: e for e in events}

    edges = []
    for ed in case.get("edges", []):
        a, b = ev_by_eid[ed["from_eid"]], ev_by_eid[ed["to_eid"]]
        ev_spans = []
        for text in ed["evidence"]:
            idx = find_offset(policy, text)
            assert idx >= 0, f"{case['case_id']}: evidence not verbatim: {text!r}"
            ev_spans.append({"start": idx, "end": idx + len(text), "text": text})
        edges.append({
            "from_eid": ed["from_eid"], "to_eid": ed["to_eid"],
            "from_span": a["source_span"], "to_span": b["source_span"],
            "relation": ed["relation"],
            "acceptable": ed.get("acceptable", [ed["relation"]]),
            "evidence": ev_spans,
        })

    groups = []
    for g in case.get("groups", []):
        ev_spans = []
        for text in g["evidence"]:
            idx = find_offset(policy, text)
            assert idx >= 0, f"{case['case_id']}: group evidence not verbatim: {text!r}"
            ev_spans.append({"start": idx, "end": idx + len(text), "text": text})
        groups.append({
            "target_eid": g["target_eid"], "logic": g["logic"],
            "parent_eids": g["parent_eids"],
            "target_span": ev_by_eid[g["target_eid"]]["source_span"],
            "parent_spans": [ev_by_eid[p]["source_span"] for p in g["parent_eids"]],
            "evidence": ev_spans,
        })

    # pair universe: ALL unordered pairs of ALL events (incl. descriptive)
    pair_universe = []
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            a, b = events[i], events[j]
            connected = any(
                {e["from_eid"], e["to_eid"]} == {a["eid"], b["eid"]} for e in edges)
            same_sent = (a["sentence_index"] >= 0 and
                         a["sentence_index"] == b["sentence_index"])
            pair_universe.append({
                "a_eid": a["eid"], "b_eid": b["eid"],
                "a_span": a["source_span"], "b_span": b["source_span"],
                "gold": "POSITIVE" if connected else "NEGATIVE",
                "hard": bool(is_hard_negative(a, b, same_sent)),
            })

    tool_types = ({t["name"]: t["type"] for t in tools} if not renamed
                  else {rename_map[k]: v for k, v in
                        [(t["name"], t["type"]) for t in case["tools"]]})

    return {
        "case_id": case["case_id"] + ("_renamed" if renamed else ""),
        "orig_case_id": case["case_id"],
        "domain": case["domain"],
        "family": case["family"],
        "split": case["split"],
        "policy": policy,
        "tools": tools,
        "events": events,
        "edges": edges,
        "groups": groups,
        "tool_types": tool_types,
        "pair_universe": pair_universe,
        "cf_of": case.get("cf_of"),
        "mp1": case.get("cf_of") is not None or case.get("cf") is not None,
        "notes": case.get("notes", ""),
    }


def build_cf_links(cases):
    by_id = {c["case_id"]: c for c in cases}
    links = []
    for c in cases:
        cf = c.get("cf")
        if not cf:
            continue
        tgt = by_id.get(cf["cf_case_id"])
        assert tgt is not None, f"missing cf case {cf['cf_case_id']}"
        links.append({
            "original_case_id": c["case_id"],
            "cf_case_id": cf["cf_case_id"],
            "split": c["split"],
            "swap": cf["swap"],
        })
    return links


def sha256_of(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    FROZEN.mkdir(parents=True, exist_ok=True)
    cases = resolve_tools(json.loads(json.dumps(ALL_CASES)))

    orig = [build_case_record(c, renamed=False) for c in cases]
    ren = [build_case_record(c, renamed=True) for c in cases]

    # -------- sanity: totals --------------------------------------------
    n_events = sum(len(c["events"]) for c in orig)
    n_edges = sum(len(c["edges"]) for c in orig)
    n_pairs = sum(len(c["pair_universe"]) for c in orig)
    n_pos = sum(1 for c in orig for p in c["pair_universe"] if p["gold"] == "POSITIVE")
    n_hard = sum(1 for c in orig for p in c["pair_universe"]
                 if p["gold"] == "NEGATIVE" and p["hard"])
    n_easy = n_pairs - n_pos - n_hard
    by_split = {}
    for c in orig:
        by_split.setdefault(c["split"], []).append(c["case_id"])
    by_family = {}
    for c in orig:
        by_family.setdefault(c["family"], []).append(c["case_id"])

    # every eid pair unique, every case has >= 1 event
    for c in orig:
        eids = [e["eid"] for e in c["events"]]
        assert len(eids) == len(set(eids)), f"{c['case_id']}: duplicate eids"
        assert len(eids) >= 3, f"{c['case_id']}: too few events"

    # -------- write frozen files ----------------------------------------
    out = {
        "frozen_cases.json": orig,
        "frozen_cases_renamed.json": ren,
        "cf_links.json": build_cf_links(cases),
        "splits.json": {
            "calibration": by_split.get("calib", []),
            "validation": by_split.get("val", []),
            "test": by_split.get("test", []),
            "rule": ("conformal thresholds fitted ONLY on calibration split; "
                     "development decisions ONLY on validation split; test "
                     "split opened last and never used for tuning"),
        },
        "families.json": by_family,
    }
    for name, payload in out.items():
        (FROZEN / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                   encoding="utf-8")

    # component inputs for the real-frontend track (policy + tools only)
    comp = [{"case_id": c["case_id"], "orig_case_id": c["orig_case_id"],
             "split": c["split"], "policy": c["policy"], "tools": c["tools"]}
            for c in orig]
    (FROZEN / "component_inputs.json").write_text(
        json.dumps(comp, ensure_ascii=False, indent=1), encoding="utf-8")

    manifest = {
        "created": "2026-09-28",
        "created_before_any_inference": True,
        "n_cases": len(orig),
        "n_events": n_events,
        "n_edges": n_edges,
        "n_pairs": n_pairs,
        "n_positive_pairs": n_pos,
        "n_hard_negatives": n_hard,
        "n_easy_negatives": n_easy,
        "positive_rate": round(n_pos / n_pairs, 4),
        "splits": {k: len(v) for k, v in by_split.items()},
        "families": {k: len(v) for k, v in by_family.items()},
        "cf_pairs": len(out["cf_links.json"]),
        "hard_negative_rule": ("same sentence OR (condition-like, op-like) OR "
                               "(op-like, op-like)"),
        "files": {},
    }
    for f in sorted(FROZEN.glob("*.json")):
        manifest["files"][f.name] = sha256_of(f)
    (FROZEN / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({k: v for k, v in manifest.items() if k != "files"},
                     indent=2))
    print("\nFROZEN OK ->", FROZEN)


if __name__ == "__main__":
    main()
