#!/usr/bin/env python3
"""FULL_21 Section 6 (L) — API variant: Google LangExtract over public46 via
REAL Mistral API (ministral-14b-latest), user-provided key.

Channel decision (user, 2026-09-22): the API model is stronger than the local
mistral-7b substitute; the API key is now valid and reachable from the server.
This runner is a SEPARATE output namespace from the local-channel run
(outputs/full21/s6_langextract/ = local mistral-7b, frozen 4 records) so the
two channels can be compared honestly. Same extraction example, prompt hint,
span verification, graph-digest new-fact check, and 48000-char truncation as
the local runner — only the backend differs.

Credentials: /mnt/data/guardian/agent-workspace/.mistral.env (outside git,
mode 600, value never printed, never logged).

Outputs (append-only, resumable):
  outputs/full21/s6_langextract_api/records.jsonl
  outputs/full21/s6_langextract_api/summary.json
"""
from __future__ import annotations

import argparse
import json
import os
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

ENV_FILE = REPO.parent / ".mistral.env"
BASE_URL = "https://api.mistral.ai/v1"

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


def load_env(path: Path) -> dict:
    vals = {}
    for line in open(path):
        line = line.strip()
        if line.startswith("export "):
            k, _, v = line[7:].partition("=")
            vals[k.strip()] = v.strip().strip("'\"")
    return vals


def span_ok(text, start, end, source) -> bool:
    if start is None or end is None:
        return False
    if start < 0 or end > len(source) or end <= start:
        return False
    return source[start:end] == text


def new_fact(quote: str, digest: str) -> bool:
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
    ap.add_argument("--time-budget", type=int, default=0)
    ap.add_argument("--batch-max", type=int, default=0)
    ap.add_argument("--retries", type=int, default=3)
    args = ap.parse_args()

    vals = load_env(ENV_FILE)
    key = vals.get("MISTRAL_API_KEY") or ""
    model_id = vals.get("MISTRAL_MODEL") or "ministral-14b-latest"
    if not key:
        print("FATAL: MISTRAL_API_KEY missing in .mistral.env", flush=True)
        return 2
    print(f"[s6api] backend: {model_id} via {BASE_URL} (key hidden)", flush=True)

    out_dir = Path("outputs/full21/s6_langextract_api")
    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / "records.jsonl"

    model = OpenAILanguageModel(
        model_id=model_id, api_key=key, base_url=BASE_URL,
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
    print(f"[s6api] resume: {len(done)} done, {len(cases) - len(done)} to go", flush=True)

    stats = {"cases": 0, "extractions": 0, "span_ok": 0, "span_bad": 0,
             "new_facts": 0, "errors": 0, "retries_used": 0}
    t_run0 = time.perf_counter()
    stopped = None
    with open(rec_path, "a", encoding="utf-8") as fout:
        for case in cases:
            cid = case["id"]
            if cid in done:
                continue
            if args.time_budget and (time.perf_counter() - t_run0) > args.time_budget:
                stopped = "time_budget"
                break
            if args.batch_max and stats["cases"] >= args.batch_max:
                stopped = "batch_max"
                break
            t0 = time.perf_counter()
            source = case["prompt"][:args.max_chars]
            result = None
            last_err = None
            for attempt in range(args.retries):
                try:
                    result = lx.extract(
                        source,
                        prompt_description=PROMPT_HINT,
                        examples=[EXAMPLE],
                        model=model,
                        show_progress=False,
                    )
                    last_err = None
                    break
                except Exception as e:
                    last_err = f"{type(e).__name__}: {e}"
                    if attempt + 1 < args.retries:
                        stats["retries_used"] += 1
                        time.sleep(5 * (attempt + 1))
            try:
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
            if last_err and "error" not in rec:
                rec["warning"] = f"succeeded after retries; last error: {last_err}"
            stats["cases"] += 1
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            print(f"[s6api] {cid}: {rec.get('n_extractions', 'ERR')} extr, "
                  f"{rec.get('n_span_ok', 0)} span_ok, {rec.get('n_new_vs_graph', 0)} new "
                  f"({rec.get('latency_s', '?')}s)", flush=True)

    (out_dir / "summary.json").write_text(json.dumps({
        **stats, "backend": f"api {model_id} via {BASE_URL}",
        "input": args.input, "max_chars": args.max_chars,
        "stopped_reason": stopped,
        "done_total_after": len(done) + stats["cases"],
    }, indent=1))
    print(json.dumps(stats, indent=1))
    if stopped:
        print(f"[s6api] stopped cleanly: {stopped}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
