"""F6 ARM E — two independent LLM extractors: agreement analysis.

mistral (ARM A) vs codestral (ARM A) on the same F6 policies, run
independently (neither saw the other's answers).

Measured (directive section 9):
  - mention agreement (span overlap >=0.3 IoU one-to-one);
  - type agreement on matched mentions;
  - missing events (gold event mentions covered by one extractor only);
  - source-span disagreement on matched mentions (IoU distribution);
  - disagreement as an uncertainty signal (directive section 11 input):
    mention-level correctness of agreed vs disagreed mentions.

NOT a majority vote: disagreement is recorded as a signal only.

Run: python3 en_f6_agree.py   (deterministic, zero LLM)
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
RAW = HERE / "outputs" / "raw"
OUT = HERE / "outputs" / "score"
OUT.mkdir(parents=True, exist_ok=True)


def load_cases():
    return json.loads((IE / "frozen" / "level_f6_cases.json")
                      .read_text(encoding="utf-8"))


def load_mentions(model_key, cid):
    f = RAW / model_key / "A" / f"{cid}.json"
    if not f.exists():
        return []
    d = json.loads(f.read_text(encoding="utf-8"))
    return [m for m in d["mentions"] if m.get("grounded")]


def iou(a, b):
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    if inter == 0:
        return 0.0
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / max(1, union)


def gold_label_for(case, m):
    best, blab = 0.0, None
    for g in case["mentions"]:
        if not g.get("cid"):
            continue
        inter = max(0, min(m["end"], g["end"]) - max(m["start"], g["start"]))
        if inter > best:
            best, blab = inter, g["cid"]
    if blab is None:
        for g in case["mentions"]:
            if max(0, min(m["end"], g["end"]) -
                   max(m["start"], g["start"])) > 0:
                return "ENTITY_ONLY"
        return "JUNK"
    return blab


def main():
    rows = []
    tot = Counter()
    ious = []
    for case in load_cases():
        cid = case["case_id"]
        A = load_mentions("mistral", cid)
        B = load_mentions("codestral", cid)
        # greedy one-to-one matching at IoU >= 0.3
        cand = sorted(((iou(a, b), i, j) for i, a in enumerate(A)
                       for j, b in enumerate(B)), reverse=True)
        usedA, usedB, matches = set(), set(), []
        for v, i, j in cand:
            if v < 0.3:
                break
            if i in usedA or j in usedB:
                continue
            usedA.add(i)
            usedB.add(j)
            matches.append((i, j, v))
            ious.append(round(v, 2))
        onlyA = [a for i, a in enumerate(A) if i not in usedA]
        onlyB = [b for j, b in enumerate(B) if j not in usedB]
        type_agree = sum(1 for i, j, _ in matches
                         if A[i].get("type") == B[j].get("type"))
        # uncertainty signal value: gold-event overlap of agreed mentions
        agreed_ok = sum(1 for i, j, _ in matches
                        if gold_label_for(case, A[i]) not in
                        ("JUNK", "ENTITY_ONLY"))
        disagreed_ok = sum(1 for a in onlyA
                           if gold_label_for(case, a) not in
                           ("JUNK", "ENTITY_ONLY")) + \
                       sum(1 for b in onlyB
                           if gold_label_for(case, b) not in
                           ("JUNK", "ENTITY_ONLY"))
        # missing events: gold event mentions covered by exactly one side
        gm = [m for m in case["mentions"] if m.get("cid")]
        miss_m = [g for g in gm
                  if not any(iou({"start": a["start"], "end": a["end"]},
                                 g) > 0 for a in A)]
        miss_c = [g for g in gm
                  if not any(iou({"start": b["start"], "end": b["end"]},
                                 g) > 0 for b in B)]
        tot["nA"] += len(A)
        tot["nB"] += len(B)
        tot["matched"] += len(matches)
        tot["type_agree"] += type_agree
        tot["onlyA"] += len(onlyA)
        tot["onlyB"] += len(onlyB)
        tot["agreed_ok"] += agreed_ok
        tot["disagreed_total"] += len(onlyA) + len(onlyB)
        tot["disagreed_ok"] += disagreed_ok
        tot["gold_miss_m"] += len(miss_m)
        tot["gold_miss_c"] += len(miss_c)
        rows.append({"case_id": cid, "nA": len(A), "nB": len(B),
                     "matched": len(matches),
                     "type_agree": type_agree,
                     "onlyA": [a["quote"] for a in onlyA],
                     "onlyB": [b["quote"] for b in onlyB],
                     "gold_missed_by_mistral": [g["span"] for g in miss_m],
                     "gold_missed_by_codestral": [g["span"] for g in miss_c]})
    summary = {
        "mentions_mistral": tot["nA"], "mentions_codestral": tot["nB"],
        "matched_pairs": tot["matched"],
        "mention_agreement": round(tot["matched"] /
                                   max(1, (tot["nA"] + tot["nB"]) / 2), 3),
        "type_agreement_on_matched": round(tot["type_agree"] /
                                           max(1, tot["matched"]), 3),
        "only_mistral": tot["onlyA"], "only_codestral": tot["onlyB"],
        "gold_missed_by_mistral": tot["gold_miss_m"],
        "gold_missed_by_codestral": tot["gold_miss_c"],
        "agreed_on_gold_event": tot["agreed_ok"],
        "disagreed_mentions": tot["disagreed_total"],
        "disagreed_on_gold_event": tot["disagreed_ok"],
        "agreement_precision_proxy": round(
            tot["agreed_ok"] / max(1, tot["matched"]), 3),
        "disagreement_precision_proxy": round(
            tot["disagreed_ok"] / max(1, tot["disagreed_total"]), 3),
        "mean_match_iou": round(sum(ious) / len(ious), 3) if ious else 0.0,
    }
    (OUT / "agreement.json").write_text(
        json.dumps({"summary": summary, "per_case": rows}, indent=1,
                   ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
