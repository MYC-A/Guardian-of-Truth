"""EVENT_CANON_v1 - local arms over GOLD mentions (Track A).

Arms (zero-shot, no training):
  A_lex  : trivial lexical baseline (LemmaECR heuristic analogue) - SAME if
           content-lemma overlap >= 0.5 (min side), else DIFFERENT. Floor.
  B_emb  : bge-base-en-v1.5 cosine; two variants recorded:
           B1 span-only, B2 span + containing sentence. Raw scores; labels
           applied by the scorer with dev-frozen thresholds.
  C_ce   : bge-reranker-base CrossEncoder zero-shot, bidirectional mean.
  D_ud   : stanza UD event signature + deterministic comparison
           (voice-agnostic, polarity/entity conflicts block merge).
  G_nli  : cross-encoder/nli-deberta-v3-base zero-shot (entailment /
           contradiction / neutral) over concatenated local contexts.

Output: outputs/ARMS/<arm>/<case_id>.json (pairs with scores/labels).
Run for original + renamed suites (rename stability).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from ec_common import load_suite, out_dir, write_usage, sentence_of_span
from ec_feats import (content_tokens, overlap_coeff, ud_signature,
                      signature_compare, _WORD_RE)
import numpy as np

A_OVERLAP = 0.5  # frozen a priori: min-side content overlap for arm A


def run_arm_a(case):
    out = []
    ms = case["mentions"]
    toks = {m["mid"]: set(content_tokens(m["span"])) for m in ms}
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            a, b = ms[i], ms[j]
            ov = overlap_coeff(toks[a["mid"]], toks[b["mid"]])
            label = "SAME_EVENT" if ov >= A_OVERLAP else "DIFFERENT"
            out.append({"a": a["mid"], "b": b["mid"], "label": label,
                        "overlap": round(ov, 4)})
    return out


def encode_bge(model, texts):
    return model.encode(texts, batch_size=32, normalize_embeddings=True,
                        show_progress_bar=False)


def run_arm_b(case, enc_span, enc_ctx):
    policy = case["policy"]
    ms = case["mentions"]
    spans = [m["span"] for m in ms]
    ctxs = []
    for m in ms:
        s, k = sentence_of_span(policy, m["start"])
        ctxs.append(f"{m['span']} || {s}")
    V1 = encode_bge(enc_span, spans)
    V2 = encode_bge(enc_ctx, ctxs)
    out = []
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            out.append({"a": ms[i]["mid"], "b": ms[j]["mid"],
                        "sim_span": round(float(V1[i] @ V1[j]), 4),
                        "sim_ctx": round(float(V2[i] @ V2[j]), 4)})
    return out, V1


def run_arm_c(case, ce):
    policy = case["policy"]
    ms = case["mentions"]
    inputs = []
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            a, b = ms[i], ms[j]
            sa, _ = sentence_of_span(policy, a["start"])
            sb, _ = sentence_of_span(policy, b["start"])
            q = f'Do these two policy text mentions refer to the same single event? Mention 1: "{a["span"]}". Mention 2: "{b["span"]}".'
            passage = f'Mention 1 appears in: {sa} Mention 2 appears in: {sb}'
            inputs.append((q, passage))
            inputs.append((q, passage))
    scores = ce.predict(inputs, batch_size=32, convert_to_numpy=True) if inputs else []
    out = []
    k = 0
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            s1 = float(scores[k]) if k < len(scores) else 0.0
            s2 = float(scores[k + 1]) if k + 1 < len(scores) else 0.0
            k += 2
            out.append({"a": ms[i]["mid"], "b": ms[j]["mid"],
                        "ce": round((s1 + s2) / 2, 4)})
    return out


def run_arm_d(case, nlp):
    doc = nlp(case["policy"])
    sigs = {m["mid"]: ud_signature(case["policy"], doc, m["start"], m["end"])
            for m in case["mentions"]}
    out = []
    ms = case["mentions"]
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            label, reason = signature_compare(sigs[ms[i]["mid"]],
                                              sigs[ms[j]["mid"]])
            out.append({"a": ms[i]["mid"], "b": ms[j]["mid"], "label": label,
                        "reason": reason})
    return out, sigs


def run_arm_g(case, nli_model, nli_tok, device):
    policy = case["policy"]
    ms = case["mentions"]
    import torch
    pairs_txt = []
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            a, b = ms[i], ms[j]
            sa, _ = sentence_of_span(policy, a["start"])
            sb, _ = sentence_of_span(policy, b["start"])
            pairs_txt.append((sa or a["span"], sb or b["span"]))
    if not pairs_txt:
        return []
    enc = nli_tok(pairs_txt, padding=True, truncation=True, max_length=256,
                  return_tensors="pt").to(device)
    with torch.no_grad():
        logits = nli_model(**enc).logits
    probs = torch.softmax(logits, dim=-1).cpu().numpy()
    # nli-deberta-v3-base label order: [contradiction, neutral, entailment]
    out = []
    k = 0
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            p = probs[k]
            k += 1
            out.append({"a": ms[i]["mid"], "b": ms[j]["mid"],
                        "nli_contra": round(float(p[0]), 4),
                        "nli_neutral": round(float(p[1]), 4),
                        "nli_entail": round(float(p[2]), 4)})
    return out


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "original"
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer
    import stanza
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    device = "cuda"
    enc_span = SentenceTransformer("BAAI/bge-base-en-v1.5", device=device,
                                   cache_folder="/workspace/guardian/hf_cache")
    enc_ctx = enc_span
    ce = CrossEncoder("BAAI/bge-reranker-base", device=device, max_length=512,
                      cache_folder="/workspace/guardian/hf_cache")
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)
    nli_tok = AutoTokenizer.from_pretrained(
        "cross-encoder/nli-deberta-v3-base",
        cache_dir="/workspace/guardian/hf_cache")
    nli_model = AutoModelForSequenceClassification.from_pretrained(
        "cross-encoder/nli-deberta-v3-base",
        cache_dir="/workspace/guardian/hf_cache").to(device).eval()

    suite = load_suite(which)
    t0 = time.time()
    for case in suite:
        cid_ = case["case_id"]
        base = out_dir(f"ARMS_{which}")
        # A
        p = base / "A_lex" / f"{cid_}.json"
        if not p.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(run_arm_a(case), ensure_ascii=False))
        # B (+ embedding cache for blocking)
        p = base / "B_emb" / f"{cid_}.json"
        if not p.is_file():
            recs, V1 = run_arm_b(case, enc_span, enc_ctx)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(recs, ensure_ascii=False))
            np.save(base / "B_emb" / f"{cid_}.npy", V1)
        # C
        p = base / "C_ce" / f"{cid_}.json"
        if not p.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(run_arm_c(case, ce), ensure_ascii=False))
        # D (+ signature cache for arm E comparator reuse)
        p = base / "D_ud" / f"{cid_}.json"
        if not p.is_file():
            recs, sigs = run_arm_d(case, nlp)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(recs, ensure_ascii=False))
            (base / "D_ud" / f"{cid_}_sigs.json").write_text(
                json.dumps(sigs, ensure_ascii=False))
        # G
        p = base / "G_nli" / f"{cid_}.json"
        if not p.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(run_arm_g(case, nli_model, nli_tok, device),
                                    ensure_ascii=False))
        print(f"[{cid_}] arms done", flush=True)
    write_usage(f"ARMS_{which}", {"wall_seconds": round(time.time() - t0, 1),
                                   "llm_calls": 0})
    print(f"local arms done ({which})")


if __name__ == "__main__":
    main()
