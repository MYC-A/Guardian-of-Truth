"""F6 sealed-suite builder — LLM-FIRST EXTRACTION phase.

Freezes (BEFORE any inference; anti-leakage directive section 18):
  f6_frozen/f6_cases.json          24 policies + compact gold
  f6_frozen/f6_cf_twins.json       6 counterfactual minimal-pair twins
  f6_frozen/f6_cases_renamed.json  6 renamed variants
  f6_frozen/f6_graph_gold.json     directed gold edges per case
  f6_frozen/f6_clusters_gold.json  gold clusters (cid -> member spans)
  f6_frozen/f6_pairs_gold.json     derived mention-pair identity labels
  f6_frozen/f6_manifest.json       SHAs + conventions + composition

Gold is decisive (no AMBIGUOUS gold; AMBIGUOUS is a classifier outcome).

Run: python3 en_f6_build.py    (writes f6_frozen/, NO inference)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from en_f6_cases_m import M_CASES  # noqa: E402
from en_f6_cases_l import L_CASES  # noqa: E402
from en_f6_cases_s import S_CASES  # noqa: E402
from en_f6_cf import F6_CF_TWINS, F6_RENAMES  # noqa: E402

FROZEN = HERE / "f6_frozen"
CASES = M_CASES + L_CASES + S_CASES

SEM_TYPES = {"ACTION", "CHECK", "STATE", "RECORD", "COMMUNICATION",
             "REFERENCE_TO_EVENT", "OTHER"}
PIPE_TYPES = {"EVENT", "CHECK", "STATE_OR_FACET", "EVENT_REFERENCE",
              "ARTIFACT", "ENTITY"}


# ------------------------------------------------------------- validation
def validate(cs) -> list[str]:
    errs: list[str] = []
    seen_ids: set[str] = set()
    for c in cs:
        cid = c["case_id"]
        if cid in seen_ids:
            errs.append(f"{cid}: duplicate case_id")
        seen_ids.add(cid)
        pol = c["policy"]
        if not pol.strip().endswith("."):
            errs.append(f"{cid}: policy must end with a period")
        spans = [m[0] for m in c["mentions"]]
        for m in c["mentions"]:
            s, typ, cid_, sem = m[0], m[1], m[2], m[3]
            if s not in pol:
                errs.append(f"{cid}: span not verbatim: {s!r}")
            if typ not in PIPE_TYPES:
                errs.append(f"{cid}: bad pipeline type {typ!r}")
            if sem not in SEM_TYPES:
                errs.append(f"{cid}: bad sem type {sem!r}")
            if len(m) == 5:
                emb = m[4].get("embeds")
                if emb and emb not in pol:
                    errs.append(f"{cid}: embeds span not verbatim: {emb!r}")
                if emb and emb not in spans:
                    errs.append(f"{cid}: embeds target not a mention: {emb!r}")
            if typ == "ENTITY" and cid_ is not None:
                errs.append(f"{cid}: entity mention with cid {cid_!r}")
            if typ in ("EVENT", "CHECK", "STATE_OR_FACET") and cid_ is None:
                errs.append(f"{cid}: event-like mention without cid: {s!r}")
        dups = [s for s, n in Counter(spans).items() if n > 1]
        for d in dups:
            errs.append(f"{cid}: duplicated span: {d!r}")
        cids = {m[2] for m in c["mentions"] if m[2]}
        for e in c["normative_edges"]:
            f, t, acc, ev = e[0], e[1], e[2], e[3]
            if f not in cids or t not in cids:
                errs.append(f"{cid}: edge endpoint not in cids: {f}->{t}")
            if ev not in pol:
                errs.append(f"{cid}: edge evidence not verbatim: {ev!r}")
            if not acc:
                errs.append(f"{cid}: edge without acceptable relations")
        for p in c.get("related_pairs", []) + c.get("ambiguous_pairs", []):
            if p[0] not in cids or p[1] not in cids:
                errs.append(f"{cid}: related/ambiguous pair unknown cids {p}")
        for t in c["tools"]:
            for k in ("name", "description", "input", "output"):
                if k not in t:
                    errs.append(f"{cid}: tool missing {k}")
    return errs


def validate_twins(tw) -> list[str]:
    errs: list[str] = []
    for t in tw:
        for side in ("a", "b"):
            s = t[side]
            for f in s["focus"]:
                if f not in s["policy"]:
                    errs.append(f"{t['twin_id']}.{side}: focus not verbatim: {f!r}")
            if s["expected"] not in ("SAME_EVENT", "RELATED_BUT_DIFFERENT",
                                     "DIFFERENT_EVENT"):
                errs.append(f"{t['twin_id']}.{side}: bad expected label")
    return errs


# ----------------------------------------------------------------- pairs
def derive_pairs(c):
    """Derive mention-pair identity labels from gold structure (F5 logic,
    sem_type carried through)."""
    ms = c["mentions"]
    edge_pairs = {(e[0], e[1]) for e in c["normative_edges"]} | \
                 {(e[1], e[0]) for e in c["normative_edges"]}
    rel = {(p[0], p[1]) for p in c.get("related_pairs", [])} | \
          {(p[1], p[0]) for p in c.get("related_pairs", [])}
    amb = {(p[0], p[1]) for p in c.get("ambiguous_pairs", [])} | \
          {(p[1], p[0]) for p in c.get("ambiguous_pairs", [])}
    pairs = []
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            a, b = ms[i], ms[j]
            if not a[2] or not b[2]:
                continue
            if (a[2], b[2]) in amb:
                lab = "AMBIGUOUS"
            elif a[2] == b[2]:
                lab = "SAME_EVENT"
            elif (a[2], b[2]) in rel or (a[2], b[2]) in edge_pairs:
                lab = "RELATED_BUT_DIFFERENT"
            else:
                lab = "DIFFERENT_EVENT"
            pairs.append({"a": a[0], "a_cid": a[2], "a_sem": a[3],
                          "b": b[0], "b_cid": b[2], "b_sem": b[3],
                          "label": lab})
    return pairs


# ---------------------------------------------------------------- renames
def _ren_text(s: str, mapping: list[list[str]]) -> str:
    """Phrase-level, longest-first, case-preserving rename."""
    out = s
    for src, dst in sorted(mapping, key=lambda p: -len(p[0])):
        if src in out:
            def sub(m, dst=dst):
                w = m.group(0)
                d = dst
                if w[0].isupper() and d and not d[0].isupper():
                    d = d[0].upper() + d[1:]
                return d
            out = re.sub(r"(?<![A-Za-z])" + re.escape(src) +
                         r"(?![A-Za-z])", sub, out)
    return out


def build_rename(c, spec):
    out = dict(c)
    out["case_id"] = spec["case_id_new"]
    out["family"] = c["family"] + "_renamed"
    out["policy"] = _ren_text(c["policy"], spec["map"])
    out["mentions"] = []
    for m in c["mentions"]:
        m2 = list(m)
        m2[0] = _ren_text(m[0], spec["map"])
        if len(m) == 5:
            m2[4] = {"embeds": _ren_text(m[4]["embeds"], spec["map"])}
        out["mentions"].append(tuple(m2))
    out["normative_edges"] = [[f, t, list(acc), _ren_text(ev, spec["map"])]
                              for f, t, acc, ev in c["normative_edges"]]
    tools = []
    for t in c["tools"]:
        t2 = dict(t)
        for src, dst in spec.get("tool_map", []):
            t2["name"] = t2["name"].replace(src, dst)
            t2["description"] = _ren_text(t2["description"], [[src, dst]])
        tools.append(t2)
    out["tools"] = tools
    return out


# ------------------------------------------------------------------ main
def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()


def main() -> None:
    errs = validate(CASES) + validate_twins(F6_CF_TWINS)
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)

    renamed = [build_rename(c, F6_RENAMES[c["case_id"]])
               for c in CASES if c["case_id"] in F6_RENAMES]
    errs2 = validate(renamed)
    if errs2:
        print("RENAMED VALIDATION FAILED:")
        for e in errs2:
            print(" -", e)
        raise SystemExit(1)

    FROZEN.mkdir(parents=True, exist_ok=True)
    n_mentions = sum(len(c["mentions"]) for c in CASES)
    n_events = sum(len({m[2] for m in c["mentions"] if m[2]}) for c in CASES)
    n_edges = sum(len(c["normative_edges"]) for c in CASES)
    all_pairs = {c["case_id"]: derive_pairs(c) for c in CASES}
    n_pairs = sum(len(v) for v in all_pairs.values())
    lab_dist = Counter(p["label"] for v in all_pairs.values() for p in v)

    out_cases = {"cases": [
        {k: (v if k != "mentions" else [list(m) for m in v])
         for k, v in c.items()} for c in CASES]}
    (FROZEN / "f6_cases.json").write_text(
        json.dumps(out_cases, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (FROZEN / "f6_cf_twins.json").write_text(
        json.dumps({"twins": F6_CF_TWINS}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    out_ren = {"cases": [
        {k: (v if k != "mentions" else [list(m) for m in v])
         for k, v in c.items()} for c in renamed]}
    (FROZEN / "f6_cases_renamed.json").write_text(
        json.dumps(out_ren, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (FROZEN / "f6_graph_gold.json").write_text(json.dumps(
        {c["case_id"]: [{"from": e[0], "to": e[1], "acceptable": e[2],
                         "evidence": e[3]} for e in c["normative_edges"]]
         for c in CASES}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (FROZEN / "f6_clusters_gold.json").write_text(json.dumps(
        {c["case_id"]: {cid: [m[0] for m in c["mentions"] if m[2] == cid]
                        for cid in {m[2] for m in c["mentions"] if m[2]}}
         for c in CASES}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (FROZEN / "f6_pairs_gold.json").write_text(
        json.dumps(all_pairs, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    manifest = {
        "name": "LEVEL_F6",
        "phase": "LLM-FIRST EXTRACTION",
        "frozen_at": "2026-09-29",
        "branch": "codex/llm-first-extraction-f6-20260929",
        "base": "codex/event-normalization-f5-20260929 @ 27a21bc5",
        "sha256": {
            "cases": _sha(out_cases),
            "cf_twins": _sha({"twins": F6_CF_TWINS}),
            "renamed": _sha(out_ren),
        },
        "n_cases": len(CASES),
        "n_mentions": n_mentions,
        "n_canonical_events": n_events,
        "n_gold_edges": n_edges,
        "n_pairs": n_pairs,
        "pair_label_dist": dict(lab_dist),
        "n_cf_twins": len(F6_CF_TWINS),
        "n_renamed_cases": len(renamed),
        "groups": {
            "m_mention_form": [c["case_id"] for c in M_CASES],
            "l_licensing": [c["case_id"] for c in L_CASES],
            "s_reference_identity": [c["case_id"] for c in S_CASES],
        },
        "families": sorted({c["family"] for c in CASES}),
        "conventions": [
            "passive voice facet shares the action cid (F5 kept)",
            "adjectival/result/completion/outcome states: OWN cid, RELATED",
            "action / check-of-action / recording: distinct cids (F5 kept)",
            "repetition ('again'/'repeat'/ordinal second): separate cid (F5 kept)",
            "NEW F6: nested CHECK/RECORD/COMMUNICATION clauses keep BOTH the "
            "outer mention and the embedded clause mention (embeds field)",
            "NEW F6 (convention change vs F5): recording clauses ('X is "
            "logged/filed/signed/archived by Y') are RECORD events with "
            "their own cid",
            "NEW F6: outcome/failure/cancellation/skipping states get their "
            "own cid (RELATED), instead of sharing the referenced event cid",
            "synonym-voice facets ('Broadcast'/'was transmitted') share cid",
            "reported/quoted action shares cid with the direct imperative",
            "prescribed rule vs reported past occurrence: DIFFERENT events; "
            "vs habitual passive restatement: SAME event",
            "temporal PPs with bare deverbal heads are not annotated; plain "
            "temporal NPs are ENTITY mentions",
            "entity NPs listed once per distinct surface form",
            "negated imperatives annotated without 'Do not'",
            "OR-coordinated alternatives: no edge between them (F5 kept)",
            "coordinated state gates: one edge per gating state",
        ],
        "sem_taxonomy": sorted(SEM_TYPES),
        "pipeline_types": sorted(PIPE_TYPES),
        "rule": "F6 is SEALED: no inference before this freeze; after the "
                "first F6 run no fixes measured on F6 (new ideas go to F7).",
    }
    (FROZEN / "f6_manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    print(f"[f6] {len(CASES)} cases valid; {n_mentions} mentions; "
          f"{n_events} canonical events; {n_edges} gold edges; "
          f"{n_pairs} pairs {dict(lab_dist)}; "
          f"{len(F6_CF_TWINS)} CF twins; {len(renamed)} renamed cases")
    print("[f6] manifest sha256(cases):", manifest["sha256"]["cases"][:16])


if __name__ == "__main__":
    main()
