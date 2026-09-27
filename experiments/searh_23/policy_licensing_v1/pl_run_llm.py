"""LLM arms for the POLICY-LICENSED RELATIONS research.

Phases (run per model: mistral | codestral):
  det       BASE narrow pair detection (same question family as
            relation_edges_v1 DET arm -> reproduces the known over-binding)
  det_pol   IDEA F ablation: policy text only (no tool semantics)
  det_tool  IDEA F ablation: tool semantics only (no policy text)
  listwise  IDEA A: per event, top-3 retriever candidates COMPETE; the model
            must select only policy-licensed connections
  ev        IDEA B: extractive evidence - the model must quote the minimal
            policy span licensing the pair, or return NO_EVIDENCE
  evjudge   IDEA B: evidence-centred re-decision - given ONLY the quoted
            evidence, is the pair licensed?
  qa        IDEA C: extractive QA - "which operation is constrained by X?",
            answer must be an exact policy span or NO ANSWER
  dir       direction question (which event must happen first)
  cls       relation classification on gold-positive pairs

All prompts name-blind (tool descriptions only, never names).
Evidence/QA answers are verified verbatim downstream - a generated
paraphrase counts as hallucinated evidence, not evidence.

Run: PL_SUITE=original PL_MODEL=mistral python3 pl_run_llm.py det
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import (MODELS, Mistral, load_suite, out_dir, render_tool,
                       tools_by_name, ev_by_eid, sentence_of_span, RELATION_DEFS,
                       write_usage)

SYSTEM = ("You are a policy-compliance analyst. You judge ONLY from the given "
          "policy text; general world knowledge about how such processes "
          "usually work is NOT evidence. Tool names are never shown; tool "
          "semantics come from the descriptions provided. Answer strictly as "
          "a single JSON object, no extra text.")


def render_event(case, ev, label, with_tools=True, with_context=True):
    by_name = tools_by_name(case)
    parts = [f'{label}: "{ev["source_span"]}" (role: {ev["role"]})']
    if with_context:
        s, _ = sentence_of_span(case["policy"], ev["span_start"])
        parts.append(f'Context sentence for {label}: "{s or ""}"')
    if with_tools:
        tools = " ".join(render_tool(by_name[n]) for n in ev.get("governed_tools", [])
                         if n in by_name)
        parts.append(f"Tool semantics for {label}: {tools or 'none'}")
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------- det
def det_user(case, a, b, variant="both"):
    with_tools = variant in ("both",)
    with_policy = variant in ("both", "policy")
    head = f"POLICY:\n{case['policy']}\n\n" if with_policy else ""
    return (head
            + render_event(case, a, "EVENT A", with_tools, with_policy)
            + render_event(case, b, "EVENT B", with_tools, with_policy)
            + "Question: in this policy, does event A stand in a regulatory or "
              "temporal relation to event B - does A gate, precede, enable, "
              "trigger or except B, or is A explicitly stated NOT to block B? "
              "Answer only from the policy text.\n"
              'Answer strictly as JSON: {"decision": "RELATED" or '
              '"NOT_RELATED" or "UNKNOWN", "reason": "one short sentence"}')


# ----------------------------------------------------------------- listwise
def listwise_user(case, target, cands):
    lines = "\n".join(
        f'{i}. "{c["source_span"]}" (role: {c["role"]})'
        for i, c in enumerate(cands, 1))
    by_name = tools_by_name(case)
    tools = " ".join(render_tool(by_name[n]) for n in target.get("governed_tools", [])
                     if n in by_name)
    return (f"POLICY:\n{case['policy']}\n\n"
            f'EVENT X (the antecedent candidate): "{target["source_span"]}" '
            f'(role: {target["role"]})\n'
            f"Tool semantics for X: {tools or 'none'}\n\n"
            f"CANDIDATE events that might be connected to X:\n{lines}\n\n"
            "Question: according to THIS POLICY ONLY - not general world "
            "knowledge about how such processes usually work - which of the "
            "candidate events does the policy text itself explicitly connect "
            "to event X (by gating, precedence, triggering, exception or "
            "documented non-blocking)? The candidates compete: select ONLY "
            "those for which the policy contains explicit supporting text. "
            "If the policy connects none of them, select NONE. If the policy "
            "connects several, select all of them. If you cannot tell from "
            "the text, answer UNKNOWN.\n"
            'Answer strictly as JSON: {"selected": [list of candidate numbers '
            'like "1"], "decision": "SOME" or "NONE" or "MULTIPLE" or '
            '"UNKNOWN", "reason": "one short sentence"}')


# -------------------------------------------------------------- evidence
def ev_user(case, a, b):
    return (f"POLICY:\n{case['policy']}\n\n"
            + render_event(case, a, "EVENT A")
            + render_event(case, b, "EVENT B")
            + "Task: decide whether THIS POLICY explicitly states a relation "
              "between event A and event B (gating, precedence, triggering, "
              "exception or documented non-blocking). If it does, quote the "
              "MINIMAL exact substring of the policy that states this "
              "relation between A and B - copy it character by character, "
              "do not paraphrase. If the policy contains no such text, "
              "answer NO_EVIDENCE. Do not use general world knowledge.\n"
              'Answer strictly as JSON: {"evidence": "<exact substring>" or '
              '"NO_EVIDENCE", "reason": "one short sentence"}')


def evjudge_user(a, b, evidence):
    return ("EVIDENCE (an exact quote from a workplace policy):\n"
            f"\"{evidence}\"\n\n"
            f'EVENT A: "{a["source_span"]}" (role: {a["role"]})\n'
            f'EVENT B: "{b["source_span"]}" (role: {b["role"]})\n\n'
            "Question: does this quoted evidence, by itself, explicitly "
            "state a relation between event A and event B (A gates, precedes, "
            "enables, triggers or excepts B, or states A does not block B)? "
            "Judge only the quote: if the quote mentions both events and "
            "connects them, answer LICENSED; if it connects only one of them "
            "to something else, or mentions both without connecting them, "
            "answer NOT_LICENSED; if you cannot tell, answer UNKNOWN.\n"
            'Answer strictly as JSON: {"decision": "LICENSED" or '
            '"NOT_LICENSED" or "UNKNOWN", "reason": "one short sentence"}')


# --------------------------------------------------------------------- qa
def qa_user(case, ev):
    by_name = tools_by_name(case)
    tools = " ".join(render_tool(by_name[n]) for n in ev.get("governed_tools", [])
                     if n in by_name)
    return (f"POLICY:\n{case['policy']}\n\n"
            f'QUESTION ANCHOR EVENT: "{ev["source_span"]}" (role: {ev["role"]})\n'
            f"Tool semantics: {tools or 'none'}\n\n"
            "Question: according to this policy, which operation or event is "
            "constrained by, gated by, or must happen after the anchor event? "
            "Answer by quoting the EXACT substring of the policy that names "
            "that constrained event - copy it character by character, do not "
            "paraphrase. If the policy does not constrain anything by the "
            "anchor event, answer NO ANSWER. Do not use general world "
            "knowledge.\n"
            'Answer strictly as JSON: {"answer": "<exact substring>" or '
            '"NO ANSWER", "reason": "one short sentence"}')


# --------------------------------------------------------------------- dir
def dir_user(case, a, b):
    return (f"POLICY:\n{case['policy']}\n\n"
            f'EVENT A: "{a["source_span"]}" (role: {a["role"]})\n'
            f'EVENT B: "{b["source_span"]}" (role: {b["role"]})\n\n'
            "Question: according to this policy, which event must happen "
            "first, or acts as the prerequisite/trigger for the other? "
            "Answer only from the policy text.\n"
            'Answer strictly as JSON: {"first": "A" or "B" or "UNKNOWN", '
              '"reason": "one short sentence"}')


# --------------------------------------------------------------------- cls
def cls_user(case, a, b):
    defs = "\n".join(f"- {k}: {v}" for k, v in RELATION_DEFS.items())
    return (f"POLICY:\n{case['policy']}\n\n"
            + render_event(case, a, "EVENT A")
            + render_event(case, b, "EVENT B")
            + f"Relation types:\n{defs}\n\n"
            "Question: which relation best describes how event A relates to "
            "event B in this policy? If two readings are genuinely plausible, "
            "list both in possible_relations (most plausible first).\n"
            'Answer strictly as JSON: {"relation": "<primary type>", '
            '"possible_relations": ["<primary type>", "..."], '
            '"direction_confidence": "high" or "low", '
            '"reason": "one short sentence"}')


# ------------------------------------------------------------------ runner
def phase_det(client, suite, arm, variant):
    outdir = out_dir(arm)
    n = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            n += len(case["pair_universe"])
            continue
        evmap = ev_by_eid(case)
        rows = []
        for pu in case["pair_universe"]:
            a, b = evmap[pu["a_eid"]], evmap[pu["b_eid"]]
            rec = client.ask(SYSTEM, det_user(case, a, b, variant), max_tokens=220)
            ans, err = Mistral.parse_json(rec["raw"])
            rows.append({"a_eid": pu["a_eid"], "b_eid": pu["b_eid"],
                         "decision": (ans or {}).get("decision"),
                         "reason": (ans or {}).get("reason"), "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def phase_listwise(client, suite, arm, pair_dir):
    outdir = out_dir(arm)
    n = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        sig_path = pair_dir / f"{case['case_id']}.json"
        if path.is_file() or not sig_path.is_file():
            continue
        sig = json.loads(sig_path.read_text(encoding="utf-8"))
        evmap = ev_by_eid(case)
        rows = []
        for ev in case["events"]:
            ranking = sig["rankings"].get(ev["eid"], [])
            top = [evmap[c["eid"]] for c in ranking[:3] if c["eid"] in evmap]
            if not top:
                rows.append({"eid": ev["eid"], "candidates": [],
                             "selected": [], "decision": "NONE"})
                continue
            rec = client.ask(SYSTEM, listwise_user(case, ev, top), max_tokens=300)
            ans, err = Mistral.parse_json(rec["raw"])
            sel = (ans or {}).get("selected") or []
            if isinstance(sel, str):
                sel = [sel]
            rows.append({
                "eid": ev["eid"],
                "candidates": [c["eid"] for c in top],
                "selected": [str(s) for s in sel],
                "decision": (ans or {}).get("decision"),
                "reason": (ans or {}).get("reason"), "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def _clean_quote(s):
    """Strip wrapping quotes/whitespace the model may add around a quote."""
    if not isinstance(s, str):
        return s
    t = s.strip()
    while t and t[0] in "\"'«" + chr(8220) and t[-1] in "\"'»" + chr(8221):
        t = t[1:-1].strip()
    return t


def phase_ev(client, suite, arm):
    outdir = out_dir(arm)
    n = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            n += len(case["pair_universe"])
            continue
        evmap = ev_by_eid(case)
        rows = []
        for pu in case["pair_universe"]:
            a, b = evmap[pu["a_eid"]], evmap[pu["b_eid"]]
            rec = client.ask(SYSTEM, ev_user(case, a, b), max_tokens=300)
            ans, err = Mistral.parse_json(rec["raw"])
            rows.append({"a_eid": pu["a_eid"], "b_eid": pu["b_eid"],
                         "evidence": _clean_quote((ans or {}).get("evidence")),
                         "reason": (ans or {}).get("reason"), "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def phase_evjudge(client, suite, arm, ev_dir):
    outdir = out_dir(arm)
    n = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        ev_path = ev_dir / f"{case['case_id']}.json"
        if path.is_file() or not ev_path.is_file():
            continue
        evmap = ev_by_eid(case)
        ev_rows = json.loads(ev_path.read_text(encoding="utf-8"))["rows"]
        rows = []
        for r in ev_rows:
            a, b = evmap[r["a_eid"]], evmap[r["b_eid"]]
            ev_text = r.get("evidence")
            if not ev_text or ev_text == "NO_EVIDENCE" or ev_text not in case["policy"]:
                rows.append({"a_eid": r["a_eid"], "b_eid": r["b_eid"],
                             "evidence": ev_text,
                             "verbatim": bool(ev_text and ev_text in case["policy"]),
                             "decision": "UNSUPPORTED", "judge_reason": None})
                continue
            rec = client.ask(SYSTEM, evjudge_user(a, b, ev_text), max_tokens=220)
            ans, err = Mistral.parse_json(rec["raw"])
            rows.append({"a_eid": r["a_eid"], "b_eid": r["b_eid"],
                         "evidence": ev_text, "verbatim": True,
                         "decision": (ans or {}).get("decision"),
                         "judge_reason": (ans or {}).get("reason"),
                         "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def phase_qa(client, suite, arm):
    outdir = out_dir(arm)
    n = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            n += len(case["events"])
            continue
        rows = []
        for ev in case["events"]:
            rec = client.ask(SYSTEM, qa_user(case, ev), max_tokens=260)
            ans, err = Mistral.parse_json(rec["raw"])
            ans_text = _clean_quote((ans or {}).get("answer"))
            rows.append({"eid": ev["eid"],
                         "answer": ans_text,
                         "verbatim": bool(ans_text and ans_text != "NO ANSWER"
                                          and ans_text in case["policy"]),
                         "reason": (ans or {}).get("reason"), "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def phase_dir(client, suite, arm, gold_pairs_only=True):
    outdir = out_dir(arm)
    n = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        evmap = ev_by_eid(case)
        todo = [e for e in case["edges"]] if gold_pairs_only else []
        rows = []
        for ed in todo:
            a, b = evmap[ed["from_eid"]], evmap[ed["to_eid"]]
            rec = client.ask(SYSTEM, dir_user(case, a, b), max_tokens=220)
            ans, err = Mistral.parse_json(rec["raw"])
            rows.append({"a_eid": ed["from_eid"], "b_eid": ed["to_eid"],
                         "first": (ans or {}).get("first"),
                         "reason": (ans or {}).get("reason"), "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def phase_cls(client, suite, arm):
    outdir = out_dir(arm)
    n = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            n += len(case["edges"])
            continue
        evmap = ev_by_eid(case)
        rows = []
        for ed in case["edges"]:
            a, b = evmap[ed["from_eid"]], evmap[ed["to_eid"]]
            rec = client.ask(SYSTEM, cls_user(case, a, b), max_tokens=300)
            ans, err = Mistral.parse_json(rec["raw"])
            rows.append({"a_eid": ed["from_eid"], "b_eid": ed["to_eid"],
                         "relation": (ans or {}).get("relation"),
                         "possible_relations": (ans or {}).get("possible_relations"),
                         "reason": (ans or {}).get("reason"), "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def grp_user(case, target, parents):
    lines = "\n".join(f'{i}. "{p["source_span"]}" (role: {p["role"]})'
                      for i, p in enumerate(parents, 1))
    return (f"POLICY:\n{case['policy']}\n\n"
            f'TARGET OPERATION: "{target["source_span"]}" (role: {target["role"]})\n'
            f"Events that gate or precede the target:\n{lines}\n\n"
            "Question: does the policy require ALL of these events before the "
            "target operation (AND), or at least ONE of them (OR), or exactly "
            "one of them (XOR)? Answer only from the policy text.\n"
            'Answer strictly as JSON: {"logic": "AND" or "OR" or "XOR" or '
            '"UNKNOWN", "reason": "one short sentence"}')


def phase_grp(client, suite, arm, det_dir):
    """Group logic for targets with >= 2 RELATED parents per the DET arm."""
    outdir = out_dir(arm)
    n = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        dpath = det_dir / f"{case['case_id']}.json"
        if path.is_file() or not dpath.is_file():
            continue
        evmap = ev_by_eid(case)
        det = json.loads(dpath.read_text(encoding="utf-8"))["rows"]
        related = {frozenset((r["a_eid"], r["b_eid"])) for r in det
                   if r.get("decision") == "RELATED"}
        parents_of = {}
        for e in case["events"]:
            ps = [evmap[other["eid"]] for other in case["events"]
                  if other["eid"] != e["eid"]
                  and frozenset((e["eid"], other["eid"])) in related]
            if len(ps) >= 2:
                parents_of[e["eid"]] = ps
        rows = []
        for eid, ps in parents_of.items():
            rec = client.ask(SYSTEM, grp_user(case, evmap[eid], ps), max_tokens=220)
            ans, err = Mistral.parse_json(rec["raw"])
            rows.append({"target_eid": eid,
                         "parent_eids": [p["eid"] for p in ps],
                         "logic": (ans or {}).get("logic"),
                         "reason": (ans or {}).get("reason"), "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def _base_or_evidence_pairs(case, det, sig_map, detection):
    """Candidate pairs for pipeline assembly: BASE combo or EVIDENCE arm.
    (evidence rows carry the verbatim-checked judge decision)."""
    CE_BAND = 0.35
    if detection == "evidence":
        evp = out_dir(f"ev_mistral{'' if os.environ.get('PL_SUITE','original')=='original' else '_'+os.environ.get('PL_SUITE','original')}") / f"{case['case_id']}.json"
        evjp = out_dir(f"evjudge_mistral{'' if os.environ.get('PL_SUITE','original')=='original' else '_'+os.environ.get('PL_SUITE','original')}") / f"{case['case_id']}.json"
        if not evjp.is_file():
            return []
        evj = json.loads(evjp.read_text(encoding="utf-8"))["rows"]
        return [(r["a_eid"], r["b_eid"]) for r in evj
                if r.get("decision") == "LICENSED"]
    out = []
    for r in det:
        if r.get("decision") != "RELATED":
            continue
        key = frozenset((r["a_eid"], r["b_eid"]))
        s = sig_map.get(key)
        if s is None or max(s["ce_both_ab"], s["ce_both_ba"]) < CE_BAND:
            continue
        out.append((r["a_eid"], r["b_eid"]))
    return out


def phase_dir_pred(client, suite, arm, det_dir, pair_dir):
    """DIR on pairs DETECTED by the BASE combo (ce-band AND mistral RELATED),
    so pipelines can be assembled from predicted (not gold) edges."""
    outdir = out_dir(arm)
    n = 0
    CE_BAND = 0.35
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        dpath = det_dir / f"{case['case_id']}.json"
        spath = pair_dir / f"{case['case_id']}.json"
        if path.is_file() or not dpath.is_file() or not spath.is_file():
            continue
        evmap = ev_by_eid(case)
        det = json.loads(dpath.read_text(encoding="utf-8"))["rows"]
        sig = json.loads(spath.read_text(encoding="utf-8"))["pairs"]
        sig_map = {frozenset((r["a_eid"], r["b_eid"])): r for r in sig}
        detection = os.environ.get("PL_DETECTION", "base")
        rows = []
        for a_eid, b_eid in _base_or_evidence_pairs(case, det, sig_map, detection):
            a, b = evmap[a_eid], evmap[b_eid]
            rec = client.ask(SYSTEM, dir_user(case, a, b), max_tokens=220)
            ans, err = Mistral.parse_json(rec["raw"])
            rows.append({"a_eid": a_eid, "b_eid": b_eid,
                         "first": (ans or {}).get("first"),
                         "reason": (ans or {}).get("reason"), "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def phase_cls_pred(client, suite, arm, det_dir, pair_dir, dir_dir):
    """CLS on detected pairs (BASE or EVIDENCE per PL_DETECTION) in the
    DIR-resolved direction (pipeline typing)."""
    outdir = out_dir(arm)
    n = 0
    CE_BAND = 0.35
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        dpath = det_dir / f"{case['case_id']}.json"
        spath = pair_dir / f"{case['case_id']}.json"
        ddirp = dir_dir / f"{case['case_id']}.json"
        if path.is_file() or not dpath.is_file() or not spath.is_file():
            continue
        evmap = ev_by_eid(case)
        det = json.loads(dpath.read_text(encoding="utf-8"))["rows"]
        sig = json.loads(spath.read_text(encoding="utf-8"))["pairs"]
        sig_map = {frozenset((r["a_eid"], r["b_eid"])): r for r in sig}
        dirrows = {}
        if ddirp.is_file():
            for r in json.loads(ddirp.read_text(encoding="utf-8"))["rows"]:
                dirrows[frozenset((r["a_eid"], r["b_eid"]))] = r
        detection = os.environ.get("PL_DETECTION", "base")
        rows = []
        for a_eid, b_eid in _base_or_evidence_pairs(case, det, sig_map, detection):
            key = frozenset((a_eid, b_eid))
            d = dirrows.get(key)
            first = (d or {}).get("first")
            if first == "B":
                a_eid, b_eid = b_eid, a_eid
            a, b = evmap[a_eid], evmap[b_eid]
            rec = client.ask(SYSTEM, cls_user(case, a, b), max_tokens=300)
            ans, err = Mistral.parse_json(rec["raw"])
            rows.append({"a_eid": a_eid, "b_eid": b_eid,
                         "relation": (ans or {}).get("relation"),
                         "possible_relations": (ans or {}).get("possible_relations"),
                         "reason": (ans or {}).get("reason"), "parse_error": err})
            n += 1
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def main():
    phase = sys.argv[1]
    model_key = os.environ.get("PL_MODEL", "mistral")
    which = os.environ.get("PL_SUITE", "original")
    model = MODELS[model_key]
    suite = load_suite(which)
    suffix = "" if which == "original" else "_" + which
    pair_dir = out_dir("PAIR_signals" + suffix)

    client = Mistral(model=model,
                     cache_dir=Path(os.environ.get("PL_CACHE",
                                                   str(out_dir("_cache")))))
    t0 = time.time()
    arm = f"{phase}_{model_key}{suffix}"
    if phase == "det":
        n = phase_det(client, suite, arm, "both")
    elif phase == "det_pol":
        n = phase_det(client, suite, arm, "policy")
    elif phase == "det_tool":
        n = phase_det(client, suite, arm, "tool")
    elif phase == "listwise":
        n = phase_listwise(client, suite, arm, pair_dir)
    elif phase == "ev":
        n = phase_ev(client, suite, arm)
    elif phase == "evjudge":
        n = phase_evjudge(client, suite, arm, out_dir(f"ev_{model_key}{suffix}"))
    elif phase == "qa":
        n = phase_qa(client, suite, arm)
    elif phase == "dir":
        n = phase_dir(client, suite, arm)
    elif phase == "dir_pred":
        arm = f"dir_pred_{os.environ.get('PL_DETECTION', 'base')}_{model_key}{suffix}"
        n = phase_dir_pred(client, suite, arm,
                           out_dir(f"det_{model_key}{suffix}"), pair_dir)
    elif phase == "cls_pred":
        arm = f"cls_pred_{os.environ.get('PL_DETECTION', 'base')}_{model_key}{suffix}"
        n = phase_cls_pred(client, suite, arm,
                           out_dir(f"det_{model_key}{suffix}"), pair_dir,
                           out_dir(f"dir_pred_{os.environ.get('PL_DETECTION', 'base')}_{model_key}{suffix}"))
    elif phase == "grp":
        n = phase_grp(client, suite, arm, out_dir(f"det_{model_key}{suffix}"))
    elif phase == "cls":
        n = phase_cls(client, suite, arm)
    else:
        raise SystemExit(f"unknown phase {phase}")
    write_usage(arm, {"phase": phase, "model": model, "suite": which,
                      "calls": n, "wall_seconds": round(time.time() - t0, 1)})
    print(f"{arm}: {n} calls in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
