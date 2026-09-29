"""F6 mention-level scorer — directive section 16 metrics.

For each raw arm (model x arm x suite):
  - exact span P/R/F1 vs gold event mentions (cid non-null);
  - overlap (IoU>0) and strict (IoU>=0.5) matching secondary;
  - semantic gold mention recall (gold event cids covered);
  - junk mentions (no overlap with any gold event mention);
  - entity-only mentions (overlap only gold ENTITY/ARTIFACT spans);
  - hallucinated/non-source quotes (from the grounding check);
  - boundary deltas on matched pairs (IoU mean, over-extension counts);
  - typing confusion matrix (sem_type on best-IoU matched pairs);
  - raw vs grounded counts (directive section 6, ARM B vs A).

Run: python3 en_f6_mentions.py   (writes outputs/score/mentions.json)
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
FROZEN = HERE / "f6_frozen"
IE = HERE.parent / "event_ie_frontends_v1"
RAW = HERE / "outputs" / "raw"
OUT = HERE / "outputs" / "score"
OUT.mkdir(parents=True, exist_ok=True)

SEM = ["ACTION", "CHECK", "STATE", "RECORD", "COMMUNICATION",
       "REFERENCE_TO_EVENT", "OTHER"]


def load_cases(suite: str) -> list[dict]:
    fname = {"f6": "level_f6_cases.json",
             "f6r": "level_f6r_cases.json",
             }[suite]
    return json.loads((IE / "frozen" / fname).read_text(encoding="utf-8"))


def load_cf() -> list[dict]:
    tw = json.loads((FROZEN / "f6_cf_twins.json").read_text())["twins"]
    out = []
    for t in tw:
        for side in ("a", "b"):
            out.append({"case_id": f"{t['twin_id']}_{side}",
                        "policy": t[side]["policy"],
                        "focus": t[side]["focus"],
                        "expected": t[side]["expected"],
                        "twin_id": t["twin_id"], "side": side,
                        "mentions": [], "tools": []})
    return out


def iou(a: dict, b: dict) -> float:
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    if inter == 0:
        return 0.0
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / max(1, union)


def score_case(gold: dict, llm: dict) -> dict:
    gm = [m for m in gold["mentions"] if m.get("cid")]
    gall = gold["mentions"]
    pred = [m for m in llm["mentions"] if m.get("grounded")]
    # exact spans
    gold_spans = {m["span"] for m in gm}
    pred_spans = {m["quote"] for m in pred}
    exact_p = len(pred_spans & gold_spans) / len(pred_spans) if pred_spans else 0.0
    exact_r = len(pred_spans & gold_spans) / len(gold_spans) if gold_spans else 0.0
    # matching by best IoU (greedy, one-to-one)
    pairs = []
    used = set()
    for i, p in enumerate(pred):
        best, bi = 0.0, -1
        for j, g in enumerate(gm):
            v = iou({"start": p["start"], "end": p["end"]}, g)
            if v > best:
                best, bi = v, j
        if bi >= 0 and best > 0 and bi not in used:
            used.add(bi)
            pairs.append((i, bi, best))
    matched_strict = [(i, j) for i, j, v in pairs if v >= 0.5]
    # coverage of gold event mentions (loose overlap)
    covered = set()
    for j, g in enumerate(gm):
        if any(iou({"start": p["start"], "end": p["end"]}, g) > 0
               for p in pred):
            covered.add(j)
    # junk / entity-only
    junk, ent_only = [], []
    for i, p in enumerate(pred):
        ev = any(iou({"start": p["start"], "end": p["end"]}, g) > 0
                 for g in gm)
        if ev:
            continue
        any_gold = any(iou({"start": p["start"], "end": p["end"]}, g) > 0
                       for g in gall)
        (ent_only if any_gold else junk).append(p["quote"])
    # typing on strict matches
    conf = Counter()
    for i, j in matched_strict:
        gs = gm[j].get("sem_type", "OTHER")
        ps = pred[i].get("type", "OTHER")
        if ps not in SEM:
            ps = "OTHER"
        conf[(gs, ps)] += 1
    return {"case_id": gold.get("case_id", llm["case_id"]),
            "n_gold_events": len(gm), "n_pred": len(pred),
            "n_raw": llm.get("raw_count", len(pred)),
            "n_hallucinated": llm.get("hallucinated", 0),
            "exact_p": round(exact_p, 3), "exact_r": round(exact_r, 3),
            "n_exact": len(pred_spans & gold_spans),
            "n_matched_strict": len(matched_strict),
            "n_covered_gold": len(covered),
            "junk": junk, "entity_only": ent_only,
            "iou_matched": [round(v, 3) for _, _, v in pairs],
            "confusion": {f"{a}>{b}": n for (a, b), n in conf.items()},
            }


def agg(rows: list[dict]) -> dict:
    t = Counter()
    ious_all: list[float] = []
    for r in rows:
        t["gold"] += r["n_gold_events"]
        t["pred"] += r["n_pred"]
        t["raw"] += r["n_raw"]
        t["hallu"] += r["n_hallucinated"]
        t["exact"] += r["n_exact"]
        t["strict"] += r["n_matched_strict"]
        t["covered"] += r["n_covered_gold"]
        t["junk"] += len(r["junk"])
        t["ent_only"] += len(r["entity_only"])
        ious_all.extend(r["iou_matched"])
    p = t["exact"] / t["pred"] if t["pred"] else 0
    r_ = t["exact"] / t["gold"] if t["gold"] else 0
    f1 = 2 * p * r_ / (p + r_) if p + r_ else 0
    cov = t["covered"] / t["gold"] if t["gold"] else 0
    str_r = t["strict"] / t["gold"] if t["gold"] else 0
    return {"n_cases": len(rows), "gold_events": t["gold"],
            "pred_mentions": t["pred"], "raw_generated": t["raw"],
            "hallucinated": t["hallu"],
            "exact_p": round(p, 3), "exact_r": round(r_, 3),
            "exact_f1": round(f1, 3),
            "coverage_loose": round(cov, 3),
            "strict_match_r": round(str_r, 3),
            "junk": t["junk"], "entity_only": t["ent_only"],
            "mean_iou_matched": round(sum(ious_all) / len(ious_all), 3)
            if ious_all else 0.0}


def main() -> None:
    report = {}
    cases = load_cases("f6")
    cf_cases = load_cf()
    for model_key in ("mistral", "codestral"):
        for arm in ("A", "B"):
            rows = []
            for case in cases:
                f = RAW / model_key / arm / f"{case['case_id']}.json"
                if not f.exists():
                    continue
                rows.append(score_case(
                    case, json.loads(f.read_text(encoding="utf-8"))))
            key = f"{model_key}_{arm}"
            report[key] = {"per_case": rows, "agg": agg(rows)}
            # typing confusion aggregate
            conf = Counter()
            for r in rows:
                for k, n in r["confusion"].items():
                    a, b = k.split(">")
                    conf[(a, b)] += n
            report[key]["typing_confusion"] = {
                f"{a}>{b}": n for (a, b), n in sorted(conf.items())}
            print(key, json.dumps(report[key]["agg"]), flush=True)
    # CF twins: focus-pair identity decision is evaluated in the identity
    # module; here we record mention presence for the focus spans.
    cf_report = {}
    for model_key in ("mistral", "codestral"):
        for arm in ("A", "B"):
            cf_rows = []
            for case in cf_cases:
                f = RAW / model_key / arm / f"{case['case_id']}.json"
                if not f.exists():
                    continue
                data = json.loads(f.read_text(encoding="utf-8"))
                pred = [m for m in data["mentions"] if m.get("grounded")]
                focus_hit = []
                for fs in case["focus"]:
                    hit = next((m["quote"] for m in pred
                                if iou({"start": m["start"],
                                        "end": m["end"]},
                                       {"start": case["policy"].find(fs),
                                        "end": case["policy"].find(fs) +
                                        len(fs)}) >= 0.3), None)
                    focus_hit.append(hit)
                cf_rows.append({"case_id": case["case_id"],
                                "focus": case["focus"],
                                "focus_hits": focus_hit,
                                "expected": case["expected"],
                                "n_pred": len(pred)})
            cf_report[f"{model_key}_{arm}"] = cf_rows
    report["cf_focus_presence"] = cf_report
    (OUT / "mentions.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print("[mentions] written", OUT / "mentions.json")


if __name__ == "__main__":
    main()
