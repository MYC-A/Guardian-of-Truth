"""Track A scorer: frontend quality without Guardian downstream.

Scores every arm's outputs/<ARM>/<case>.json against the frozen Level F
gold: mention detection (exact + IoU>=0.5), typing micro/macro F1,
argument accuracy, semantic link P/R, hallucination rates, provenance.

Oracle rows are computed from the same gold to decompose where loss sits:
  ORACLE_MENTIONS  gold spans only (type UNKNOWN)
  ORACLE_TYPES     gold spans + gold types
  ORACLE_LINKS     + gold semantic links
(they bound the stages; FULL GOLD appears in Track B)

Run:  python3 lf_score.py            # scores every outputs/ subdirectory
      python3 lf_score.py CUR UIE    # selected arms
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "outputs"
TYPES = ["EVENT", "EVENT_REFERENCE", "STATE_OR_FACET", "ARTIFACT",
         "CHECK", "ENTITY", "UNKNOWN"]


def load_gold() -> dict[str, dict]:
    cases = json.loads((HERE / "frozen" / "level_f_cases.json")
                       .read_text(encoding="utf-8"))
    return {c["case_id"]: c for c in cases}


def iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def match_mentions(gold_ms: list[dict], pred_cs: list[dict]) -> dict:
    """Greedy one-to-one matching, exact first then IoU>=0.5.

    Returns {gold_mid: {"pred": ..., "mode": exact|iou}}, plus reverse map.
    """
    by_exact: dict[str, list] = defaultdict(list)
    for c in pred_cs:
        if c.get("span"):
            by_exact[c["span"].strip()].append(c)
    matched: dict[str, dict] = {}
    used_pred: set = set()
    unmatched_gold: list = []
    for g in gold_ms:
        key = g["span"].strip()
        hit = None
        for c in by_exact.get(key, []):
            if id(c) not in used_pred:
                hit = c
                break
        if hit is not None:
            used_pred.add(id(hit))
            matched[g["mid"]] = {"pred": hit, "mode": "exact"}
        else:
            unmatched_gold.append(g)
    # IoU pass for remaining gold with predicted offsets
    for g in unmatched_gold:
        best, best_iou = None, 0.0
        for c in pred_cs:
            if id(c) in used_pred or c.get("start") is None:
                continue
            j = iou((g["start"], g["end"]), (c["start"], c["end"]))
            if j > best_iou:
                best, best_iou = c, j
        if best is not None and best_iou >= 0.5:
            used_pred.add(id(best))
            matched[g["mid"]] = {"pred": best, "mode": "iou"}
    return {"matched": matched, "n_matched": len(matched),
            "n_gold": len(gold_ms), "n_pred": len(pred_cs),
            "n_pred_used": len(used_pred)}


def score_case(gold: dict, preds: list[dict]) -> dict:
    c = Counter()
    # 1) hallucination: span not verbatim in policy
    policy = gold["policy"]
    for p in preds:
        if not p.get("span") or p["span"].strip() not in policy:
            c["hallucinated_nodes"] += 1
    # 2) mention detection
    m = match_mentions(gold["mentions"], preds)
    c["gold_mentions"] = m["n_gold"]
    c["pred_mentions"] = m["n_pred"]
    c["matched_exact"] = sum(1 for v in m["matched"].values()
                             if v["mode"] == "exact")
    c["matched_iou"] = m["n_matched"] - c["matched_exact"]
    # 3) typing on matched pairs
    per_type = defaultdict(lambda: Counter())
    for g in gold["mentions"]:
        hit = m["matched"].get(g["mid"])
        gt = g["type"]
        per_type[gt]["gold"] += 1
        if hit:
            pt = hit["pred"].get("type", "UNKNOWN")
            per_type[gt]["pred"] += 1
            if pt == gt:
                per_type[gt]["tp"] += 1
                c["type_correct"] += 1
            else:
                c["type_confusion_" + gt + "->" + pt] = 1 + c.get(
                    "type_confusion_" + gt + "->" + pt, 0)
        if hit:
            c["typed_pairs"] += 1
    # 4) arguments (gold event mentions with arguments)
    gold_args = 0
    gold_args_hit = 0
    ent_by_mid = {e["xid"]: e for e in gold.get("entities", [])}
    for a in gold.get("arguments", []):
        g = next((x for x in gold["mentions"] if x["mid"] == a["event_mid"]),
                 None)
        if not g:
            continue
        ent = ent_by_mid.get(a["entity_xid"])
        if not ent:
            continue
        gold_args += 1
        hit = m["matched"].get(g["mid"])
        if hit:
            pargs = hit["pred"].get("arguments", [])
            for pa in pargs:
                if (pa.get("role") == a["role"] and pa.get("span")
                        and any(pa["span"].strip() == s.strip()
                                for s in ent["spans"])):
                    gold_args_hit += 1
                    break
    c["gold_arguments"] = gold_args
    c["arguments_hit"] = gold_args_hit
    # 5) semantic links (span-pair + type)
    gold_link_set = set()
    by_mid = {x["mid"]: x for x in gold["mentions"]}
    for lk in gold.get("semantic_links", []):
        src = by_mid.get(lk["from"])
        if src is None:
            continue
        if lk["to"].startswith("E"):
            # link to canonical event: use its first anchored mention span
            tgt = next((x for x in gold["mentions"]
                        if x.get("cid") == lk["to"]
                        and x["type"] in ("EVENT", "EVENT_REFERENCE",
                                          "STATE_OR_FACET", "CHECK")), None)
        else:
            tgt = by_mid.get(lk["to"])
        if tgt is None:
            continue
        gold_link_set.add((lk["link"], src["span"].strip(),
                           tgt["span"].strip()))
    c["gold_links"] = len(gold_link_set)
    pred_link_set = set()
    by_cid = {p["cid_local"]: p for p in preds}
    for p in preds:
        for r in p.get("relations", []):
            t = by_cid.get(r.get("to"))
            if t is None:
                c["hallucinated_links"] += 1
                continue
            if p.get("span") and t.get("span"):
                pred_link_set.add((r.get("type", "UNKNOWN"),
                                   p["span"].strip(), t["span"].strip()))
    c["pred_links"] = len(pred_link_set)
    c["links_tp"] = len(gold_link_set & pred_link_set)
    # 6) provenance availability
    c["with_offsets"] = sum(1 for p in preds if p.get("start") is not None)
    return {"counts": dict(c), "per_type": {k: dict(v)
                                            for k, v in per_type.items()},
            "type_confusions": {k: v for k, v in c.items()
                                if k.startswith("type_confusion_")}}


def score_arm(arm_dir: Path, gold: dict[str, dict]) -> dict | None:
    rows = {}
    total = Counter()
    per_type_total = defaultdict(Counter)
    for cid, g in gold.items():
        f = arm_dir / f"{cid}.json"
        if not f.exists():
            continue
        preds = json.loads(f.read_text(encoding="utf-8"))["candidates"]
        row = score_case(g, preds)
        rows[cid] = row
        total.update(row["counts"])
        for t, cc in row["per_type"].items():
            per_type_total[t].update(cc)
    if not rows:
        return None
    n_gold, n_pred = total["gold_mentions"], total["pred_mentions"]
    matched = total["matched_exact"] + total["matched_iou"]
    mention_p = matched / n_pred if n_pred else 0.0
    mention_r = matched / n_gold if n_gold else 0.0
    typed = total.get("typed_pairs", 0)
    type_acc = total.get("type_correct", 0) / typed if typed else 0.0
    # micro type F1 over the 6 real classes (UNKNOWN excluded as a class,
    # counted as wrong prediction)
    micro = {}
    for t in ["EVENT", "EVENT_REFERENCE", "STATE_OR_FACET", "ARTIFACT",
              "CHECK", "ENTITY"]:
        g = per_type_total[t]["gold"]
        p = per_type_total[t]["pred"]
        tp = per_type_total[t]["tp"]
        prec = tp / p if p else 0.0
        rec = tp / g if g else 0.0
        micro[t] = {"gold": g, "pred": p, "tp": tp, "P": round(prec, 3),
                    "R": round(rec, 3),
                    "F1": round(2 * prec * rec / (prec + rec), 3)
                    if prec + rec else 0.0}
    f1s = [v["F1"] for v in micro.values() if v["gold"]]
    link_p = total["links_tp"] / total["pred_links"] \
        if total["pred_links"] else 0.0
    link_r = total["links_tp"] / total["gold_links"] \
        if total["gold_links"] else 0.0
    return {"n_cases": len(rows),
            "mention_P": round(mention_p, 3), "mention_R": round(mention_r, 3),
            "mention_F1": round(2 * mention_p * mention_r /
                                (mention_p + mention_r), 3)
            if mention_p + mention_r else 0.0,
            "exact_match_rate": round(total["matched_exact"] / n_gold, 3)
            if n_gold else 0.0,
            "type_accuracy_on_matched": round(type_acc, 3),
            "type_micro": micro,
            "type_macro_F1": round(sum(f1s) / len(f1s), 3) if f1s else 0.0,
            "arguments_hit": total.get("arguments_hit", 0),
            "gold_arguments": total.get("gold_arguments", 0),
            "links_P": round(link_p, 3), "links_R": round(link_r, 3),
            "hallucinated_nodes": total.get("hallucinated_nodes", 0),
            "hallucinated_links": total.get("hallucinated_links", 0),
            "with_offsets": total.get("with_offsets", 0),
            "pred_total": n_pred, "rows": rows}


def main() -> None:
    arms = sys.argv[1:] or [d.name for d in sorted(OUT.iterdir())
                            if d.is_dir()
                            and any(f.suffix == ".json"
                                    for f in d.iterdir())]
    gold = load_gold()
    report = {}
    for arm in arms:
        d = OUT / arm
        if not d.is_dir():
            print("skip", arm)
            continue
        res = score_arm(d, gold)
        if res:
            report[arm] = res
            print(f"{arm:14s} mP={res['mention_P']:.3f} "
                  f"mR={res['mention_R']:.3f} "
                  f"exact={res['exact_match_rate']:.3f} "
                  f"typeAcc={res['type_accuracy_on_matched']:.3f} "
                  f"macroF1={res['type_macro_F1']:.3f} "
                  f"links P/R={res['links_P']:.3f}/{res['links_R']:.3f} "
                  f"hallN={res['hallucinated_nodes']} "
                  f"pred={res['pred_total']}")
    (OUT / "score_trackA.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print("written", OUT / "score_trackA.json")


if __name__ == "__main__":
    main()
