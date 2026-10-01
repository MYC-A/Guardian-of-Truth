#!/usr/bin/env python3
"""Stage A native-adapter smoke (directive §6, 2026-10-01).

For each AVAILABLE candidate checker: 10-20 smoke examples in its NATIVE
format (never a foreign JSON-judge prompt), tables of format success,
runtime, peak VRAM. Real model answers, not package imports.

Candidates this run:
  * MiniCheck small  — lytang/MiniCheck-Flan-T5-Large (native doc/claim)
  * FactCG           — yaxili96/FactCG-DeBERTa-v3-Large (native ctx/claim)
  * Granite Guardian — local granite-guardian-4.1-8b, BYOC custom POLICY
                       criterion (verbatim policy requirement + question
                       about the current move's error) — distinct from the
                       historical groundedness run.
BLOCKED (measured, not guessed): Bespoke-MiniCheck-7B (~15 GB weights) and
policy-reasoning-traces Qwen-7B (~15 GB) do not fit the 8.7 GB free disk
alongside the 16 GB granite checkout; recorded in the summary.

The smoke bank = 15 doc/claim pairs of OUR problem shape with expected
labels written from the doc text itself (fact support, policy-interpretation
support, applicability). Labels are for SMOKE diagnostics only — no
threshold is tuned here.

Run on the instance:
  python experiments/searh_23/hybrid_service_v1/smoke_native_adapters.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "outputs" / "native_smoke"
OUT.mkdir(parents=True, exist_ok=True)

GRANITE_PATH = Path("/workspace/guardian/models/granite-guardian-4.1-8b")

# ------------------------------------------------------------------ bank

BANK = [
    # (doc, claim, expected: 1 = supported, 0 = not supported)
    ("TOOL_RESPONSE refund_order: {\"order_id\": \"ORD-1\", \"status\": \"processed\"}",
     "The refund for order ORD-1 was processed.", 1),
    ("TOOL_RESPONSE refund_order: {\"order_id\": \"ORD-1\", \"status\": \"processed\"}",
     "The refund for order ORD-1 failed.", 0),
    ("TOOL_RESPONSE check_status: {\"order_id\": \"ORD-2\", \"status\": \"shipped\"}",
     "Order ORD-1 has shipped.", 0),
    ("Policy: Publishing an archive record requires the record to be "
     "declassified and the archivist's sign-off to be recorded. Publishing "
     "is allowed with only the declassification when the record is marked "
     "as public interest. Reading a record does not publish it.",
     "A record marked as public interest may be published once it is "
     "declassified, even if the sign-off is not recorded.", 1),
    ("Policy: Publishing an archive record requires the record to be "
     "declassified and the archivist's sign-off to be recorded. Publishing "
     "is allowed with only the declassification when the record is marked "
     "as public interest. Reading a record does not publish it.",
     "A record that is not declassified may be published if it is marked "
     "as public interest.", 0),
    ("Policy: Publishing an archive record requires the record to be "
     "declassified and the archivist's sign-off to be recorded. Publishing "
     "is allowed with only the declassification when the record is marked "
     "as public interest. Reading a record does not publish it.",
     "Reading a record counts as publishing it.", 0),
    ("Policy: A parcel may be dispatched only if its inspection passed. "
     "Checking inspection does not dispatch the parcel.",
     "Running the inspection check satisfies the dispatch condition.", 0),
    ("Policy: A parcel may be dispatched only if its inspection passed. "
     "Checking inspection does not dispatch the parcel.",
     "A parcel whose inspection passed may be dispatched.", 1),
    ("TOOL_RESPONSE check_flight: {\"flight\": \"HAT078\", \"status\": \"landed\"}",
     "Flight HAT078 has landed.", 1),
    ("TOOL_RESPONSE check_flight: {\"flight\": \"HAT078\", \"status\": \"landed\"}",
     "Flight HAT078 is still in the air.", 0),
    ("Policy: Only make one tool call at a time. You may make two "
     "read-only calls together.",
     "Two read-only calls in one turn violate the one-call rule.", 0),
    ("Catalog: - check_status — Checks the current status of an order. "
     "- create_refund — Creates a refund for a paid order.",
     "The catalog contains a tool that sends emails to customers.", 0),
    ("Catalog: - check_status — Checks the current status of an order. "
     "- create_refund — Creates a refund for a paid order.",
     "The create_refund tool creates a refund for a paid order.", 1),
    ("TOOL_RESPONSE get_balance: {\"account\": \"A-77\", \"balance\": 120.5}",
     "The balance of account A-77 is 120.5.", 1),
    ("TOOL_RESPONSE get_balance: {\"account\": \"A-77\", \"balance\": 120.5}",
     "The balance of account A-77 is 125.0.", 0),
]


def _acc(preds) -> dict:
    if len(preds) != len(BANK):
        raise ValueError("one prediction is required for each smoke case")
    valid_pairs = [(p, expected) for p, (_, _, expected) in zip(preds, BANK)
                   if p is not None]
    valid = len(valid_pairs)
    return {"format_success": f"{valid}/{len(BANK)}",
            "valid_coverage": round(valid / len(BANK), 3),
            "smoke_acc_on_valid": (round(sum(p == expected for p, expected
                                              in valid_pairs) / valid, 3)
                                   if valid else None),
            "smoke_acc_invalid_as_wrong": round(
                sum(p == expected for p, expected in valid_pairs) / len(BANK), 3)}


# ------------------------------------------------------------- MiniCheck

def smoke_minicheck_small() -> dict:
    """Native MiniCheck-Flan-T5-Large inference (format ported verbatim
    from Liyan06/MiniCheck minicheck/inference.py): input =
    'predict: ' + doc + eos_token + claim; decoder start token 0;
    P(supported) = softmax(logits[:, [3, 209]])[1]; doc chunked to ~500
    words by sentences; max over chunks; label 1 if prob > 0.5."""
    t0 = time.time()
    try:
        import torch  # noqa: PLC0415
        from transformers import (AutoModelForSeq2SeqLM,  # noqa: PLC0415
                                  AutoTokenizer)
    except Exception as e:  # noqa: BLE001
        return {"candidate": "MiniCheck-Flan-T5-Large",
                "status": f"IMPORT_FAIL:{type(e).__name__}",
                "detail": str(e)[:200]}
    try:
        ckpt = "lytang/MiniCheck-Flan-T5-Large"
        tok = AutoTokenizer.from_pretrained(ckpt)
        model = AutoModelForSeq2SeqLM.from_pretrained(
            ckpt, device_map="auto")
        model.eval()
    except Exception as e:  # noqa: BLE001
        return {"candidate": "MiniCheck-Flan-T5-Large",
                "status": f"LOAD_FAIL:{type(e).__name__}",
                "detail": str(e)[:300]}

    def sent_split(text: str) -> list:
        import re as _re
        blocks = text.split("\n")
        out = []
        for b in blocks:
            out.extend(x for x in _re.split(r"(?<=[.!?])\s+", b) if x)
            out.append("\n")
        return out[:-1]

    def word_chunks(sents: list, n: int = 500) -> list:
        cur, cnt = [], 0
        for sent in sents:
            w = len(sent.split())
            if cnt + w > n and cur:
                yield_cur = " ".join(cur)
                cur, cnt = [sent], w
                yield yield_cur
                continue
            cur.append(sent)
            cnt += w
        if cur:
            yield " ".join(cur)

    preds, probs = [], []
    t1 = time.time()
    with torch.inference_mode():
        for doc, claim, _ in BANK:
            chunks = list(word_chunks(sent_split(doc)))
            texts = ["predict: " + tok.eos_token.join([c, claim])
                     for c in chunks]
            enc = tok(texts, max_length=2048, truncation=True,
                      padding=True, return_tensors="pt").to(model.device)
            dec = torch.zeros((enc["input_ids"].size(0), 1),
                              dtype=torch.long).to(model.device)
            logits = model(input_ids=enc["input_ids"],
                           attention_mask=enc["attention_mask"],
                           decoder_input_ids=dec).logits.squeeze(1)
            label_logits = logits[:, torch.tensor([3, 209])].cpu()
            label_probs = torch.softmax(label_logits, dim=-1)[:, 1]
            best = float(label_probs.max().item())
            probs.append(round(best, 4))
            preds.append(1 if best > 0.5 else 0)
    out = {"candidate": "MiniCheck-Flan-T5-Large",
           "native": "predict:+doc</s>claim, decoder0, logits[3,209]",
           "load_s": round(t1 - t0, 1), "infer_s": round(time.time() - t1, 1)}
    out.update(_acc(preds))
    out["support_probs"] = probs
    return out


# ----------------------------------------------------------------- FactCG

def smoke_factcg() -> dict:
    """Compare the author's FactCG input with the old pair-tokenization.

    Both arms use the same pinned checkpoint and the same 15 cases; the old
    prediction is retained as a control rather than silently overwritten.
    """
    t0 = time.time()
    try:
        import torch  # noqa: PLC0415
        from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer  # noqa: PLC0415
        from factcg_native import native_score  # noqa: PLC0415
        name = "yaxili96/FactCG-DeBERTa-v3-Large"
        revision = "0430e3509dbd28d2dff7a117c0eae25359ff3e80"
        try:
            config = AutoConfig.from_pretrained(name, revision=revision,
                                               num_labels=2,
                                               finetuning_task="text-classification")
            config.problem_type = "single_label_classification"
            tok = AutoTokenizer.from_pretrained(name, revision=revision,
                                                use_fast=True)
            model = AutoModelForSequenceClassification.from_pretrained(
                name, config=config, revision=revision,
                ignore_mismatched_sizes=False)
        except Exception as e:  # noqa: BLE001
            return {"candidate": "FactCG-DeBERTa-v3-Large",
                    "status": f"LOAD_FAIL:{type(e).__name__}",
                    "detail": str(e)[:300]}
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device).eval()
        preds, legacy_preds, scores = [], [], []
        t1 = time.time()
        for doc, claim, _ in BANK:
            try:
                score = native_score(model, tok, doc, claim, device)
                scores.append(round(score, 5))
                preds.append(int(score > 0.5))
            except Exception:  # noqa: BLE001
                scores.append(None)
                preds.append(None)
            try:
                # Stage A's former adapter, retained for a paired comparison.
                enc = tok(doc, claim, return_tensors="pt",
                          truncation=True, max_length=512)
                with torch.inference_mode():
                    logits = model(**{k: v.to(device) for k, v in enc.items()}).logits
                pred = int(logits.argmax(-1).item())
                id2label = model.config.id2label
                lab = id2label.get(pred, str(pred)).lower()
                legacy_preds.append(1 if lab in {"supported", "label_1", "entailment", "1"} else 0)
            except Exception:  # noqa: BLE001
                legacy_preds.append(None)
        out = {"candidate": "FactCG-DeBERTa-v3-Large",
               "revision": revision,
               "native": "author template + NLTK 550-word chunks + P(class1) max",
               "load_s": round(t1 - t0, 1),
               "infer_s": round(time.time() - t1, 1)}
        out.update(_acc(preds))
        out["legacy_pair_adapter"] = _acc(legacy_preds)
        out["support_scores"] = scores
        out["per_example"] = [
            {"claim": c[:60], "pred": p, "legacy_pred": lp, "expected": e}
            for p, lp, (_, c, e) in zip(preds, legacy_preds, BANK)]
        return out
    except Exception as e:  # noqa: BLE001
        return {"candidate": "FactCG-DeBERTa-v3-Large",
                "status": f"IMPORT_FAIL:{type(e).__name__}",
                "detail": str(e)[:200]}


# ---------------------------------------------------------------- granite

GUARDIAN_JUDGE_NOTHINK = (
    "<no-think>As a judge agent, assess whether the provided text meets the given "
    "judging criteria using all available information, including conversations, "
    "documents, and tools. Provide your score immediately without explanation. "
    "Output empty </think>\n</think> tags followed by your score in <score></score> tags."
)


def smoke_granite_byoc_policy() -> dict:
    """Granite Guardian 4.1 BYOC with a CUSTOM POLICY criterion: the
    criterion quotes a verifiable policy requirement and asks about the
    current move's error (directive §6: 'критерий должен содержать
    проверяемое требование политики и вопрос об ошибке текущего хода')."""
    t0 = time.time()
    if not GRANITE_PATH.exists():
        return {"candidate": "granite-guardian-4.1-8b (BYOC policy)",
                "status": "MODEL_NOT_FOUND", "path": str(GRANITE_PATH)}
    try:
        import torch  # noqa: PLC0415
        from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415
        tok = AutoTokenizer.from_pretrained(str(GRANITE_PATH),
                                            local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            str(GRANITE_PATH), local_files_only=True, torch_dtype="auto",
            device_map="auto")
        model.eval()
        vram_gb = round(torch.cuda.max_memory_allocated() / 2**30, 1) \
            if torch.cuda.is_available() else None
    except Exception as e:  # noqa: BLE001
        return {"candidate": "granite-guardian-4.1-8b (BYOC policy)",
                "status": f"LOAD_FAIL:{type(e).__name__}",
                "detail": str(e)[:300]}

    def parse_score(text: str):
        m = re.findall(r"<score>\s*(.*?)\s*</score>", text, re.DOTALL)
        if m:
            v = m[0].strip().lower()
            if v.startswith("yes"):
                return "yes"
            if v.startswith("no"):
                return "no"
        low = text.strip().lower()
        if low.startswith("yes"):
            return "yes"
        if low.startswith("no"):
            return "no"
        return None

    preds, raws = [], []
    t1 = time.time()
    for doc, claim, _ in BANK:
        # BYOC custom criterion: verifiable policy/fact requirement + the
        # question about the CURRENT statement's error
        criteria = (
            "A statement about the current move is erroneous if it asserts "
            "an action result or a policy permission that is not supported "
            "by, or contradicts, the provided document. The policy "
            "requirement to check is quoted verbatim in the document.")
        schema = ("If the statement violates the criteria (unsupported or "
                  "contradicted), return 'yes'; otherwise, return 'no'.")
        guardian_block = (f"{GUARDIAN_JUDGE_NOTHINK}\n\n"
                          f"### Criteria: {criteria}\n\n"
                          f"### Scoring Schema: {schema}")
        messages = [{"role": "assistant", "content": claim},
                    {"role": "user", "content": guardian_block}]
        documents = [{"doc_id": "evidence", "text": doc}]
        chat = tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
            documents=documents)
        inputs = tok(chat, add_special_tokens=False,
                     return_tensors="pt").to(model.device)
        with torch.inference_mode():
            gen = model.generate(**inputs, do_sample=False,
                                 max_new_tokens=16,
                                 pad_token_id=tok.eos_token_id)
        text = tok.decode(gen[0][inputs["input_ids"].shape[1]:],
                          skip_special_tokens=False)
        risk = parse_score(text)
        raws.append(text[:60])
        # risk yes = erroneous (unsupported/contradicted) statement;
        # expected 1 = SUPPORTED claim -> 'no'; expected 0 -> 'yes'
        preds.append(1 if risk == "no" else 0 if risk == "yes" else None)
    import torch as _t  # noqa: PLC0415
    vram_gb = round(_t.cuda.max_memory_allocated() / 2**30, 1) \
        if _t.cuda.is_available() else None
    out = {"candidate": "granite-guardian-4.1-8b (BYOC policy)",
           "native": "BYOC guardian block + <score> yes/no",
           "load_s": round(t1 - t0, 1),
           "infer_s": round(time.time() - t1, 1),
           "peak_vram_gb": vram_gb}
    out.update(_acc(preds))
    out["raw_heads"] = raws[:4]
    return out


# ------------------------------------------------------------------ main

def main() -> int:
    results = []
    print("[smoke] MiniCheck small ...", flush=True)
    results.append(smoke_minicheck_small())
    print(json.dumps(results[-1], ensure_ascii=False)[:400], flush=True)
    print("[smoke] FactCG ...", flush=True)
    results.append(smoke_factcg())
    print(json.dumps(results[-1], ensure_ascii=False)[:400], flush=True)
    print("[smoke] Granite BYOC policy ...", flush=True)
    results.append(smoke_granite_byoc_policy())
    print(json.dumps(results[-1], ensure_ascii=False)[:400], flush=True)

    import shutil
    disk_free_gb = round(shutil.disk_usage("/workspace").free / 2**30, 1)
    results.append({
        "candidate": "Bespoke-MiniCheck-7B",
        "status": "BLOCKED:disk",
        "detail": (f"~15 GB weights vs {disk_free_gb} GB free (granite 16 GB "
                   "occupies the volume); retry after a disk decision"),
    })
    results.append({
        "candidate": "policy-reasoning-traces Qwen-7B "
                     "(josephimperial/qwen2.5_7b_all_finetuned_generalist_withpol)",
        "status": "BLOCKED:disk",
        "detail": (f"~15 GB weights vs {disk_free_gb} GB free; same volume "
                   "constraint"),
    })
    summary = {"stage": "native_adapter_smoke", "bank_size": len(BANK),
               "disk_free_gb": disk_free_gb, "results": results}
    (OUT / "smoke_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n[smoke] summary -> {OUT / 'smoke_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
