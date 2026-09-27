"""LLM arms: A (Mistral end-to-end component task), I (strong Mistral medium),
A2/I2 (narrow span-to-tool pair classification on gold spans), and the
relation-only diagnostic (S10) which deliberately receives gold endpoints.

Runners for A/A2 never read gold files; A2 reads component_inputs.json which
contains SPANS ONLY (no roles, no tools). The relation diagnostic reads gold
edges by design (it tests relation typing in isolation) and is labelled as
an oracle-endpoint experiment everywhere.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_common import (Mistral, mistral_settings, load_suite, load_component_inputs,
                       out_dir, write_usage, ROLE_VOCAB, RELATION_VOCAB,
                       PAIR_LABEL_VOCAB, FROZEN_DIR)

STRONG_MODEL = os.environ.get("OC_STRONG_MODEL", "mistral-medium-latest")

E2E_SYSTEM = """You classify policy events for a compliance system. Read the business policy and the available tool catalog.

For every act, state, or communication mentioned in the policy, output a candidate event with:
- source_span: an EXACT substring copied verbatim from the policy text (no paraphrase, no shortening)
- role: one of OPERATION_EFFECT (the regulated business action itself), PRECONDITION_CHECK (a verification act that tests whether something holds), STATE_OBSERVATION (a perception or state reading such as sensor values, report presence, permit status), COMMUNICATION (a message act by anyone), OTHER (a descriptive statement that is not an operation)
- governed_tools: the tool names whose execution realizes this event (empty list for OTHER)

Also output condition edges: {"condition_span": ..., "operation_span": ..., "relation": ...} where relation is one of GATE (the operation may happen only if the condition holds), ORDER_BEFORE (the condition must happen before the operation), ORDER_AFTER (the operation happens after the trigger condition), EXCEPTION (the operation is forbidden unless the condition holds), EVEN_IF (the operation is forbidden even if the condition holds).

Bind a condition only to the operation it regulates. Do not treat a tool's name as its meaning: judge tools by their description and schema. A tool that only reads or audits is not a business operation. Answer with JSON only: {"events": [...], "edges": [...]}"""

PAIR_SYSTEM = """You see one source span from a policy and one tool from the catalog. Choose exactly one label:
- REALIZES_OPERATION: executing the tool performs the action described by the span
- CHECKS_PRECONDITION: executing the tool verifies whether the state in the span holds
- OBSERVES_STATE: executing the tool reads or observes the state in the span
- COMMUNICATES: executing the tool sends a communication about the span
- UNRELATED: the tool has nothing to do with the span
- UNKNOWN: cannot decide
Judge by the tool description and schema, never by the tool name. Answer with JSON only: {"label": "...", "reason": "one short sentence"}."""

RELATION_SYSTEM = """Given a policy, one condition span and one operation span, choose their relation:
- GATE: the operation may happen only if the condition holds
- ORDER_BEFORE: the condition is a required earlier step in a sequence; the operation is a later step ("after X, perform Y", "weigh before unloading")
- ORDER_AFTER: the operation is a triggered reaction to the condition occurring, typically a notification duty ("when X, notify", "after each X, report")
- EXCEPTION: the operation is forbidden unless the condition holds
- EVEN_IF: the operation is forbidden even if the condition holds
- NONE: there is no regulatory relation between them
- UNKNOWN: cannot decide
Answer with JSON only: {"relation": "..."}."""


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def sentence_for_span(policy: str, span: str) -> str:
    for sent in split_sentences(policy):
        if span in sent:
            return sent
    return policy


def validate_e2e(case, answer):
    policy = case["policy"]
    tool_names = {t["name"] for t in case["tools"]}
    events, edges = [], []
    errors = []
    for ev in answer.get("events", []) or []:
        if not isinstance(ev, dict):
            errors.append("event_not_object")
            continue
        span, role = ev.get("source_span"), ev.get("role")
        tools = ev.get("governed_tools", [])
        if not isinstance(span, str) or span not in policy:
            errors.append("span_not_substring")
            continue
        if role not in ROLE_VOCAB:
            errors.append(f"bad_role:{role}")
            continue
        if not isinstance(tools, list) or any(t not in tool_names for t in tools):
            errors.append("bad_tool")
            continue
        events.append({"span": span, "role": role, "governed_tools": tools})
    for ed in answer.get("edges", []) or []:
        if not isinstance(ed, dict):
            errors.append("edge_not_object")
            continue
        cond, op, rel = ed.get("condition_span"), ed.get("operation_span"), ed.get("relation")
        if not isinstance(cond, str) or cond not in policy:
            errors.append("cond_not_substring")
            continue
        if not isinstance(op, str) or op not in policy:
            errors.append("op_not_substring")
            continue
        if rel not in RELATION_VOCAB:
            errors.append(f"bad_relation:{rel}")
            continue
        edges.append({"condition_span": cond, "operation_span": op, "relation": rel})
    return events, edges, errors


def run_e2e(arm: str, model: str, which: str):
    suite = load_suite(which)
    suffix = "_renamed" if which == "renamed" else ""
    client = Mistral(model=model, cache_dir=out_dir(arm + suffix) / "_cache")
    outdir = out_dir(arm + suffix)
    t0 = time.time()
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        user = json.dumps({"policy": case["policy"],
                           "tools": case["tools"]}, ensure_ascii=False)
        rec = client.ask(E2E_SYSTEM, user, max_tokens=3000)
        answer, err = Mistral.parse_json(rec["raw"])
        events, edges, errors = validate_e2e(case, answer)
        path.write_text(json.dumps({
            "case_id": case["case_id"], "model": model,
            "served_model": rec.get("served_model"),
            "events": events, "edges": edges,
            "format_errors": errors, "parse_error": err,
            "finish_reason": rec.get("finish_reason"),
            "usage": rec.get("usage"), "latency": rec.get("latency"),
            "cached": rec.get("cached"),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    write_usage(arm + suffix, {
        "wall_seconds": round(time.time() - t0, 1), "suite": which, "model": model,
        "calls": client.calls, "usage": client.usage_total})
    print(arm, "done", which, client.calls, client.usage_total)


def run_pairs(arm: str, model: str, which: str):
    suite = load_suite(which)
    comp = load_component_inputs(which)
    suffix = "_renamed" if which == "renamed" else ""
    client = Mistral(model=model, cache_dir=out_dir(arm + suffix) / "_cache")
    outdir = out_dir(arm + suffix)
    t0 = time.time()
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        spans = comp.get(case["case_id"], [])
        pairs = []
        served = None
        for span in spans:
            sent = sentence_for_span(case["policy"], span)
            for tool in case["tools"]:
                user = json.dumps({"policy_sentence": sent, "source_span": span,
                                   "tool": tool}, ensure_ascii=False)
                rec = client.ask(PAIR_SYSTEM, user, max_tokens=200)
                served = rec.get("served_model")
                answer, err = Mistral.parse_json(rec["raw"])
                label = answer.get("label")
                if label not in PAIR_LABEL_VOCAB:
                    label = "UNKNOWN"
                pairs.append({"span": span, "tool": tool["name"], "label": label,
                              "reason": answer.get("reason"),
                              "parse_error": err or None,
                              "usage": rec.get("usage")})
        path.write_text(json.dumps({
            "case_id": case["case_id"], "model": model,
            "served_model": served,
            "pairs": pairs}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_usage(arm + suffix, {
        "wall_seconds": round(time.time() - t0, 1), "suite": which, "model": model,
        "calls": client.calls, "usage": client.usage_total})
    print(arm, "done", which, client.calls, client.usage_total)


def run_relation(arm: str, model: str, which: str):
    """Oracle-endpoint diagnostic: gold condition/operation pairs + sampled
    negatives with no gold edge; the model only types the relation."""
    suite = load_suite(which)
    gold_name = "gold.json" if which == "original" else "gold_renamed.json"
    gold = {g["case_id"]: g for g in json.loads((FROZEN_DIR / gold_name).read_text(encoding="utf-8"))}
    rng = random.Random(20260927)
    suffix = "_renamed" if which == "renamed" else ""
    client = Mistral(model=model, cache_dir=out_dir(arm + suffix) / "_cache")
    outdir = out_dir(arm + suffix)
    t0 = time.time()
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        g = gold[case["case_id"]]
        edge_keys = {(e["condition_span"], e["operation_span"]) for e in g["condition_edges"]}
        questions = []
        for e in g["condition_edges"]:
            ref = e.get("ref_span") or e["condition_span"]
            questions.append({"condition_span": e["condition_span"],
                              "operation_span": e["operation_span"],
                              "gold_relation": e["relation"], "kind": "gold"})
        # negatives: event pairs without a gold edge (event spans only)
        evs = [ev["source_span"] for ev in g["candidate_events"]
               if ev["role"] in {"OPERATION_EFFECT", "PRECONDITION_CHECK",
                                 "STATE_OBSERVATION", "COMMUNICATION"}]
        op_evs = [ev["source_span"] for ev in g["candidate_events"]
                  if ev["role"] == "OPERATION_EFFECT"]
        neg_candidates = [(c, o) for c in evs for o in op_evs
                          if (c, o) not in edge_keys and c != o]
        rng.shuffle(neg_candidates)
        for c, o in neg_candidates[:2]:
            questions.append({"condition_span": c, "operation_span": o,
                              "gold_relation": "NONE", "kind": "negative"})
        answers = []
        for q in questions:
            user = json.dumps({"policy": case["policy"],
                               "condition_span": q["condition_span"],
                               "operation_span": q["operation_span"]},
                              ensure_ascii=False)
            rec = client.ask(RELATION_SYSTEM, user, max_tokens=200)
            answer, err = Mistral.parse_json(rec["raw"])
            rel = answer.get("relation")
            if rel not in RELATION_VOCAB:
                rel = "UNKNOWN"
            answers.append({**q, "predicted": rel, "parse_error": err or None,
                            "usage": rec.get("usage")})
        path.write_text(json.dumps({
            "case_id": case["case_id"], "model": model,
            "answers": answers}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_usage(arm + suffix, {
        "wall_seconds": round(time.time() - t0, 1), "suite": which, "model": model,
        "calls": client.calls, "usage": client.usage_total,
        "note": "oracle-endpoint diagnostic (gold spans given by design)"})
    print(arm, "done", which, client.calls, client.usage_total)


def main():
    arm = os.environ.get("OC_ARM", "A_e2e")
    which = os.environ.get("OC_SUITE", "original")
    default_model = mistral_settings()["MISTRAL_MODEL"]
    if arm == "A_e2e":
        run_e2e("A_e2e", os.environ.get("OC_MODEL") or default_model, which)
    elif arm == "I_e2e":
        run_e2e("I_e2e", STRONG_MODEL, which)
    elif arm == "A2_pairs":
        run_pairs("A2_pairs", os.environ.get("OC_MODEL") or default_model, which)
    elif arm == "I2_pairs":
        run_pairs("I2_pairs", STRONG_MODEL, which)
    elif arm == "relation":
        run_relation("relation", os.environ.get("OC_MODEL") or default_model, which)
    elif arm == "relation_strong":
        run_relation("relation_strong", STRONG_MODEL, which)
    else:
        raise SystemExit(f"unknown arm {arm}")


if __name__ == "__main__":
    main()
