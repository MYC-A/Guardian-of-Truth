#!/usr/bin/env python3
"""FULL_21 Section 5 (G): existing Guardian provenance graph as Granite context.

Old Granite 8B, criterion groundedness, think=false, temperature 0 — the only
changing axis is the DOCUMENT context handed to the checkpoint:

  control (already run):  documents = [bounded head_tail prompt @4800]
  s5_graph:               documents = [mechanical graph digest (provenance)]
  s5_graph_quotes:        documents = [graph digest + bounded original prompt
                          quotes, total ~= control budget]
  s5_plain_summary:       documents = [flat mechanical event list, NO graph
                          relations/lineage/statuses, comparable size]
                          (tests whether graph STRUCTURE or mere compactness)

Graph digest is imported from the previous session's experiments/superz_fullcycle/g_graph.py
(guardian_truth.parsing.parse_events + guardian_truth.provenance.build_graph):
observed values per entity, previous observations (lineage), scope conflicts,
value mismatches, unobserved candidate arguments. Observations, not instructions.
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
sys.path.insert(0, str(REPO / "experiments" / "full21"))
sys.path.insert(0, str(REPO / "src"))

from g_graph import graph_digest  # noqa: E402  (reuses provenance graph digest)
from guardian_truth.parsing import parse_events  # noqa: E402
from guardian_truth.provenance import build_graph  # noqa: E402

from run_granite_modes import (  # noqa: E402
    GraniteLocalRunner, read_cases, bounded_text, parse_score, make_output_dir,
    sha256_file, BoundText,
)

from datetime import UTC, datetime

CONTROL_PROMPT_BUDGET = 4800  # chars — matches control doc size at 12k ctx


def plain_event_summary(prompt: str, response: str, budget: int) -> str:
    """Same underlying facts as the graph digest, but FLAT: no statuses, no
    entity scoping, no previous/lineage links, no alternatives — the
    compactness control required by FULL_21 section 5 item 2."""
    history = parse_events(prompt, "prompt")
    candidate = parse_events(response, "response")
    graph = build_graph(history, candidate)
    lines = []
    for f in graph.facts:
        v = json.dumps(f.value, ensure_ascii=False)[:60]
        lines.append(f"ev{f.event} tool={f.tool} {f.field}={v}")
    for a in graph.arguments:
        lines.append(f"response argument {'/'.join(map(str, a.path))}="
                     f"{json.dumps(a.value, ensure_ascii=False)[:60]}")
    lines.append(f"(history events: {len(history)}; response events: {len(candidate)})")
    text = "\n".join(lines)
    if len(text) > budget:
        marker = "\n[... omitted ...]\n"
        keep = budget - len(marker)
        text = text[: keep // 2] + marker + text[-keep // 2:]
    return text


def run_variant(runner: GraniteLocalRunner, cases: list, variant: dict, input_path: Path) -> dict:
    out_dir = make_output_dir(variant["output_dir"])
    mode = variant["context_kind"]
    max_new = 16
    run_config = {
        "runner": "full21/s5_graph_granite",
        "model_id": "ibm-granite/granite-guardian-3.3-8b",
        "model_path": variant["model_path"],
        "criterion": "groundedness",
        "think": False,
        "context_kind": mode,
        "max_new_tokens": max_new,
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "case_count": len(cases),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "note": "graph digest via guardian_truth provenance (g_graph.graph_digest)",
    }
    (out_dir / "run_config.json").write_text(json.dumps(run_config, indent=1), encoding="utf-8")

    response_limit = 7200  # 12k * 3/5, same as control
    records = []
    counts = {}
    digest_errors = {}
    for case in cases:
        t0 = time.perf_counter()
        prompt, response = case["prompt"], case["response"]
        try:
            digest = graph_digest(prompt, response)
        except Exception as e:
            digest_errors[case["id"]] = f"{type(e).__name__}: {e}"
            digest = ""
        try:
            plain = plain_event_summary(prompt, response, CONTROL_PROMPT_BUDGET)
        except Exception as e:
            digest_errors[case["id"]] += f" | plain: {type(e).__name__}"
            plain = ""
        prompt_b = bounded_text(prompt, CONTROL_PROMPT_BUDGET, "prompt")
        response_b = bounded_text(response, response_limit, "response")

        if mode == "graph":
            documents = [{"doc_id": "graph_digest", "text": digest}]
        elif mode == "graph_quotes":
            quote_budget = max(800, CONTROL_PROMPT_BUDGET - min(len(digest), 2600))
            quotes_b = bounded_text(prompt, quote_budget, "prompt_quotes")
            documents = [
                {"doc_id": "graph_digest", "text": digest},
                {"doc_id": "original_quotes", "text": quotes_b.text},
            ]
        elif mode == "plain_summary":
            documents = [{"doc_id": "event_list", "text": plain}]
        else:
            raise ValueError(mode)

        messages = [{"role": "assistant", "content": response_b.text}]
        chat = runner.tokenizer.apply_chat_template(
            messages, guardian_config={"criteria_id": "groundedness"},
            documents=documents, think=False, tokenize=False, add_generation_prompt=True)
        gen = runner.generate(chat, max_new)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        risk = parse_score(gen["text"])
        status = "ok" if risk is not None else "no_score_token"
        rec = {
            "id": case["id"],
            "criterion": "groundedness",
            "context_kind": mode,
            "status": status,
            "risk_token": risk,
            "raw_model_output": gen["text"],
            "latency_ms": round(latency_ms, 3),
            "digest_chars": len(digest),
            "plain_chars": len(plain),
            "doc_chars": sum(len(d["text"]) for d in documents),
            "response_bounded_chars": response_b.kept_chars,
            "input_token_count": gen["input_token_count"],
            "probabilistic_score": gen["probabilistic_score"],
            "score_method": gen["score_method"],
            "formal_proof_status": "UNRESOLVED",
        }
        records.append(rec)
        counts[status] = counts.get(status, 0) + 1
    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = {"output_dir": str(out_dir), "records": len(records), "status_counts": counts,
               "digest_errors": digest_errors,
               "input_sha256": run_config["input_sha256"],
               "finished_at_utc": datetime.now(UTC).isoformat()}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--kinds", nargs="+", default=["graph", "graph_quotes", "plain_summary"])
    args = ap.parse_args()
    cases = read_cases(Path(args.input))
    runner = GraniteLocalRunner(Path(args.model_path))
    results = []
    for kind in args.kinds:
        variant = {"context_kind": kind, "model_path": args.model_path,
                   "output_dir": f"outputs/research_granite_guardian/full21_s5_{kind}"}
        print(f"[s5 {kind}] start", flush=True)
        s = run_variant(runner, cases, variant, Path(args.input))
        print(f"[s5 {kind}] -> {json.dumps(s, ensure_ascii=False)}", flush=True)
        results.append(s)
    print(json.dumps({"variants": results}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
