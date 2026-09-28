"""EVENT_CANON_v1 - freeze the Level D dataset BEFORE any inference.

Validates authoring, resolves char offsets, derives pair gold, builds the
renamed suite, writes manifest. Run once; the frozen/ directory is then
committed before any canonicalization model sees the data.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from ec_cases_a import CASES_A
from ec_cases_b import CASES_B
from ec_cases_c import CASES_C

ALL_CASES = CASES_A + CASES_B + CASES_C
SPLITS = ("dev", "calib", "val", "test")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentences(policy: str):
    return [s.strip() for s in _SENT_SPLIT.split(policy) if s.strip()]


def sentence_index_of(policy: str, start: int) -> int:
    pos, k = 0, 0
    for s in _SENT_SPLIT.split(policy):
        if pos <= start < pos + len(s):
            return k
        pos += len(s) + 1
        k += 1
    return -1


def resolve_span(policy: str, span: str, start_hint):
    """Return (start, end) for a mention span. start_hint: None|int|AUTO1..N."""
    occurrences = [m.start() for m in re.finditer(re.escape(span), policy)]
    if not occurrences:
        raise ValueError(f"span not found: {span!r}")
    if start_hint is None:
        if len(occurrences) != 1:
            raise ValueError(f"span not unique ({len(occurrences)}x): {span!r}")
        return occurrences[0], occurrences[0] + len(span)
    if isinstance(start_hint, str) and start_hint.startswith("AUTO"):
        n = int(start_hint[4:])
        if len(occurrences) < n:
            raise ValueError(f"span occurrence {n} missing: {span!r}")
        return occurrences[n - 1], occurrences[n - 1] + len(span)
    if isinstance(start_hint, int):
        if policy[start_hint:start_hint + len(span)] != span:
            raise ValueError(f"explicit start mismatch: {span!r}@{start_hint}")
        return start_hint, start_hint + len(span)
    raise ValueError(f"bad start hint {start_hint!r}")


def validate_and_build():
    out = []
    seen_ids = set()
    for c in ALL_CASES:
        cid_ = c["case_id"]
        if cid_ in seen_ids:
            raise ValueError(f"duplicate case_id {cid_}")
        seen_ids.add(cid_)
        policy = c["policy"]
        cids = {e["cid"] for e in c["canonical_events"]}
        tool_names = {t["name"] for t in c["tools"]}
        mids = set()
        mentions = []
        for m in c["mentions"]:
            if m["mid"] in mids:
                raise ValueError(f"{cid_}: duplicate mid {m['mid']}")
            mids.add(m["mid"])
            if m["cid"] not in cids:
                raise ValueError(f"{cid_}: mention {m['mid']} unknown cid {m['cid']}")
            st, en = resolve_span(policy, m["span"], m.get("start"))
            mentions.append({
                "mid": m["mid"], "span": m["span"], "start": st, "end": en,
                "cid": m["cid"],
                "sentence_index": sentence_index_of(policy, st),
            })
        # canonical events must have >=1 mention, valid tools, role
        by_cid = {}
        for m in mentions:
            by_cid.setdefault(m["cid"], []).append(m["mid"])
        events = []
        for e in c["canonical_events"]:
            if e["cid"] not in by_cid:
                raise ValueError(f"{cid_}: canonical {e['cid']} has no mentions")
            for t in e["governed_tools"]:
                if t not in tool_names:
                    raise ValueError(f"{cid_}: {e['cid']} unknown tool {t}")
            if e["role"] not in {"OPERATION_EFFECT", "PRECONDITION_CHECK",
                                 "STATE_OBSERVATION", "COMMUNICATION", "OTHER"}:
                raise ValueError(f"{cid_}: bad role {e['role']}")
            events.append({k: e[k] for k in ("cid", "predicate", "role", "governed_tools")})
        # related groups
        related = set()
        for a, b in c["related_groups"]:
            if a not in cids or b not in cids:
                raise ValueError(f"{cid_}: related group unknown cid {a}/{b}")
            related.add(frozenset((a, b)))
        # ambiguous pairs
        amb = []
        for a, b in c["ambiguous_pairs"]:
            if a not in mids or b not in mids:
                raise ValueError(f"{cid_}: ambiguous pair unknown mid {a}/{b}")
            amb.append([a, b])
        # edges
        edges = []
        for e in c["edges"]:
            if e["from_cid"] not in cids or e["to_cid"] not in cids:
                raise ValueError(f"{cid_}: edge unknown cid")
            evs = []
            for ev in e["evidence"]:
                occ = [m.start() for m in re.finditer(re.escape(ev["text"]), policy)]
                if len(occ) != 1:
                    raise ValueError(f"{cid_}: evidence not unique ({len(occ)}x): {ev['text']!r}")
                evs.append({"start": occ[0], "end": occ[0] + len(ev["text"]),
                            "text": ev["text"]})
            edges.append({"from_cid": e["from_cid"], "to_cid": e["to_cid"],
                          "relation": e["relation"], "acceptable": e["acceptable"],
                          "evidence": evs})
        out.append({
            "case_id": cid_, "domain": c["domain"], "family": c["family"],
            "split": c["split"], "policy": policy, "tools": c["tools"],
            "mentions": mentions, "canonical_events": events,
            "related_pairs": [sorted(p) for p in related],
            "ambiguous_pairs": amb, "edges": edges, "cf_of": c["cf_of"],
            "notes": c.get("notes", ""),
        })
    # cf links symmetric, twin exists, same split
    for c in out:
        if c["cf_of"]:
            twin = next((t for t in out if t["case_id"] == c["cf_of"]), None)
            if twin is None:
                raise ValueError(f"{c['case_id']}: cf twin missing")
            if twin["cf_of"] != c["case_id"]:
                raise ValueError(f"{c['case_id']}: asymmetric cf link")
    return out


def derive_pairs(case):
    """All unordered mention pairs with gold labels."""
    related = {frozenset(p) for p in case["related_pairs"]}
    amb = {frozenset(p) for p in case["ambiguous_pairs"]}
    mids = case["mentions"]
    pairs = []
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            a, b = mids[i], mids[j]
            key = frozenset((a["mid"], b["mid"]))
            if key in amb:
                label = "AMBIGUOUS"
            elif a["cid"] == b["cid"]:
                label = "SAME_EVENT"
            elif frozenset((a["cid"], b["cid"])) in related:
                label = "RELATED_BUT_DIFFERENT"
            else:
                label = "DIFFERENT"
            pairs.append({
                "a": a["mid"], "b": b["mid"], "label": label,
                "same_sentence": a["sentence_index"] == b["sentence_index"],
                "cid_a": a["cid"], "cid_b": b["cid"],
            })
    return pairs


def renamed_suite(cases):
    out = []
    for c in cases:
        name_map = {}
        tools = []
        for i, t in enumerate(c["tools"]):
            new_name = f"tool_{i + 1:02d}"
            name_map[t["name"]] = new_name
            tools.append({**t, "name": new_name})
        events = [{**e, "governed_tools": [name_map.get(x, x) for x in e["governed_tools"]]}
                  for e in c["canonical_events"]]
        out.append({**c, "tools": tools, "canonical_events": events})
    return out


def main():
    cases = validate_and_build()
    frozen = HERE / "frozen"
    frozen.mkdir(exist_ok=True)

    pairs_gold = {c["case_id"]: derive_pairs(c) for c in cases}
    (frozen / "frozen_cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    (frozen / "frozen_cases_renamed.json").write_text(
        json.dumps(renamed_suite(cases), ensure_ascii=False, indent=1), encoding="utf-8")
    (frozen / "pairs_gold.json").write_text(
        json.dumps(pairs_gold, ensure_ascii=False, indent=1), encoding="utf-8")
    splits = {s: [c["case_id"] for c in cases if c["split"] == s] for s in SPLITS}
    (frozen / "splits.json").write_text(
        json.dumps(splits, ensure_ascii=False, indent=1), encoding="utf-8")

    # manifest
    h = hashlib.sha256()
    stats = {"cases": len(cases), "splits": {s: len(v) for s, v in splits.items()}}
    for key, payload in (("frozen_cases.json", cases),
                         ("frozen_cases_renamed.json", renamed_suite(cases)),
                         ("pairs_gold.json", pairs_gold)):
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        stats[f"sha256::{key}"] = hashlib.sha256(blob).hexdigest()
    n_mentions = sum(len(c["mentions"]) for c in cases)
    n_events = sum(len(c["canonical_events"]) for c in cases)
    n_edges = sum(len(c["edges"]) for c in cases)
    label_counts = {}
    for cid_, pairs in pairs_gold.items():
        for p in pairs:
            label_counts[p["label"]] = label_counts.get(p["label"], 0) + 1
    n_multi = sum(1 for c in cases if len({m["cid"] for m in c["mentions"]}) <
                  len({m["mid"] for m in c["mentions"]}))
    stats.update({
        "mentions": n_mentions, "canonical_events": n_events, "edges": n_edges,
        "pairs_total": sum(len(v) for v in pairs_gold.values()),
        "pair_labels": label_counts,
        "cases_with_coref_links": sum(
            1 for c in cases
            if any(p["label"] == "SAME_EVENT" for p in pairs_gold[c["case_id"]]
                   if pairs_gold[c["case_id"]][0]["a"] != p["a"] or True)
            and any(len([m for m in c["mentions"] if m["cid"] == mm["cid"]]) > 1
                    for mm in c["mentions"])),
        "cf_pairs": sorted({tuple(sorted((c["case_id"], c["cf_of"])))
                            for c in cases if c["cf_of"]}),
        "domains": sorted({c["domain"] for c in cases}),
        "frozen_at": "2026-09-28",
    })
    (frozen / "manifest.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1)[:2000])
    print("FROZEN OK")


if __name__ == "__main__":
    main()
