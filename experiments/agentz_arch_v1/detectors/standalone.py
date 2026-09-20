"""Standalone claim-level faithfulness detectors (local, CPU).

1. MiniCheck (lytang/MiniCheck-RoBERTa-Large) - document/claim grounding score.
2. LettuceDetect (kornw01/lettucedetect-base-european or -modernbert-large) -
   hallucination span detection given context + answer.

Usage in this project: claim-level signal for the FINAL RESPONSE only.
Input row -> (context = prompt, answer = response). For long contexts we test
three strategies per the research plan:
  T1 truncation (head+tail window)
  T2 chunking (split into K chunks, max-aggregate scores)
  T3 relevance selection (lexical BM25 top sentences around response entities)
Also: Russian support probe (public46 responses are RU) - documented separately.
"""
import sys, json, gc, re, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.io_utils import load_dataset, prf, save_result

OUT = Path("/home/z/my-project/got-agentz/outputs/agentz")


# ---------------- context strategies ----------------

def ctx_truncate(prompt, max_chars=6000):
    if len(prompt) <= max_chars:
        return prompt
    return prompt[:int(max_chars * 0.5)] + "\n[...]\n" + prompt[-int(max_chars * 0.5):]


def ctx_chunks(prompt, chunk_chars=3000, max_chunks=6):
    """Split on segment markers; keep head/tail chunks (budgeted)."""
    parts = re.split(r"(?=\u27e6)", prompt)  # split before segment markers
    buf, chunks = "", []
    for p in parts:
        if len(buf) + len(p) > chunk_chars and buf:
            chunks.append(buf)
            buf = p
        else:
            buf += p
    if buf:
        chunks.append(buf)
    if len(chunks) <= max_chunks:
        return chunks
    half = max_chunks // 2
    return chunks[:half] + chunks[-half:]


def ctx_relevant(prompt, response, max_chars=4000):
    """Lexical relevance: rank sentences by overlap with response content words."""
    stop = set("the a an and or of to in for is are was were be been with on at as by from you your we our i my it this that not no yes".split())
    words = set(re.findall(r"[A-Za-z\u0400-\u04FF]{3,}", response.lower())) - stop
    sents = re.split(r"(?<=[.!?])\s+|\n+", prompt)
    scored = []
    for s in sents:
        sw = set(re.findall(r"[A-Za-z\u0400-\u04FF]{3,}", s.lower()))
        if not sw:
            continue
        score = len(words & sw)
        if score:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    sel, total = [], 0
    for _, s in scored:
        if total + len(s) > max_chars:
            break
        sel.append(s)
        total += len(s)
    return "\n".join(sel) if sel else ctx_truncate(prompt, max_chars)


# ---------------- MiniCheck ----------------

def minicheck_model():
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    name = "lytang/MiniCheck-RoBERTa-Large"
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForSequenceClassification.from_pretrained(name, torch_dtype="float32")
    model.eval()
    return tok, model


def minicheck_score(tok, model, doc, claim):
    """1 = grounded/supported, 0 = not supported (MiniCheck convention)."""
    import torch
    inputs = tok(claim, doc, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        logits = model(**inputs).logits
        prob = torch.softmax(logits, dim=1)[0]
    return float(prob[1])


# ---------------- LettuceDetect ----------------

def lettuce_model():
    from lettucedetect.models.inference import HallucinationDetector
    det = HallucinationDetector(method="transformer",
                                model_path="KRLabsOrg/lettucedect-base-modernbert-en-v1")
    return det


# ---------------- runners ----------------

def run_minicheck(dataset, strategy="truncate", limit=None):
    rows = load_dataset(dataset)
    if limit:
        rows = rows[:limit]
    tok, model = minicheck_model()
    preds, details = {}, {}
    t0 = time.time()
    for i, r in enumerate(rows):
        resp = r["response"]
        # response as claim(s): split text part; skip pure tool calls (note in details)
        claim = re.sub(r"→\s*TOOL_CALL[^←]*", " ", resp, flags=re.S).strip() or resp
        if strategy == "truncate":
            docs = [ctx_truncate(r["prompt"])]
        elif strategy == "chunk":
            docs = ctx_chunks(r["prompt"])
        else:
            docs = [ctx_relevant(r["prompt"], resp)]
        scores = [minicheck_score(tok, model, d, claim[:1500]) for d in docs]
        agg_max = max(scores)
        agg_min = min(scores)
        preds[r["id"]] = 1 if agg_max < 0.5 else 0   # unsupported claim => error
        details[r["id"]] = {"scores": [round(s, 4) for s in scores],
                            "max": round(agg_max, 4), "min": round(agg_min, 4)}
    golds = {r["id"]: r["gold"] for r in rows}
    m = prf(preds, golds)
    m["elapsed_s"] = round(time.time() - t0, 1)
    save_result(f"det_minicheck_{strategy}_{dataset}.json",
                {"detector": "minicheck-roberta-large", "strategy": strategy,
                 "dataset": dataset, "metrics": m, "preds": preds, "details": details})
    print(f"MiniCheck/{strategy}/{dataset}: {m}")
    del tok, model
    gc.collect()


def run_lettuce(dataset, limit=None):
    rows = load_dataset(dataset)
    if limit:
        rows = rows[:limit]
    det = lettuce_model()
    preds, details = {}, {}
    # incremental persistence (resume across process restarts)
    inc_path = OUT / f"det_lettuce_{dataset}.partial.json"
    if inc_path.exists():
        try:
            inc = json.loads(inc_path.read_text())
            preds.update(inc.get("preds", {}))
            details.update(inc.get("details", {}))
        except Exception:
            pass
    t0 = time.time()
    for r in rows:
        if r["id"] in preds:
            continue
        resp = r["response"]
        answer = re.sub(r"→\s*TOOL_CALL[^←]*", " ", resp, flags=re.S).strip() or resp[:1500]
        try:
            probs = []
            span_out = []
            for doc in ctx_chunks(r["prompt"], chunk_chars=2000, max_chunks=2):
                spans = det.predict(context=doc, question="", answer=answer,
                                    output_format="spans")
                for sp in spans:
                    probs.append(sp.get("confidence", 0))
                    span_out.append({"text": sp.get("text", "")[:80],
                                     "prob": round(sp.get("confidence", 0), 3)})
            p = max(probs, default=0.0)
            preds[r["id"]] = 1 if p >= 0.5 else 0
            details[r["id"]] = {"max_prob": round(p, 4),
                                "spans": sorted(span_out, key=lambda x: -x["prob"])[:5]}
        except Exception as e:
            preds[r["id"]] = None
            details[r["id"]] = {"error": str(e)[:200]}
        if time.time() - t0 > 30:
            inc_path.write_text(json.dumps({"preds": preds, "details": details}))
    inc_path.write_text(json.dumps({"preds": preds, "details": details}))
    golds = {r["id"]: r["gold"] for r in rows}
    m = prf(preds, golds)
    m["elapsed_s"] = round(time.time() - t0, 1)
    save_result(f"det_lettuce_{dataset}.json",
                {"detector": "lettucedect-base-modernbert-en-v1", "dataset": dataset,
                 "metrics": m, "preds": preds, "details": details})
    print(f"Lettuce/{dataset}: {m}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    ds = sys.argv[2] if len(sys.argv) > 2 else "synth-dev"
    strat = sys.argv[3] if len(sys.argv) > 3 else "truncate"
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else None
    if cmd == "minicheck":
        run_minicheck(ds, strat, limit)
    elif cmd == "lettuce":
        run_lettuce(ds, limit)
