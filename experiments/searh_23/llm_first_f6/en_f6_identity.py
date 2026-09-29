"""F6 identity layer — F4way judge (frozen prompt, byte-identical
SYSTEM text from the F5 en_identity_llm.py) over:

  1. F6 gold mention pairs (293) - identity classifier transfer;
  2. raw-mention pairs (all pairs of grounded mentions per case) with
     overlap-derived gold labels - composed-system identity;
  3. CF twin focus pairs - the directive section 2 counterfactual
     identity flips.

Run: python3 en_f6_identity.py gold|raw|cf
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).parent
_env = Path("/home/z/my-project/guardian-access/mistral.env")
if _env.is_file() and not os.environ.get("MISTRAL_API_KEY"):
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

IE = HERE.parent / "event_ie_frontends_v1"
sys.path.insert(0, str(HERE))
from f6_mistral import Mistral  # noqa: E402

FROZEN = HERE / "f6_frozen"
RAW = HERE / "outputs" / "raw"
OUT = HERE / "outputs" / "identity"
OUT.mkdir(parents=True, exist_ok=True)

F4_SYSTEM = """You decide whether two event mentions from the same policy text refer to the SAME single event occurrence, are merely related but DISTINCT events, are clearly DIFFERENT events, or the text is insufficient to decide (AMBIGUOUS).

SAME single event: the two spans denote one and the same prescribed or reported occurrence - e.g. an imperative and a later passive or nominal reference to it ('Weigh each batch' / 'after the batch is weighed'), or an anaphoric reference ('This verification', 'the inspection' pointing at 'Inspect the filter').
RELATED but DISTINCT events: an action vs a check or observation of that action ('make the payment' / 'verify the payment was made'); an action vs its result state; an action vs the recording of that action ('the cleaning' / 'the cleaning is logged'); same predicate on different entities ('Feed the otters' / 'Feed the red pandas'); different occurrence of the same action ('weigh the batch' / 'weigh the batch again').
DIFFERENT events: different predicates or unrelated actions.
AMBIGUOUS: the text does not give enough evidence to decide (use this instead of guessing).
Judge ONLY from the given text; do not use world knowledge to merge similar-sounding events. Semantic similarity is NOT same event. Same predicate is NOT automatically same event.
Answer with JSON only: {"label": "SAME_EVENT"|"RELATED_BUT_DIFFERENT"|"DIFFERENT_EVENT"|"AMBIGUOUS", "reason": "<one short sentence citing the decisive text>"}."""


def sentence_of(policy: str, start: int) -> str:
    pos = 0
    for s in re.split(r"(?<=[.!?])\s+", policy):
        if pos <= start < pos + len(s):
            return s.strip()
        pos += len(s) + 1
    return ""


def f4_user(policy, a_span, b_span, ctx_a, ctx_b, tools_block=""):
    return (f"POLICY:\n{policy}\n\n{tools_block}"
            f'MENTION A: "{a_span}"\n'
            f'Context of A: "{ctx_a}"\n\n'
            f'MENTION B: "{b_span}"\n'
            f'Context of B: "{ctx_b}"\n\n'
            "Do A and B refer to the same single event occurrence? "
            "Answer with JSON only.")


def load_cases():
    return json.loads((IE / "frozen" / "level_f6_cases.json")
                      .read_text(encoding="utf-8"))


def load_gold_pairs():
    return json.loads((FROZEN / "f6_pairs_gold.json").read_text())


def judge_pairs(pairs, client, out_path, tools_by_case=None):
    """pairs: dicts with case/policy/a_span/a_start/b_span/b_start/label."""
    results = []
    for i, p in enumerate(pairs):
        tools_block = ""
        if tools_by_case:
            tl = tools_by_case.get(p["case"], [])
            tools_block = ("TOOLS available in this workplace:\n"
                           + "\n".join(f"- {t['name']}: {t['description']}"
                                       for t in tl) + "\n\n")
        user = f4_user(p["policy"], p["a_span"], p["b_span"],
                       sentence_of(p["policy"], p["a_start"]),
                       sentence_of(p["policy"], p["b_start"]), tools_block)
        rec = client.ask(F4_SYSTEM, user, max_tokens=200)
        ans, _err = Mistral.parse_json(rec["raw"])
        results.append({**p, "pred": (ans or {}).get("label", "PARSE_FAIL"),
                        "reason": (ans or {}).get("reason", "")})
        if (i + 1) % 40 == 0:
            print(f"  {i+1}/{len(pairs)}", flush=True)
            out_path.write_text(json.dumps(results, indent=1,
                                           ensure_ascii=False) + "\n",
                                encoding="utf-8")
    out_path.write_text(json.dumps(results, indent=1,
                                   ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return results


def pair_metrics(results):
    cm = Counter((r["label"], r["pred"]) for r in results)
    same_gold = [r for r in results if r["label"] == "SAME_EVENT"]
    tp = sum(1 for r in same_gold if r["pred"] == "SAME_EVENT")
    fp = sum(1 for r in results
             if r["label"] != "SAME_EVENT" and r["pred"] == "SAME_EVENT")
    fn = len(same_gold) - tp
    p = tp / (tp + fp) if tp + fp else 0.0
    r_ = tp / len(same_gold) if same_gold else 0.0
    f1 = 2 * p * r_ / (p + r_) if p + r_ else 0.0
    acc = sum(1 for r in results if r["label"] == r["pred"]) / len(results)
    dangerous = sum(1 for r in results
                    if r["label"] == "DIFFERENT_EVENT"
                    and r["pred"] == "SAME_EVENT")
    return {"n": len(results), "same_p": round(p, 3), "same_r": round(r_, 3),
            "same_f1": round(f1, 3), "acc": round(acc, 3),
            "dangerous": dangerous,
            "confusion": {f"{a}>{b}": n for (a, b), n in sorted(cm.items())}}


def run_gold():
    cases = {c["case_id"]: c for c in load_cases()}
    gold_pairs = load_gold_pairs()
    pairs = []
    for cid, plist in gold_pairs.items():
        case = cases[cid]
        for p in plist:
            a_start = case["policy"].find(p["a"])
            b_start = case["policy"].find(p["b"])
            pairs.append({"case": cid, "policy": case["policy"],
                          "a_span": p["a"], "a_start": a_start,
                          "b_span": p["b"], "b_start": b_start,
                          "label": p["label"]})
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    tools = {c["case_id"]: c["tools"] for c in cases.values()}
    res = judge_pairs(pairs, client, OUT / "f4_gold_pairs.json", tools)
    print("[gold pairs]", json.dumps(pair_metrics(res)))


def _overlap_label(case, m):
    best, blab = 0.0, None
    for g in case["mentions"]:
        if not g.get("cid"):
            continue
        inter = max(0, min(m["end"], g["end"]) - max(m["start"], g["start"]))
        if inter > best:
            best, blab = inter, g["cid"]
    return blab


def run_raw():
    cases = {c["case_id"]: c for c in load_cases()}
    gold_pairs = load_gold_pairs()
    rel = {}
    for cid, case in cases.items():
        rel[cid] = {(p[0], p[1]) for p in case.get("related_pairs", [])} | \
                   {(p[1], p[0]) for p in case.get("related_pairs", [])} | \
                   {(e["from_cid"], e["to_cid"]) for e in
                    case["normative_edges"]} | \
                   {(e["to_cid"], e["from_cid"]) for e in
                    case["normative_edges"]}
    pairs = []
    for cid, case in cases.items():
        f = RAW / "mistral" / "A" / f"{cid}.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        mentions = [m for m in data["mentions"] if m.get("grounded")]
        for a, b in combinations(mentions, 2):
            la, lb = _overlap_label(case, a), _overlap_label(case, b)
            if la is None or lb is None:
                continue
            if la == lb:
                lab = "SAME_EVENT"
            elif (la, lb) in rel[cid]:
                lab = "RELATED_BUT_DIFFERENT"
            else:
                lab = "DIFFERENT_EVENT"
            pairs.append({"case": cid, "policy": case["policy"],
                          "a_span": a["quote"], "a_start": a["start"],
                          "b_span": b["quote"], "b_start": b["start"],
                          "label": lab})
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    tools = {c["case_id"]: c["tools"] for c in cases.values()}
    res = judge_pairs(pairs, client, OUT / "f4_raw_pairs.json", tools)
    print("[raw pairs]", json.dumps(pair_metrics(res)))


def run_cf():
    tw = json.loads((FROZEN / "f6_cf_twins.json").read_text())["twins"]
    pairs = []
    for t in tw:
        for side in ("a", "b"):
            s = t[side]
            pol = s["policy"]
            fa, fb = s["focus"]
            pairs.append({"case": f"{t['twin_id']}_{side}", "policy": pol,
                          "a_span": fa, "a_start": pol.find(fa),
                          "b_span": fb, "b_start": pol.find(fb),
                          "label": s["expected"],
                          "twin_id": t["twin_id"], "side": side})
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    res = judge_pairs(pairs, client, OUT / "f4_cf_pairs.json")
    print("[cf pairs]")
    for r in res:
        print(f"  {r['case']}: gold={r['label']} pred={r['pred']}")
    both = {}
    for r in res:
        both.setdefault(r["twin_id"], {})[r["side"]] = r["pred"] == r["label"]
    for tid, d in both.items():
        print(f"  {tid}: a={'OK' if d.get('a') else 'FAIL'} "
              f"b={'OK' if d.get('b') else 'FAIL'}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "gold"
    {"gold": run_gold, "raw": run_raw, "cf": run_cf}[which]()
