#!/usr/bin/env python3
"""SEARCH_23 §8 demo: frozen primary candidate = OR(structural Guardian, granite 3.3 groundedness).

Works on NEW inputs (any CSV with id,prompt,response — no recorded answers needed).
Channels (both frozen exactly as audited on public46):
  1. structural Guardian: guardian_truth.pipeline.Detector(all checks) +
     decision.decide(threshold=0.5, use_semantic=False, unknown_label=0) -> label
     (validated 12/12 vs frozen baseline labels before this demo was written)
  2. granite-guardian-3.3-8b groundedness, doc mode, max_context_chars=12000
     (2/5 prompt + 3/5 response head-tail bounding), temperature 0, think=false,
     <score> yes -> label 1 (byte-compatible with the control runner)
Aggregation: label = structural OR granite (the audited OR control, F1 .8889 on public46).
Output: per-case label + per-channel trace (findings/status, score, truncation, latency).

Usage:
  venv/bin/python experiments/searh_23/demo_frozen.py --input <cases.csv> \
      [--model-path /mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda] \
      [--limit N] [--out outputs/searh_23/demo/out.json]
"""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "experiments/full21"))

from guardian_truth.decision import decide  # noqa: E402
from guardian_truth.pipeline import Detector  # noqa: E402
from run_granite_modes import GraniteLocalRunner, SCORE_RE, bound_pair  # noqa: E402

DEFAULT_MODEL = "/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda"


def parse_score(text):
    m = SCORE_RE.search(text)
    if not m:
        return None
    return 1 if m.group(1).strip().lower() == "yes" else 0


def granite_label(runner, prompt, response, max_context_chars=12000, max_new_tokens=200):
    t0 = time.perf_counter()
    prompt_b, response_b = bound_pair(prompt, response, max_context_chars)
    messages = [{"role": "assistant", "content": response_b.text}]
    chat = runner.tokenizer.apply_chat_template(
        messages, guardian_config={"criteria_id": "groundedness"},
        documents=[{"doc_id": "prompt_context", "text": prompt_b.text}],
        think=False, tokenize=False, add_generation_prompt=True)
    gen = runner.generate(chat, max_new_tokens)
    risk = parse_score(gen["text"])
    return {"label": risk, "status": "ok" if risk is not None else "no_score_token",
            "probabilistic_score": gen.get("probabilistic_score"),
            "input_token_count": gen["input_token_count"],
            "bounded_chars": {"prompt": prompt_b.kept_chars, "response": response_b.kept_chars},
            "truncated": prompt_b.truncated or response_b.truncated,
            "raw_excerpt": gen["text"][:200],
            "latency_s": round(time.perf_counter() - t0, 2)}


def structural_label(prompt, response):
    t0 = time.perf_counter()
    det = Detector()
    rev = det.review(prompt, response)
    d = decide(rev, threshold=0.5, use_semantic=False, unknown_label=0)
    return {"label": int(d.label), "status": rev.status,
            "used_fallback": bool(d.used_fallback), "reason": d.reason,
            "n_findings": len(rev.findings), "n_obligations": len(rev.obligations),
            "n_unresolved": len(rev.unresolved),
            "findings_excerpt": [str(f)[:120] for f in rev.findings[:3]],
            "latency_s": round(time.perf_counter() - t0, 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="CSV with id,prompt,response")
    ap.add_argument("--model-path", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    csv.field_size_limit(2 ** 30)
    cases = list(csv.DictReader(open(args.input, encoding="utf-8-sig", newline="")))
    if args.limit:
        cases = cases[:args.limit]

    runner = GraniteLocalRunner(Path(args.model_path))
    results = []
    for c in cases:
        s = structural_label(c["prompt"], c["response"])
        g = granite_label(runner, c["prompt"], c["response"])
        label = int(s["label"] == 1 or g["label"] == 1)
        rec = {"id": c["id"], "label": label,
               "aggregation": "structural OR granite",
               "channels": {"structural": s, "granite": g}}
        results.append(rec)
        print(f"[demo] {c['id']}: label={label} "
              f"(structural={s['label']} [{s['status']}], granite={g['label']} "
              f"[{g['status']}, score={g['probabilistic_score']}])", flush=True)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"written {len(results)} results to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
