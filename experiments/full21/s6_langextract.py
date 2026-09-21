#!/usr/bin/env python3
"""FULL_21 Section 6 (L): Google LangExtract over public46 via LOCAL Mistral backend.

Backend: langextract 1.7 OpenAILanguageModel -> http://127.0.0.1:8002/v1
(local mistral-7b-instruct-v0.3 served by experiments/full21/mini_openai_server.py,
temperature 0, max_workers 1). NO external API is called.

Extraction classes target exactly what the structural parser misses
(directive section 6): policy obligations, exceptions, temporal constraints,
user commitments, textual tool confirmations. Every extraction's char span is
mechanically verified against the source text (exact substring check).

Outputs (append-only, resumable):
  outputs/full21/s6_langextract/records.jsonl  — per case: extractions with
    spans + span_ok flags + counts + latency; NEW facts = extractions whose
    quoted text is NOT represented in the mechanical graph digest.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments" / "superz_fullcycle"))
sys.path.insert(0, str(REPO / "src"))

import langextract as lx
from langextract.providers.openai import OpenAILanguageModel

from g_graph import graph_digest  # noqa: E402
from run_granite_modes import read_cases  # noqa: E402

BASE_URL = "http://127.0.0.1:8002/v1"
MODEL_ID = "mistral-7b-instruct-v0.3"

EXAMPLE = lx.data.ExampleData(
    text=(
        "Policy: The agent must verify the customer's identity before processing "
        "any refund. Refunds over $500 require manager approval, unless the customer "
        "has gold status. Refunds are only possible within 30 days of purchase.\n"
        "User: I bought the laptop on March 3rd and want a refund.\n"
        "Tool result: refund_check -> status=eligible, message='Refund request accepted'"
    ),
    extractions=[
        lx.data.Extraction(
            extraction_class="policy_obligation",
            extraction_text="must verify the customer's identity before processing any refund",
        ),
        lx.data.Extraction(
            extraction_class="policy_exception",
            extraction_text="Refunds over $500 require manager approval, unless the customer has gold status",
        ),
        lx.data.Extraction(
            extraction_class="temporal_constraint",
            extraction_text="Refunds are only possible within 30 days of purchase",
        ),
        lx.data.Extraction(
            extraction_class="user_commitment",
            extraction_text="I bought the laptop on March 3rd and want a refund",
        ),
        lx.data.Extraction(
            extraction_class="tool_confirmation",
            extraction_text="refund_check -> status=eligible, message='Refund request accepted'",
        ),
    ],
)

PROMPT_HINT = (
    "Extract policy obligations, exceptions, temporal constraints, user "
    "commitments, and textual tool confirmations from customer-service agent "
    "transcripts. Extract only text present verbatim in the source."
)


def span_ok(text: str, start: int, end: int, source: str) -> bool:
    if start is None or end is None:
        return False
    if start < 0 or end > len(source) or end <= start:
        return False
    return source[start:end] == text


def new_fact(quote: str, digest: str) -> bool:
    """Heuristic: quote is NEW if no >=24-char verbatim run of it appears in digest."""
    n = len(quote)
    step = 24
    for i in range(0, max(1, n - step + 1), 8):
        frag = quote[i:i + step]
        if frag and frag in digest:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-chars", type=int, default=48000)
    args = ap.parse_args()

    out_dir = Path("outputs/full21/s6_langextract")
    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / "records.jsonl"

    model = OpenAILanguageModel(
        model_id=MODEL_ID, api_key="local-no-key", base_url=BASE_URL,
        temperature=0.0, max_workers=1)

    cases = read_cases(Path(args.input))
    if args.limit:
        cases = cases[:args.limit]

    done = set()
    if rec_path.exists():
        for line in open(rec_path, encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    print(f"resume: {len(done)} done, {len(cases) - len(done)} to go", flush=True)

    stats = {"cases": 0, "extractions": 0, "span_ok": 0, "span_bad": 0,
             "new_facts": 0, "errors": 0}
    with open(rec_path, "a", encoding="utf-8") as fout:
        for case in cases:
            cid = case["id"]
            if cid in done:
                continue
            t0 = time.perf_counter()
            source = case["prompt"][:args.max_chars]
            try:
                result = lx.extract(
                    source,
                    prompt_description=PROMPT_HINT,
                    examples=[EXAMPLE],
                    model=model,
                    show_progress=False,
                )
                if isinstance(result, list):
                    docs = [d for d in result if d is not None]
                    result = docs[0] if docs else None
                raw_extractions = list(getattr(result, "extractions", []) or []) if result else []
                extractions = []
                for ex in raw_extractions:
                    cls = getattr(ex, "extraction_class", None)
                    txt = getattr(ex, "extraction_text", None)
                    interval = getattr(ex, "char_interval", None)
                    start = getattr(interval, "start_pos", None) if interval else None
                    end = getattr(interval, "end_pos", None) if interval else None
                    ok = span_ok(txt, start, end, source) if txt else False
                    extractions.append({
                        "class": cls, "text": txt,
                        "start": start, "end": end, "span_ok": ok,
                    })
                try:
                    digest = graph_digest(case["prompt"], case["response"])
                except Exception:
                    digest = ""
                for e in extractions:
                    e["is_new_vs_graph"] = bool(e["span_ok"] and new_fact(e["text"] or "", digest))
                rec = {
                    "id": cid, "n_extractions": len(extractions),
                    "n_span_ok": sum(1 for e in extractions if e["span_ok"]),
                    "n_new_vs_graph": sum(1 for e in extractions if e.get("is_new_vs_graph")),
                    "latency_s": round(time.perf_counter() - t0, 2),
                    "extractions": extractions,
                }
                stats["extractions"] += len(extractions)
                stats["span_ok"] += rec["n_span_ok"]
                stats["span_bad"] += len(extractions) - rec["n_span_ok"]
                stats["new_facts"] += rec["n_new_vs_graph"]
            except Exception as e:
                stats["errors"] += 1
                rec = {"id": cid, "error": f"{type(e).__name__}: {e}",
                       "latency_s": round(time.perf_counter() - t0, 2)}
            stats["cases"] += 1
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            print(f"[s6] {cid}: {rec.get('n_extractions', 'ERR')} extr, "
                  f"{rec.get('n_span_ok', 0)} span_ok, {rec.get('n_new_vs_graph', 0)} new "
                  f"({rec.get('latency_s', '?')}s)", flush=True)

    (out_dir / "summary.json").write_text(json.dumps({
        **stats, "backend": f"local {MODEL_ID} via {BASE_URL}",
        "input": args.input, "max_chars": args.max_chars,
    }, indent=1))
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
