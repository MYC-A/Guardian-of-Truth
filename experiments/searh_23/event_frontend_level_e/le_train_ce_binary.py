"""Second controlled CE: retain the pretrained bge one-logit reranker head.

Guardian old dev trains LoRA with class-weighted BCE; old val selects epoch;
old calib selects conservative threshold. Level E inputs are read only by test.
RELATED and DIFFERENT both count as negative, with dangerous false positives
reported separately. This is a SAME-vs-rest ablation of the 3-way model.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from le_train_ce import old_rows, text_pair, batcher, FROZEN, BASE_MODEL

OUT = HERE / "outputs" / "CE_BINARY"
SEED = 20260928


def model_and_tok(adapter=None):
    import torch
    from peft import LoraConfig, TaskType, get_peft_model, PeftModel
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(BASE_MODEL, cache_dir="/workspace/guardian/hf_cache")
    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL, cache_dir="/workspace/guardian/hf_cache")
    if adapter:
        model = PeftModel.from_pretrained(model, adapter)
    else:
        model = get_peft_model(model, LoraConfig(task_type=TaskType.SEQ_CLS,
            r=8, lora_alpha=16, lora_dropout=0.05, target_modules=["query", "value"]))
    model.to("cuda" if torch.cuda.is_available() else "cpu")
    return model, tok


def predict(model, tok, rows):
    import torch
    model.eval(); out = []
    with torch.no_grad():
        for group, enc in batcher(rows, tok, 16):
            enc = {k: v.to(model.device) for k, v in enc.items()}
            probs = model(**enc).logits.float().flatten().sigmoid().cpu().tolist()
            out.extend({"id": r["id"], "prob_same": p, "gold": r.get("label")} for r, p in zip(group, probs))
    return out


def stats(rows, t):
    tp = sum(r["prob_same"] >= t and r["gold"] == "SAME_EVENT" for r in rows)
    fp = sum(r["prob_same"] >= t and r["gold"] != "SAME_EVENT" for r in rows)
    fn = sum(r["prob_same"] < t and r["gold"] == "SAME_EVENT" for r in rows)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": tp/(tp+fp) if tp+fp else 0,
            "recall": tp/(tp+fn) if tp+fn else 0,
            "dangerous": sum(r["prob_same"] >= t and r["gold"] == "RELATED_BUT_DIFFERENT" for r in rows)}


def train():
    import torch
    torch.manual_seed(SEED); random.seed(SEED)
    train_rows, val_rows = old_rows("dev"), old_rows("val")
    if {r["case_id"] for r in train_rows} & {r["case_id"] for r in val_rows}:
        raise ValueError("group leakage")
    model, tok = model_and_tok()
    positives = sum(r["label"] == "SAME_EVENT" for r in train_rows)
    weight = torch.tensor((len(train_rows)-positives)/positives, device=model.device)
    optim = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-4)
    OUT.mkdir(parents=True, exist_ok=True)
    history = []
    for epoch in range(1, 9):
        model.train(); losses = []
        for group, enc in batcher(train_rows, tok, 8, shuffle=True):
            enc = {k: v.to(model.device) for k, v in enc.items()}
            labels = torch.tensor([r["label"] == "SAME_EVENT" for r in group],
                                  dtype=torch.float32, device=model.device)
            optim.zero_grad(set_to_none=True)
            logits = model(**enc).logits.float().flatten()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, labels, pos_weight=weight)
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step(); losses.append(float(loss.detach().cpu()))
        val = predict(model, tok, val_rows)
        entry = {"epoch": epoch, "train_loss": sum(losses)/len(losses), **stats(val, 0.5)}
        history.append(entry)
        model.save_pretrained(OUT / f"epoch_{epoch}")
        (OUT / f"val_epoch_{epoch}.json").write_text(json.dumps(val, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(entry), flush=True)
    best = max(history, key=lambda r: (r["precision"], -r["dangerous"], r["recall"], -r["epoch"]))
    config = {"base_model": BASE_MODEL, "seed": SEED, "train_count": len(train_rows),
              "train_positive": positives, "val_count": len(val_rows),
              "history": history, "selected_epoch": best["epoch"],
              "selection": "max val precision, min dangerous, max recall, earliest"}
    (OUT / "training_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected_epoch": best["epoch"]}), flush=True)


def calibrate():
    config = json.loads((OUT / "training_config.json").read_text(encoding="utf-8"))
    model, tok = model_and_tok(OUT / f"epoch_{config['selected_epoch']}")
    rows = predict(model, tok, old_rows("calib"))
    (OUT / "calib_probs.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    options = [{"threshold": t, **stats(rows, t)} for t in (0.25, 0.35, 0.5, 0.65, 0.75, 0.85, 0.95)]
    best = max(options, key=lambda r: (r["precision"], -r["dangerous"], r["tp"], r["threshold"]))
    config["calibration"] = {"threshold": best["threshold"], "options": options,
                             "selection": "max precision, min dangerous, max TP, max threshold"}
    (OUT / "selected_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(config["calibration"], flush=True))


def test():
    config = json.loads((OUT / "selected_config.json").read_text(encoding="utf-8"))
    model, tok = model_and_tok(OUT / f"epoch_{config['selected_epoch']}")
    rows = json.loads((FROZEN / "identity_inputs.json").read_text(encoding="utf-8"))
    pred = predict(model, tok, rows)
    t = config["calibration"]["threshold"]
    for r in pred:
        r["label"] = "SAME_EVENT" if r["prob_same"] >= t else "UNKNOWN"
        del r["gold"]
    (OUT / "sealed_test_predictions.json").write_text(json.dumps(pred, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"n": len(pred), "threshold": t}), flush=True)


def score():
    gold = json.loads((FROZEN / "identity_gold.json").read_text(encoding="utf-8"))
    rows = json.loads((OUT / "sealed_test_predictions.json").read_text(encoding="utf-8"))
    if {r["id"] for r in rows} != set(gold):
        raise ValueError("incomplete predictions")
    for r in rows:
        r["gold"] = gold[r["id"]]
    tp = sum(r["label"] == "SAME_EVENT" and r["gold"] == "SAME_EVENT" for r in rows)
    fp = sum(r["label"] == "SAME_EVENT" and r["gold"] != "SAME_EVENT" for r in rows)
    fn = sum(r["label"] != "SAME_EVENT" and r["gold"] == "SAME_EVENT" for r in rows)
    result = {"tp": tp, "fp": fp, "fn": fn, "precision": tp/(tp+fp) if tp+fp else 0,
              "recall": tp/(tp+fn) if tp+fn else 0,
              "dangerous": sum(r["label"] == "SAME_EVENT" and r["gold"] == "RELATED_BUT_DIFFERENT" for r in rows),
              "unknown": sum(r["label"] == "UNKNOWN" for r in rows)}
    (OUT / "sealed_test_score.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("phase", choices=("train", "calibrate", "test", "score"))
    {"train": train, "calibrate": calibrate, "test": test, "score": score}[ap.parse_args().phase]()
