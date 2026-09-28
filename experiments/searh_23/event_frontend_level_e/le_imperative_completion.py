"""After E4 showed short copied spans, complete a confirmed command in code.

The LLM decides only whether the sentence is a leading imperative. For that
case, the candidate is the source-exact full sentence minus terminal
punctuation; this retains IDs/arguments. E5 is the untouched contrast test.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from le_imperative_rescue import classify, sentence_spans
from pl_common import Mistral

HERE = Path(__file__).parent
OUT = HERE / "outputs"


def complete(sentence: str, label: str) -> str:
    return sentence.rstrip().rstrip(".!?").rstrip() if label == "LEADING_IMPERATIVE" else ""


def e5():
    rows = json.loads((HERE / "frozen" / "e5_span_recovery_contrasts.json").read_text(encoding="utf-8"))
    client = Mistral(cache_dir=OUT / "_cache")
    dst = OUT / "E5_RESCUE"
    dst.mkdir(parents=True, exist_ok=True)
    for row in rows:
        path = dst / f"{row['id']}.json"
        if path.exists():
            continue
        raw = classify(client, row["sentence"])
        proposed = complete(row["sentence"], raw["label"])
        path.write_text(json.dumps({"id": row["id"], "sentence": row["sentence"],
                                    "label": raw["label"], "llm_span": raw["span"],
                                    "completed_span": proposed, "raw": raw["raw"],
                                    "usage": raw["usage"]}, indent=2) + "\n", encoding="utf-8")
        print(row["id"], raw["label"], repr(raw["span"]), "=>", repr(proposed), flush=True)
    print(json.dumps({"calls": client.calls, "usage": client.usage_total}), flush=True)


def score():
    gold = {r["id"]: r for r in json.loads((HERE / "frozen" / "e5_span_recovery_contrasts.json").read_text(encoding="utf-8"))}
    pred = {r["id"]: r for r in (json.loads(p.read_text(encoding="utf-8")) for p in (OUT / "E5_RESCUE").glob("*.json"))}
    if set(pred) != set(gold):
        raise ValueError("incomplete E5")
    tp = sum(pred[k]["label"] == "LEADING_IMPERATIVE" and gold[k]["gold"] == "LEADING_IMPERATIVE"
             and pred[k]["completed_span"] == gold[k]["sentence"].rstrip(".!? ") for k in gold)
    fp = sum(pred[k]["label"] == "LEADING_IMPERATIVE" and gold[k]["gold"] != "LEADING_IMPERATIVE" for k in gold)
    fn = sum(gold[k]["gold"] == "LEADING_IMPERATIVE" and not
             (pred[k]["label"] == "LEADING_IMPERATIVE" and
              pred[k]["completed_span"] == gold[k]["sentence"].rstrip(".!? ")) for k in gold)
    result = {"tp_exact": tp, "fp": fp, "fn": fn, "precision": tp/(tp+fp) if tp+fp else 0,
              "recall": tp/(tp+fn) if tp+fn else 0,
              "errors": [{"id": k, "gold": gold[k]["gold"], "pred": pred[k]["label"]}
                         for k in gold if gold[k]["gold"] != pred[k]["label"]]}
    (OUT / "E5_score.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


def rewrite_e3():
    original = OUT / "FRONTEND_imperative_v2"
    dest = OUT / "FRONTEND_imperative_completed"
    dest.mkdir(parents=True, exist_ok=True)
    for p in sorted(original.glob("e_*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        case = next(c for c in json.loads((HERE / "frozen" / "frozen_cases.json").read_text(encoding="utf-8"))
                    if c["case_id"] == data["case_id"])
        for ev in data["events"]:
            if ev.get("dep") != "rescue_imperative":
                continue
            start = ev["span_start"]
            match = next((sentence for st, sentence in sentence_spans(case["policy"]) if st == start), None)
            if match is None:
                raise ValueError((p.name, start))
            ev["llm_short_span"] = ev["span"]
            ev["span"] = complete(match, "LEADING_IMPERATIVE")
            ev["span_end"] = start + len(ev["span"])
        (dest / p.name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(p.stem, sum(x.get("dep") == "rescue_imperative" for x in data["events"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("phase", choices=("e5", "score", "rewrite_e3"))
    {"e5": e5, "score": score, "rewrite_e3": rewrite_e3}[ap.parse_args().phase]()
