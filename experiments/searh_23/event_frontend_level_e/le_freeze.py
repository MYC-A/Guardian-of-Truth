"""Freeze new Level E eventness, identity, and downstream policy data.

No model calls. Separate inference inputs from sealed gold. Old Level D
development data are excluded from this directory and the new domains do not
overlap EVENT_CANON_v1's frozen domain list.
"""
from __future__ import annotations

import hashlib
import json
import re
from itertools import combinations
from pathlib import Path

from level_e_cases import CASES, PROBES

HERE = Path(__file__).parent
FROZEN = HERE / "frozen"
EC_MANIFEST = HERE.parent / "event_canon_v1" / "frozen" / "manifest.json"


def unique_span(policy: str, span: str) -> tuple[int, int]:
    starts = [m.start() for m in re.finditer(re.escape(span), policy)]
    if len(starts) != 1:
        raise ValueError(f"span must occur exactly once ({len(starts)}): {span!r}")
    return starts[0], starts[0] + len(span)


def sent_index(policy: str, start: int) -> int:
    segments = list(re.finditer(r"[^.!?]+[.!?]?", policy))
    return next(i for i, m in enumerate(segments) if m.start() <= start < m.end())


def containing_sentence(policy: str, start: int) -> str:
    segments = list(re.finditer(r"[^.!?]+[.!?]?", policy))
    return next(m.group().strip() for m in segments if m.start() <= start < m.end())


def build_cases() -> list[dict]:
    old_domains = set(json.loads(EC_MANIFEST.read_text(encoding="utf-8"))["domains"])
    cases = []
    seen = set()
    for c in CASES:
        if c["case_id"] in seen or c["domain"] in old_domains:
            raise ValueError("duplicate ID or prior-domain overlap: " + c["case_id"])
        seen.add(c["case_id"])
        policy = c["policy"]
        mentions = []
        for i, (span, cid) in enumerate(c["mentions"]):
            start, end = unique_span(policy, span)
            mentions.append({"mid": f"m{i+1}", "span": span, "start": start,
                             "end": end, "cid": cid, "sentence_index": sent_index(policy, start)})
        canonical = [{"cid": cid, "predicate": pred, "role": role,
                      "governed_tools": [tool]} for cid, pred, role, tool in c["events"]]
        event_ids = {x["cid"] for x in canonical}
        if {m["cid"] for m in mentions} != event_ids:
            raise ValueError("event without mention: " + c["case_id"])
        edges = []
        for a, b, ev in c["edges"]:
            if a not in event_ids or b not in event_ids:
                raise ValueError("unknown edge endpoint")
            st, en = unique_span(policy, ev)
            edges.append({"from_cid": a, "to_cid": b, "relation": "PRECONDITION",
                          "acceptable": ["PRECONDITION", "ORDER_BEFORE"],
                          "evidence": [{"start": st, "end": en, "text": ev}]})
        related = {frozenset(x) for x in c.get("related_pairs", [])}
        related.update(frozenset((e["from_cid"], e["to_cid"])) for e in edges)
        cases.append({"case_id": c["case_id"], "domain": c["domain"], "family": c["family"],
                      "split": "sealed_test", "policy": policy, "tools": c["tools"],
                      "mentions": mentions, "canonical_events": canonical,
                      "related_pairs": [sorted(x) for x in sorted(related, key=lambda p: tuple(sorted(p)))],
                      "ambiguous_pairs": [], "edges": edges, "cf_of": None, "notes": "Level E new family"})
    return cases


def pair_rows(cases: list[dict]) -> tuple[list[dict], dict]:
    inputs, gold = [], {}
    for case in cases:
        related = {frozenset(x) for x in case["related_pairs"]}
        for a, b in combinations(case["mentions"], 2):
            pid = f"{case['case_id']}::{a['mid']}::{b['mid']}"
            label = "SAME_EVENT" if a["cid"] == b["cid"] else (
                "RELATED_BUT_DIFFERENT" if frozenset((a["cid"], b["cid"])) in related
                else "DIFFERENT")
            inputs.append({"id": pid, "case_id": case["case_id"], "family": case["family"],
                           "policy": case["policy"],
                           "a": {k: a[k] for k in ("span", "start", "end")},
                           "b": {k: b[k] for k in ("span", "start", "end")},
                           "variant": "clean"})
            gold[pid] = label
    return inputs, gold


NOISE = [
    ("e_observatory", "Calibrate mirror 7", "the mirror has been calibrated", "only after the mirror has been calibrated", "SAME_EVENT"),
    ("e_seedbank", "Dry seed tray Q", "the tray is dried", "only after the tray is dried", "SAME_EVENT"),
    ("e_aquarium", "Test tank water", "the water test is complete", "only after the water test is complete", "SAME_EVENT"),
    ("e_ceramics", "Inspect vessel A's glaze", "inspection", "only after inspection", "SAME_EVENT"),
    ("e_drone", "Approve flight 17", "the flight approval is recorded", "only after the flight approval is recorded", "SAME_EVENT"),
    ("e_theater", "Check the rigging", "the check is complete", "only after the check is complete", "SAME_EVENT"),
    ("e_orchard", "Verify the spray record on Tuesday", "verification", "but only after verification", "SAME_EVENT"),
    ("e_fleet", "Check the charger log", "the log check is complete", "only after the log check is complete", "SAME_EVENT"),
    ("e_archive", "Approve the scan for publication", "approval", "only after approval", "SAME_EVENT"),
    ("e_coldchain", "Inspect its seal", "the seal inspection is complete", "only after the seal inspection is complete", "SAME_EVENT"),
]


def noisy_rows(cases: list[dict]) -> tuple[list[dict], dict]:
    by_id = {c["case_id"]: c for c in cases}
    rows, labels = [], {}
    for cid, a, clean, noisy, label in NOISE:
        case = by_id[cid]
        ast, aen = unique_span(case["policy"], a)
        for variant, b in (("clean", clean), ("noisy", noisy)):
            bst, ben = unique_span(case["policy"], b)
            pid = f"{cid}::noise::{variant}"
            rows.append({"id": pid, "case_id": cid, "policy": case["policy"],
                         "a": {"span": a, "start": ast, "end": aen},
                         "b": {"span": b, "start": bst, "end": ben},
                         "variant": variant, "noise_family": "boundary_expansion"})
            labels[pid] = label
    return rows, labels


def eventness_rows(cases: list[dict]) -> tuple[list[dict], dict]:
    inputs, gold = [], {}
    for c in cases:
        authored = next(x for x in CASES if x["case_id"] == c["case_id"])
        for i, m in enumerate(c["mentions"]):
            pid = f"{c['case_id']}::gold::{i}"
            label = authored.get("eventness_overrides", {}).get(m["span"])
            if label is None:
                label = "EVENT_REFERENCE" if i and any(x["cid"] == m["cid"] for x in c["mentions"][:i]) else "EVENT"
            inputs.append({"id": pid, "sentence": containing_sentence(c["policy"], m["start"]), "span": m["span"],
                           "start": m["start"], "end": m["end"], "source": "policy_mention"})
            gold[pid] = label
        for i, (span, label) in enumerate(authored["probes"]):
            st = c["policy"].find(span)
            if st < 0:
                raise ValueError(f"missing probe {c['case_id']}: {span!r}")
            en = st + len(span)
            if any(m["start"] == st and m["end"] == en for m in c["mentions"]):
                continue  # same exact mention already counted in E1
            pid = f"{c['case_id']}::probe::{i}"
            inputs.append({"id": pid, "sentence": containing_sentence(c["policy"], st), "span": span,
                           "start": st, "end": en, "source": "policy_probe"})
            gold[pid] = label
    for i, (sentence, span, label) in enumerate(PROBES):
        st, en = unique_span(sentence, span)
        pid = f"standalone::{i}"
        inputs.append({"id": pid, "sentence": sentence, "span": span,
                       "start": st, "end": en, "source": "standalone"})
        gold[pid] = label
    return inputs, gold


def write_immutable(path: Path, payload: object) -> str:
    value = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != value:
        raise ValueError("frozen file changed: " + str(path))
    path.write_text(value, encoding="utf-8")
    return hashlib.sha256(value.encode()).hexdigest()


def main():
    cases = build_cases()
    e1, e1_gold = eventness_rows(cases)
    e2, e2_gold = pair_rows(cases)
    noisy, noisy_gold = noisy_rows(cases)
    FROZEN.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, value in (("frozen_cases.json", cases), ("frozen_cases_renamed.json", renamed(cases)),
                        ("eventness_inputs.json", e1), ("eventness_gold.json", e1_gold),
                        ("identity_inputs.json", e2 + noisy), ("identity_gold.json", {**e2_gold, **noisy_gold})):
        manifest[name] = write_immutable(FROZEN / name, value)
    manifest.update({"cases": len(cases), "eventness": len(e1), "identity": len(e2) + len(noisy),
                     "noise_pairs": len(noisy), "split": "sealed_test_all", "development": "EVENT_CANON_v1 dev/calib/val only"})
    write_immutable(FROZEN / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


def renamed(cases):
    out = []
    for c in cases:
        x = json.loads(json.dumps(c))
        mapping = {t["name"]: f"tool_{i+1:02d}" for i, t in enumerate(x["tools"])}
        for t in x["tools"]:
            t["name"] = mapping[t["name"]]
        for e in x["canonical_events"]:
            e["governed_tools"] = [mapping[n] for n in e["governed_tools"]]
        out.append(x)
    return out


if __name__ == "__main__":
    main()
