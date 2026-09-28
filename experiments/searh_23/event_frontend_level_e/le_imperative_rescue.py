"""Exploratory follow-up: source-exact leading-imperative recovery.

This design followed inspection of E3 frontend omissions, so E3 is no longer
sealed for this arm. The separate E4 contrast set was committed before this
classifier was run. No business vocabulary or tool name enters the prompt.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
EC = HERE.parent / "event_canon_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(EC), str(PL)]
from ec_common import load_suite
from pl_common import Mistral, render_tool
from pl_frontend import RESOLVER_SYSTEM, LABEL_TO_ROLE
from le_frontend_fixed import opaque_tool

OUT = HERE / "outputs"
SYSTEM = """Determine whether the exact sentence begins with a BARE IMPERATIVE instruction to perform a real action (a command addressed to the agent/operator). Distinguish an initial verb from a noun or adjective with the same spelling. Copular entity/state descriptions, passive descriptions, and later deontic instructions are OTHER_CONTEXT for this narrow rescue task. Return JSON only: {"label":"LEADING_IMPERATIVE|OTHER_CONTEXT|UNKNOWN","span":"exact continuous source words of the leading action, excluding final punctuation, or empty string"}. The span must begin at the first non-space character of the sentence. If uncertain, UNKNOWN. Do not infer an action from a noun."""


def classify(client, sentence):
    rec = client.ask(SYSTEM, json.dumps({"sentence": sentence}, ensure_ascii=False), max_tokens=130)
    ans, err = Mistral.parse_json(rec["raw"])
    ans = ans if isinstance(ans, dict) else {}
    label = (ans or {}).get("label")
    span = (ans or {}).get("span")
    if label not in {"LEADING_IMPERATIVE", "OTHER_CONTEXT", "UNKNOWN"}:
        label = "UNKNOWN"
    if not isinstance(span, str):
        span = ""
    if label == "LEADING_IMPERATIVE" and not (span and sentence.startswith(span) and
                                                len(span.strip()) >= 3):
        label, span = "UNKNOWN", ""
    return {"label": label, "span": span, "raw": rec["raw"],
            "error": err, "usage": rec.get("usage", {})}


def e4():
    rows = json.loads((HERE / "frozen" / "e4_rescue_contrasts.json").read_text(encoding="utf-8"))
    client = Mistral(cache_dir=OUT / "_cache")
    dst = OUT / "E4_RESCUE"
    dst.mkdir(parents=True, exist_ok=True)
    for row in rows:
        path = dst / f"{row['id']}.json"
        if path.exists():
            continue
        result = classify(client, row["sentence"])
        path.write_text(json.dumps({"id": row["id"], "sentence": row["sentence"],
                                    **result}, indent=2) + "\n", encoding="utf-8")
        print(row["id"], result["label"], repr(result["span"]), flush=True)
    print(json.dumps({"calls": client.calls, "usage": client.usage_total}), flush=True)


def score_e4():
    gold = {r["id"]: r for r in json.loads((HERE / "frozen" / "e4_rescue_contrasts.json").read_text(encoding="utf-8"))}
    pred = {r["id"]: r for r in (json.loads(p.read_text(encoding="utf-8")) for p in (OUT / "E4_RESCUE").glob("*.json"))}
    if set(pred) != set(gold):
        raise ValueError("incomplete E4")
    tp = sum(pred[k]["label"] == "LEADING_IMPERATIVE" and gold[k]["gold"] == "LEADING_IMPERATIVE" and
             pred[k]["span"] == gold[k]["span"] for k in gold)
    fp = sum(pred[k]["label"] == "LEADING_IMPERATIVE" and gold[k]["gold"] != "LEADING_IMPERATIVE" for k in gold)
    fn = sum(gold[k]["gold"] == "LEADING_IMPERATIVE" and not
             (pred[k]["label"] == "LEADING_IMPERATIVE" and pred[k]["span"] == gold[k]["span"]) for k in gold)
    result = {"tp_exact": tp, "fp": fp, "fn": fn, "precision": tp/(tp+fp) if tp+fp else 0,
              "recall": tp/(tp+fn) if tp+fn else 0,
              "errors": [{"id": k, "gold": gold[k]["gold"], "gold_span": gold[k]["span"],
                          "pred": pred[k]["label"], "pred_span": pred[k]["span"]}
                         for k in gold if (pred[k]["label"] != gold[k]["gold"] or
                                           gold[k]["gold"] == "LEADING_IMPERATIVE" and pred[k]["span"] != gold[k]["span"])]}
    (OUT / "E4_score.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


def sentence_spans(policy):
    for m in re.finditer(r"[^.!?]+[.!?]?", policy):
        part = m.group(0)
        lead = len(part) - len(part.lstrip())
        sentence = part.strip()
        if sentence:
            yield m.start() + lead, sentence


def e3():
    from sentence_transformers import CrossEncoder
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda", max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(cache_dir=OUT / "_cache")
    dest = OUT / "FRONTEND_imperative_v2"
    dest.mkdir(parents=True, exist_ok=True)
    records = OUT / "E3_IMPERATIVE_PROPOSALS"
    records.mkdir(parents=True, exist_ok=True)
    for case in load_suite("original"):
        cid = case["case_id"]
        outpath = dest / f"{cid}.json"
        if outpath.exists():
            continue
        original = json.loads((OUT / "FRONTEND_fixed_rescue" / f"{cid}.json").read_text(encoding="utf-8"))["events"]
        events = list(original)
        for start, sentence in sentence_spans(case["policy"]):
            if any(p["span_start"] == start and not p.get("is_np") for p in original):
                continue
            recpath = records / f"{cid}__{start}.json"
            if recpath.exists():
                result = json.loads(recpath.read_text(encoding="utf-8"))
            else:
                result = classify(client, sentence)
                recpath.write_text(json.dumps({"case_id": cid, "start": start, "sentence": sentence,
                                               **result}, indent=2) + "\n", encoding="utf-8")
            if result["label"] != "LEADING_IMPERATIVE":
                continue
            span = result["span"]
            if any(p["span_start"] == start and p["span"].startswith(span) for p in events):
                continue
            tools = case["tools"]
            scores = rer.predict([(span, render_tool(t)) for t in tools], convert_to_numpy=True)
            ranked = sorted(zip(scores, tools), key=lambda z: -float(z[0]))[:3]
            query = json.dumps({"policy_span": span,
                                "tools": [opaque_tool(t, j+1) for j, (_, t) in enumerate(ranked)]}, ensure_ascii=False)
            response = client.ask(RESOLVER_SYSTEM, query, max_tokens=200)
            ans, _ = Mistral.parse_json(response["raw"])
            ans = ans if isinstance(ans, dict) else {}
            label = (ans or {}).get("label")
            role = LABEL_TO_ROLE.get(label, "UNKNOWN") if isinstance(label, str) else "UNKNOWN"
            events.append({"span": span, "span_start": start, "span_end": start + len(span),
                           "role": role, "governed_tools": [ranked[0][1]["name"]] if ranked else [],
                           "resolver_label": label, "is_np": False, "dep": "rescue_imperative",
                           "mark": None, "pos_rescue": True, "rescue_label": result["label"]})
            print(cid, "RESCUED", repr(span), role, flush=True)
        events.sort(key=lambda p: (p["span_start"], p["span_end"]))
        outpath.write_text(json.dumps({"case_id": cid, "events": events}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(cid, len(original), len(events), flush=True)
    print(json.dumps({"calls": client.calls, "usage": client.usage_total}), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("phase", choices=("e4", "score_e4", "e3"))
    {"e4": e4, "score_e4": score_e4, "e3": e3}[ap.parse_args().phase]()
