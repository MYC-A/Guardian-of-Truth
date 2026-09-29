"""H.1 / H.2 as ablation arms — clause-mate pair discipline (replay, zero LLM).

H.1 (direction on non-canonical connectives) and H.2 (multi-clause
bridging) share one mechanism: SEGMENT the relation_text into clauses;
endpoint anchors must be CLAUSE-MATES (same minimal clause, or
main+subordinate clause directly linked by the gating connective);
direction comes from the clause that CONTAINS the gating connective.

Implemented as a POST-JUDGE gate over saved W1_DOWN outputs (judge
responses are in the pair logs) — v10 baseline + H.1/H.2 arms are pure
replays, zero new LLM calls.

Arms:
  v10          - saved pipeline decisions (baseline replay)
  v10 + H12    - clause-mate gate replaces NOTHING in v10 (v10 has no
                 clause segmentation); H12 REVIVES judge-YES pairs whose
                 anchors are clause-mates even when v10's v9a
                 same-sentence gate or coordination gate killed them,
                 and KILLS judge-YES pairs whose anchors live in
                 different non-adjacent clauses; direction override from
                 the connective INSIDE the pair's clause segment.
  v10 + H12x   - H12 applied ONLY as additional killer (no revivals) -
                 isolates the precision effect.

Run: python en_h12_replay.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
W1 = HERE.parent / "step1_working_v1"
sys.path.insert(0, str(W1))

from en_common import load_gold, node_label  # noqa: E402

OUTD = HERE / "outputs" / "ablations"
OUTD.mkdir(parents=True, exist_ok=True)

# clause boundaries: connectives + commas + semicolons + relative pronouns
CLAUSE_SPLIT = re.compile(
    r",|;|\b(?:and|or|but|so|then|while|whereas|although|though|"
    r"however|therefore|meanwhile|furthermore|moreover|"
    r"only\s+if|only\s+when|only\s+after|only\s+while|"
    r"if|when|unless|until|after|before|once|provided|"
    r"in\s+which\s+case|that|which|who)\b", re.I)
GATING_CONN = re.compile(
    r"\b(only\s+after|only\s+if|only\s+when|only\s+while|after|before|"
    r"if|when|unless|until|while|once|provided|in\s+which\s+case)\b",
    re.I)


def clause_segments(rel_text: str) -> list[tuple[int, int]]:
    """Minimal clause segments of a relation_text (char offsets)."""
    bounds = [0]
    for m in CLAUSE_SPLIT.finditer(rel_text):
        bounds.append(m.start())
        bounds.append(m.end())
    bounds.append(len(rel_text))
    segs = []
    for i in range(0, len(bounds) - 1, 2):
        a, b = bounds[i], bounds[i + 1]
        if rel_text[a:b].strip():
            segs.append((a, b))
    return segs or [(0, len(rel_text))]


def anchors_clause_mate(rel_text: str, a_anchor: str, b_anchor: str):
    """(is_mate, a_seg, b_seg). Anchors are clause-mates if they fall in
    the same clause segment, OR in segments directly joined by a gating
    connective at their shared boundary."""
    if not rel_text or not a_anchor or not b_anchor:
        return None, None, None
    pa, pb = rel_text.find(a_anchor), rel_text.find(b_anchor)
    if pa < 0 or pb < 0:
        return None, None, None
    segs = clause_segments(rel_text)
    sa = next((i for i, (x, y) in enumerate(segs)
               if x <= pa < y), None)
    sb = next((i for i, (x, y) in enumerate(segs)
               if x <= pb < y), None)
    if sa is None or sb is None:
        return None, None, None
    if sa == sb:
        return True, sa, sb
    # adjacent segments joined by gating connective between them
    lo, hi = min(sa, sb), max(sa, sb)
    if hi - lo == 1:
        between = rel_text[segs[lo][1]:segs[hi][0]]
        if GATING_CONN.search(between) or between.strip() in ("", ","):
            return True, sa, sb
    return False, sa, sb


def gold_edge_set(case):
    return {(e["from_cid"], e["to_cid"]): set(e["acceptable"])
            for e in case["normative_edges"]}


def replay_with_h12(case, data, policy, mode="h12"):
    """Re-derive licensed edges with the clause-mate gate.

    mode: 'v10' (baseline replay), 'h12' (kill + revive),
    'h12x' (kill only).
    Anchors: licensed pairs -> edge detail verify dict (exact);
    gate-killed pairs -> judge q1/q2 quotes located in the policy,
    relation_text approximated by the minimal covering span between
    them (documented approximation)."""
    nodes = {n["node_id"]: n for n in data.get("nodes", [])}
    edge_detail = {(e["u"], e["v"]): (e.get("detail") or {}).get(
        "verify") or {} for e in data.get("edges", [])}
    edges = []
    killed_by_h12, revived_by_h12 = [], []

    def anchors_of(rec, judge):
        """(rel_text, a_anchor, b_anchor) for a judge-passed pair."""
        v = edge_detail.get((rec.get("u"), rec.get("v"))) or {}
        if v.get("relation_text"):
            return v["relation_text"], v.get("a_anchor"), \
                v.get("b_anchor")
        q1 = judge.get("q1_where_is_a")
        q2 = judge.get("q2_where_is_b")
        if not q1 or not q2 or q1 == "NONE" or q2 == "NONE":
            return "", None, None
        i1 = policy.find(q1)
        i2 = policy.find(q2)
        if i1 < 0 or i2 < 0:
            return "", None, None
        lo, hi = min(i1, i2), max(i1, i2) + (
            len(q1) if i1 < i2 else len(q2))
        return policy[lo:hi], q1, q2

    for rec in data.get("pairs", []):
        stage = rec.get("stage")
        if stage in ("ce_band",):
            continue
        judge = rec.get("judge") or {}
        note = rec.get("judge_note") or ""
        if stage != "licensed" and note in (
                "verifier_q3_no", "verifier_q1q2_not_in_evidence",
                "semantic_link_routing"):
            continue  # judge itself said no
        if stage != "licensed" and note not in (
                "no_trigger_connective", "object_containment_gate",
                "cross_sentence_gate", "coordination_gate"):
            continue  # verification rejects stay dead
        # this pair passed the judge (licensed or gate-killed)
        if stage == "licensed":
            if mode == "v10":
                edges.append(rec)
                continue
            rel_t, aa, bb = anchors_of(rec, judge)
            mate, _, _ = anchors_clause_mate(rel_t, aa or "", bb or "")
            if mate is False:
                killed_by_h12.append((rec, "h12_kill_licensed"))
                continue
            edges.append(rec)
        else:
            if mode == "h12x":
                killed_by_h12.append((rec, f"stays_{note}"))
                continue
            if note in ("cross_sentence_gate", "coordination_gate"):
                rel_t, aa, bb = anchors_of(rec, judge)
                mate, _, _ = anchors_clause_mate(rel_t, aa or "", bb or "")
                if mate is True:
                    edges.append(rec)
                    revived_by_h12.append((rec, note))
                else:
                    killed_by_h12.append((rec, note))
            else:
                killed_by_h12.append((rec, note))
    return edges, killed_by_h12, revived_by_h12


def score_edges(case, recs, nodes):
    gold = gold_edge_set(case)
    hits, extra, wrong_dir, dup = set(), 0, 0, 0
    for rec in recs:
        u, v = nodes.get(rec.get("u")), nodes.get(rec.get("v"))
        if u is None or v is None:
            extra += 1
            continue
        lu, lv = node_label(case, u), node_label(case, v)
        d = rec.get("direction")
        if d is None:
            q4 = (rec.get("judge") or {}).get("q4_direction")
            d = q4 if q4 in ("A_TO_B", "B_TO_A") else "UNKNOWN"
        if d == "B_TO_A":
            la, lb = lv, lu
        elif d == "A_TO_B":
            la, lb = lu, lv
        else:
            extra += 1
            continue
        if la in (None, "JUNK", "MIXED", "NON_EVENT") or \
                lb in (None, "JUNK", "MIXED", "NON_EVENT"):
            extra += 1
            continue
        if (la, lb) in gold:
            if (la, lb) in hits:
                dup += 1
            else:
                hits.add((la, lb))
        elif (lb, la) in gold:
            wrong_dir += 1
        else:
            extra += 1
    g = len(gold)
    P = len(hits) / max(1, len(hits) + extra + wrong_dir + dup)
    R = len(hits) / max(1, g)
    return {"correct": len(hits), "extra": extra, "wrong_dir": wrong_dir,
            "dup": dup, "gold": g, "P": round(P, 3), "R": round(R, 3),
            "exact": len(hits) == g and extra + wrong_dir + dup == 0}


def main():
    out = {}
    for suite, arm_dir in (("main", "W1_DOWN10_LLM_SG"),
                           ("f2", "W1_DOWN10_LLM_SG"),
                           ("f4", "W1_DOWN10_LLM_SG"),
                           ("f3", "W1_DOWN8_LLM_SG")):
        gold = load_gold(suite)
        modes = ("v10", "h12", "h12x")
        totals = {m: Counter() for m in modes}
        notes = {m: Counter() for m in modes}
        per_case = {}
        for cid_, case in gold.items():
            p = W1 / "outputs" / arm_dir / f"{cid_}.json"
            if not p.exists():
                continue
            data = json.loads(p.read_text())
            nodes = {n["node_id"]: n for n in data.get("nodes", [])}
            row = {}
            for mode in modes:
                recs, killed, revived = replay_with_h12(
                    case, data, case["policy"], mode)
                sc = score_edges(case, recs, nodes)
                row[mode] = sc
                totals[mode]["correct"] += sc["correct"]
                totals[mode]["extra"] += sc["extra"]
                totals[mode]["wrong_dir"] += sc["wrong_dir"]
                totals[mode]["dup"] += sc["dup"]
                totals[mode]["gold"] += sc["gold"]
                for rec, why in killed:
                    notes[mode][why] += 1
                for rec, why in revived:
                    notes[mode][f"revived:{why}"] += 1
            per_case[cid_] = row
        for m in modes:
            c = totals[m]
            c["P"] = round(c["correct"] /
                           max(1, c["correct"] + c["extra"] +
                               c["wrong_dir"] + c["dup"]), 3)
            c["R"] = round(c["correct"] / max(1, c["gold"]), 3)
        out[suite] = {"totals": {m: dict(totals[m]) for m in modes},
                      "notes": {m: dict(notes[m]) for m in modes},
                      "per_case": per_case}
        print(f"[{suite}] v10 P={totals['v10']['P']} "
              f"R={totals['v10']['R']} | h12 P={totals['h12']['P']} "
              f"R={totals['h12']['R']} | h12x P={totals['h12x']['P']} "
              f"R={totals['h12x']['R']}")
        print(f"        notes h12: {dict(notes['h12'])}")
    (OUTD / "h12_replay.json").write_text(json.dumps(out, indent=1))
    print("saved ->", OUTD / "h12_replay.json")


if __name__ == "__main__":
    main()
