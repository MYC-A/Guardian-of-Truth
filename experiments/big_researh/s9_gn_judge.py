#!/usr/bin/env python3
"""BIG_RESEARH S9 (I.C): judge-context ablations N / N+quotes / G+N on the
frozen control granite channel.

Directive I.C ablation G+N. Judge = old Granite 8B control checkpoint,
criterion groundedness, think=false, greedy, max_new_tokens 16 — IDENTICAL to
the frozen control; the only changing axis is the DOCUMENT context:

  control (frozen, already measured): [bounded head_tail prompt @4800]
  s9_n_cards:        [NuExtract policy-rule + tool cards, cap 4800]
  s9_n_cards_quotes: [cards cap 2600 + bounded prompt quotes to ~4800]
  s9_gn_cards:       [graph digest cap 2600 + cards cap ~2200]

Cards come from outputs/big_researh/s9_nuextract/cards.jsonl (NuExtract3
verbatim, span-verified). Only span_ok spans are rendered. Graph digest from
the same g_graph module as S5 (frozen negative: G alone hurt). Gold joined
only post-hoc; no_score cases stay missing, never 0.

Outputs:
  outputs/research_granite_guardian/big_researh_s9_{arm}/records.jsonl
  outputs/big_researh/s9_nuextract/judge_metrics.json
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

from g_graph import graph_digest  # noqa: E402
from run_granite_modes import (  # noqa: E402
    GraniteLocalRunner, read_cases, bounded_text, parse_score, sha256_file)

CARDS_JSONL = REPO / "outputs" / "big_researh" / "s9_nuextract" / "cards.jsonl"
CONTROL_PERCASE = REPO / "outputs" / "full21" / "control_repro_percase.csv"
MODEL_PATH = Path("/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda")

CONTROL_PROMPT_BUDGET = 4800
RESPONSE_LIMIT = 7200
CARD_CAP = 2600
GN_DIGEST_CAP = 2600
GN_CARD_CAP = 2200


def render_cards(rec: dict, cap: int) -> str:
    span_by_field = {s["field"]: s for s in
                     (rec.get("policy_rules_spans", []) + rec.get("policy_actions_spans", [])
                      + rec.get("response_tools_spans", [])
                      + rec.get("temporal_relations_spans", [])) if s.get("text")}
    lines = ["POLICY RULES (NuExtract3 verbatim spans, mechanically verified):"]
    for i, r in enumerate(rec.get("policy_rules", [])):
        sp = span_by_field.get(f"rules[{i}].source_quote")
        if sp is None or not sp.get("span_ok"):
            continue
        cond = f" COND[{r.get('condition_text')}]" if r.get("condition_text") else ""
        exc = f" EXC[{r.get('exception_text')}]" if r.get("exception_text") else ""
        lines.append(f"r{i} {str(r.get('modality', '?')).upper()} "
                     f"T={r.get('target_name')}{cond}{exc} "
                     f"QUOTE: {sp['text']}")
    for i, r in enumerate(rec.get("policy_actions", [])):
        sp = span_by_field.get(f"actions[{i}].source_quote")
        if sp is None or not sp.get("span_ok"):
            continue
        lines.append(f"a{i} {str(r.get('modality', '?')).upper()} "
                     f"ACTION={r.get('action')} QUOTE: {sp['text']}")
    tools = [t for t in rec.get("response_tools", []) if t.get("tool_name_text")]
    if tools:
        lines.append("RESPONSE TOOL STRUCTURE (verbatim):")
        for i, t in enumerate(tools):
            args = f" ARGS: {t.get('arguments_text')}" if t.get("arguments_text") else ""
            lines.append(f"c{i} TOOL: {t['tool_name_text']}{args}")
    text = "\n".join(lines)
    if len(text) > cap:
        marker = "\n[... cards truncated ...]\n"
        keep = cap - len(marker)
        text = text[: keep // 2] + marker + text[-keep // 2:]
    return text


def run_arm(runner, cases, cards, arm: str, input_path: Path) -> dict:
    out_dir = Path(f"outputs/research_granite_guardian/big_researh_s9_{arm}")
    out_dir.mkdir(parents=True, exist_ok=True)
    run_config = {
        "runner": "big_researh/s9_gn_judge",
        "model_id": "ibm-granite/granite-guardian-3.3-8b",
        "model_path": str(MODEL_PATH),
        "criterion": "groundedness", "think": False, "max_new_tokens": 16,
        "context_kind": f"s9_{arm}",
        "cards_source": "outputs/big_researh/s9_nuextract/cards.jsonl",
        "input_path": str(input_path), "input_sha256": sha256_file(input_path),
        "case_count": len(cases),
    }
    (out_dir / "run_config.json").write_text(json.dumps(run_config, indent=1))

    records, counts = [], {}
    for case in cases:
        t0 = time.perf_counter()
        prompt, response = case["prompt"], case["response"]
        card_rec = cards.get(case["id"], {})
        cards_txt = render_cards(card_rec, CARD_CAP if arm != "gn_cards" else GN_CARD_CAP)
        response_b = bounded_text(response, RESPONSE_LIMIT, "response")
        if arm == "n_cards":
            documents = [{"doc_id": "nuextract_cards", "text": cards_txt}]
        elif arm == "n_cards_quotes":
            quote_budget = max(800, CONTROL_PROMPT_BUDGET - min(len(cards_txt), CARD_CAP))
            quotes_b = bounded_text(prompt, quote_budget, "prompt_quotes")
            documents = [{"doc_id": "nuextract_cards", "text": cards_txt},
                         {"doc_id": "original_quotes", "text": quotes_b.text}]
        elif arm == "gn_cards":
            try:
                digest = graph_digest(prompt, response)
            except Exception:
                digest = ""
            if len(digest) > GN_DIGEST_CAP:
                marker = "\n[... omitted ...]\n"
                keep = GN_DIGEST_CAP - len(marker)
                digest = digest[: keep // 2] + marker + digest[-keep // 2:]
            documents = [{"doc_id": "graph_digest", "text": digest},
                         {"doc_id": "nuextract_cards", "text": cards_txt}]
        else:
            raise ValueError(arm)
        messages = [{"role": "assistant", "content": response_b.text}]
        chat = runner.tokenizer.apply_chat_template(
            messages, guardian_config={"criteria_id": "groundedness"},
            documents=documents, think=False, tokenize=False, add_generation_prompt=True)
        gen = runner.generate(chat, 16)
        risk = parse_score(gen["text"])
        status = "ok" if risk is not None else "no_score_token"
        rec = {
            "id": case["id"], "context_kind": f"s9_{arm}", "status": status,
            "risk_token": risk, "raw_model_output": gen["text"],
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "doc_chars": sum(len(d["text"]) for d in documents),
            "cards_available": bool(card_rec),
            "n_rules_ok": card_rec.get("n_rules_ok", 0),
            "n_tools_ok": card_rec.get("n_tools_ok", 0),
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
    summary = {"output_dir": str(out_dir), "records": len(records),
               "status_counts": counts, "input_sha256": run_config["input_sha256"]}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return {"arm": arm, "records": records, "summary": summary}


def metrics(records, gold, control):
    tp = fp = fn = tn = miss = 0
    by_id = {r["id"]: r for r in records}
    for cid, g in gold.items():
        r = by_id.get(cid)
        if r is None or r["status"] != "ok":
            miss += 1
            continue
        p = 1 if r["risk_token"] == "yes" else 0
        tp += p == 1 and g == 1
        fp += p == 1 and g == 0
        fn += p == 0 and g == 1
        tn += p == 0 and g == 0
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec_ = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec_ / (prec + rec_) if prec + rec_ else 0.0
    agree = sum(1 for cid in gold if cid in by_id and by_id[cid]["status"] == "ok"
                and (1 if by_id[cid]["risk_token"] == "yes" else 0) == control.get(cid))
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "P": round(prec, 4),
            "R": round(rec_, 4), "F1": round(f1, 4), "no_score": miss,
            "agree_with_control": agree}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--arms", nargs="+",
                    default=["n_cards", "n_cards_quotes", "gn_cards"])
    args = ap.parse_args()

    cases = read_cases(Path(args.input))
    cards = {}
    for line in open(CARDS_JSONL, encoding="utf-8"):
        try:
            rec = json.loads(line)
            cards[rec["id"]] = rec
        except Exception:
            pass
    gold, control = {}, {}
    for row in csv.DictReader(open(CONTROL_PERCASE)):
        gold[row["id"]] = int(row["gold"])
        control[row["id"]] = int(row["granite_repro"])

    print(f"[s9j] cards loaded for {len(cards)} cases; arms={args.arms}", flush=True)
    runner = GraniteLocalRunner(MODEL_PATH)
    all_metrics = {}
    for arm in args.arms:
        t0 = time.perf_counter()
        res = run_arm(runner, cases, cards, arm, Path(args.input))
        m = metrics(res["records"], gold, control)
        m["wall_s"] = round(time.perf_counter() - t0, 1)
        all_metrics[arm] = m
        print(f"[s9j] {arm}: {json.dumps(m)}", flush=True)

    out = {"arms": all_metrics,
           "control_reference": {"TP": 20, "FP": 2, "FN": 3, "TN": 21, "F1": 0.8889},
           "s5_negative_reference": {"graph_alone": {"TP": 5, "FP": 21, "FN": 0, "F1": 0.6032}}}
    (REPO / "outputs" / "big_researh" / "s9_nuextract").mkdir(parents=True, exist_ok=True)
    (REPO / "outputs" / "big_researh" / "s9_nuextract" / "judge_metrics.json").write_text(
        json.dumps(out, indent=1))
    print(json.dumps(out, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
