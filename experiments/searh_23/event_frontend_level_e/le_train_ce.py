"""Guardian-only 3-way LoRA CrossEncoder: old dev TRAIN/VAL/CALIB -> new E TEST.

No Level E gold is imported by train or calibration. Full base weights remain
the public BAAI/bge-reranker-base checkpoint; only a small LoRA adapter and
classification head are saved. Group split is by old policy/domain.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
EC = HERE.parent / "event_canon_v1"
sys.path.insert(0, str(EC))
from ec_common import local_context

OUT = HERE / "outputs" / "CE_GUARDIAN"
FROZEN = HERE / "frozen"
OLD = EC / "frozen"
BASE_MODEL = "BAAI/bge-reranker-base"
CLASSES = ["DIFFERENT", "RELATED_BUT_DIFFERENT", "SAME_EVENT"]
CID = {x: i for i, x in enumerate(CLASSES)}
SEED = 20260928


def old_rows(split: str) -> list[dict]:
    cases = [c for c in json.loads((OLD / "frozen_cases.json").read_text(encoding="utf-8")) if c["split"] == split]
    pairs = json.loads((OLD / "pairs_gold.json").read_text(encoding="utf-8"))
    rows = []
    for c in cases:
        by_mid = {m["mid"]: m for m in c["mentions"]}
        for p in pairs[c["case_id"]]:
            if p["label"] == "AMBIGUOUS":
                continue
            a, b = by_mid[p["a"]], by_mid[p["b"]]
            rows.append({"id": f"{c['case_id']}::{p['a']}::{p['b']}", "case_id": c["case_id"],
                         "policy": c["policy"], "a": a, "b": b, "label": p["label"]})
    return rows


def text_pair(r: dict) -> tuple[str, str]:
    a, b, policy = r["a"], r["b"], r["policy"]
    return (f"Event mention: {a['span']} Context: {local_context(policy, a['start'], 1)}",
            f"Event mention: {b['span']} Context: {local_context(policy, b['start'], 1)}")


def model_and_tokenizer(adapter: Path | None = None):
    import torch
    from peft import LoraConfig, TaskType, get_peft_model, PeftModel
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(BASE_MODEL, cache_dir="/workspace/guardian/hf_cache")
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=3, ignore_mismatched_sizes=True,
        cache_dir="/workspace/guardian/hf_cache")
    if adapter:
        model = PeftModel.from_pretrained(model, adapter)
    else:
        config = LoraConfig(task_type=TaskType.SEQ_CLS, r=8, lora_alpha=16,
                            lora_dropout=0.05, target_modules=["query", "value"])
        model = get_peft_model(model, config)
    model.to("cuda" if torch.cuda.is_available() else "cpu")
    return model, tok


def batcher(rows, tokenizer, batch_size, *, shuffle=False):
    indices = list(range(len(rows)))
    if shuffle:
        random.shuffle(indices)
    for p in range(0, len(indices), batch_size):
        group = [rows[i] for i in indices[p:p+batch_size]]
        pairs = [text_pair(r) for r in group]
        enc = tokenizer([a for a, _ in pairs], [b for _, b in pairs],
                        max_length=256, padding=True, truncation=True, return_tensors="pt")
        yield group, enc


def predict(model, tokenizer, rows):
    import torch
    model.eval()
    out = []
    with torch.no_grad():
        for group, enc in batcher(rows, tokenizer, 16):
            enc = {k: v.to(model.device) for k, v in enc.items()}
            probs = model(**enc).logits.float().softmax(-1).cpu().tolist()
            out.extend({"id": r["id"], "probs": q, "gold": r.get("label")} for r, q in zip(group, probs))
    return out


def classification_stats(rows):
    tp = sum(x["probs"].index(max(x["probs"])) == CID["SAME_EVENT"] and x["gold"] == "SAME_EVENT" for x in rows)
    fp = sum(x["probs"].index(max(x["probs"])) == CID["SAME_EVENT"] and x["gold"] != "SAME_EVENT" for x in rows)
    fn = sum(x["probs"].index(max(x["probs"])) != CID["SAME_EVENT"] and x["gold"] == "SAME_EVENT" for x in rows)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": tp/(tp+fp) if tp+fp else 0,
            "recall": tp/(tp+fn) if tp+fn else 0}


def train():
    import torch
    torch.manual_seed(SEED); random.seed(SEED)
    train_rows, val_rows = old_rows("dev"), old_rows("val")
    train_ids = {r["case_id"] for r in train_rows}
    val_ids = {r["case_id"] for r in val_rows}
    if train_ids & val_ids:
        raise ValueError("group leakage")
    model, tok = model_and_tokenizer()
    counts = Counter(r["label"] for r in train_rows)
    weights = torch.tensor([math.sqrt(len(train_rows)/max(1, counts[x])) for x in CLASSES],
                           dtype=torch.float32, device=model.device)
    optim = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4)
    OUT.mkdir(parents=True, exist_ok=True)
    history = []
    for epoch in range(1, 4):
        model.train(); losses = []
        for group, enc in batcher(train_rows, tok, 8, shuffle=True):
            enc = {k: v.to(model.device) for k, v in enc.items()}
            labels = torch.tensor([CID[r["label"]] for r in group], device=model.device)
            optim.zero_grad(set_to_none=True)
            logits = model(**enc).logits.float()
            loss = torch.nn.functional.cross_entropy(logits, labels, weight=weights)
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step(); losses.append(float(loss.detach().cpu()))
        val = predict(model, tok, val_rows)
        stats = classification_stats(val)
        entry = {"epoch": epoch, "train_loss": sum(losses)/len(losses), **stats}
        history.append(entry)
        adapter = OUT / f"epoch_{epoch}"
        model.save_pretrained(adapter)
        (OUT / f"val_epoch_{epoch}.json").write_text(json.dumps(val, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(entry), flush=True)
    best = max(history, key=lambda x: (x["precision"], x["recall"], -x["epoch"]))
    config = {"base_model": BASE_MODEL, "seed": SEED, "train_cases": sorted(train_ids),
              "dev_cases": sorted(val_ids), "calib_cases": sorted({r["case_id"] for r in old_rows("calib")}),
              "sealed_test_cases": 10, "class_names": CLASSES, "class_counts": counts,
              "epochs": history, "selected_epoch": best["epoch"],
              "selection": "max SAME precision, then recall, then earliest epoch"}
    (OUT / "training_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected_epoch": best["epoch"], "val": best}), flush=True)


def calibrate():
    config = json.loads((OUT / "training_config.json").read_text(encoding="utf-8"))
    model, tok = model_and_tokenizer(OUT / f"epoch_{config['selected_epoch']}")
    rows = predict(model, tok, old_rows("calib"))
    (OUT / "calib_probs.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    options = []
    for t in (0.50, 0.60, 0.70, 0.80, 0.90, 0.95):
        positives = [r for r in rows if r["probs"][CID["SAME_EVENT"]] >= t and
                     r["probs"][CID["SAME_EVENT"]] == max(r["probs"])]
        tp = sum(r["gold"] == "SAME_EVENT" for r in positives)
        fp = len(positives) - tp
        dangerous = sum(r["gold"] == "RELATED_BUT_DIFFERENT" for r in positives)
        options.append({"threshold": t, "tp": tp, "fp": fp, "dangerous": dangerous,
                        "precision": tp/len(positives) if positives else 0})
    best = max(options, key=lambda x: (x["precision"], -x["dangerous"], x["tp"], x["threshold"]))
    config["calibration"] = {"threshold": best["threshold"], "options": options,
                              "rule": "max SAME precision, min dangerous, max TP, max threshold"}
    (OUT / "selected_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(config["calibration"], indent=2), flush=True)


def test():
    config = json.loads((OUT / "selected_config.json").read_text(encoding="utf-8"))
    model, tok = model_and_tokenizer(OUT / f"epoch_{config['selected_epoch']}")
    rows = json.loads((FROZEN / "identity_inputs.json").read_text(encoding="utf-8"))
    raw = predict(model, tok, rows)
    t = config["calibration"]["threshold"]
    for r in raw:
        q = r["probs"]
        top = CLASSES[q.index(max(q))]
        r["label"] = "SAME_EVENT" if top == "SAME_EVENT" and q[CID["SAME_EVENT"]] >= t else (
            "UNKNOWN" if top == "SAME_EVENT" else top)
        r.pop("gold", None)
    dst = OUT / "sealed_test_predictions.json"
    dst.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(raw), "threshold": t, "adapter_epoch": config["selected_epoch"]}), flush=True)


def score():
    gold = json.loads((FROZEN / "identity_gold.json").read_text(encoding="utf-8"))
    rows = json.loads((OUT / "sealed_test_predictions.json").read_text(encoding="utf-8"))
    if {r["id"] for r in rows} != set(gold):
        raise ValueError("prediction IDs mismatch")
    tp = sum(r["label"] == "SAME_EVENT" and gold[r["id"]] == "SAME_EVENT" for r in rows)
    fp = sum(r["label"] == "SAME_EVENT" and gold[r["id"]] != "SAME_EVENT" for r in rows)
    fn = sum(r["label"] != "SAME_EVENT" and gold[r["id"]] == "SAME_EVENT" for r in rows)
    out = {"tp": tp, "fp": fp, "fn": fn, "precision": tp/(tp+fp) if tp+fp else 0,
           "recall": tp/(tp+fn) if tp+fn else 0,
           "dangerous": sum(r["label"] == "SAME_EVENT" and gold[r["id"]] == "RELATED_BUT_DIFFERENT" for r in rows),
           "unknown": sum(r["label"] == "UNKNOWN" for r in rows)}
    (OUT / "sealed_test_score.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("phase", choices=("train", "calibrate", "test", "score")); phase = ap.parse_args().phase
    {"train": train, "calibrate": calibrate, "test": test, "score": score}[phase]()
