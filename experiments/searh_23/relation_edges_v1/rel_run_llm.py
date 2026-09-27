"""LLM arms for the relation-edges research (narrow pair questions + e2e).

Arms per model (mistral = ministral-14b-latest, codestral = codestral-latest):
  DET_{model}  relation detection, one narrow question per candidate pair
               (all pairs of the universe) -> RELATED / NOT_RELATED / UNKNOWN
  CLS_{model}  relation classification, one narrow question per pair
               (all pairs, so classification metrics can be computed on
               correct endpoints independently of detector selection)
  GRP_{model}  group logic (AND/OR/XOR) for target operations with >= 2
               RELATED parents according to the SAME model's DET arm
  E2E_{model}  baseline: full policy graph in a single call

All prompts are name-blind: tool names are never rendered, only the
description + schema. Roles are given (they are predicted upstream in the
real pipeline; the oracle track uses the frozen roles).

Run:
  REL_SUITE=original REL_MODEL=mistral   python3 rel_run_llm.py det
  REL_SUITE=original REL_MODEL=mistral   python3 rel_run_llm.py cls
  REL_SUITE=original REL_MODEL=mistral   python3 rel_run_llm.py grp
  REL_SUITE=original REL_MODEL=mistral   python3 rel_run_llm.py e2e
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rel_common import (load_suite, out_dir, render_tool, sentence_of,
                        tools_by_name, pair_universe, suffix_for, RELATION_DEFS)

from oc_common import Mistral

MODELS = {
    "mistral": "ministral-14b-latest",
    "codestral": "codestral-latest",
}

DIR_SYSTEM = ("You are a policy-compliance analyst. You judge only from the given "
              "policy text. Answer strictly as a single JSON object, no extra "
              "text.")

SYSTEM = ("You are a policy-compliance analyst. You judge only from the given "
          "policy text and the event descriptions. Tool names are never shown; "
          "tool semantics come from the descriptions provided. Answer strictly "
          "as a single JSON object, no extra text.")


def render_event(case, ev, label):
    policy = case["policy"]
    by_name = tools_by_name(case)
    sent, _ = sentence_of(ev["source_span"], policy)
    tools = " ".join(render_tool(by_name[n]) for n in ev.get("governed_tools", [])
                     if n in by_name)
    return (f'{label}: "{ev["source_span"]}" (role: {ev["role"]})\n'
            f'Context sentence for {label}: "{sent or ""}"\n'
            f'Tool semantics for {label}: {tools or "none"}\n')


def det_user(case, a, b):
    return (f"POLICY:\n{case['policy']}\n\n"
            f"{render_event(case, a, 'EVENT A')}\n"
            f"{render_event(case, b, 'EVENT B')}\n"
            "Question: in this policy, does event A stand in a regulatory or "
            "temporal relation to event B - does A gate, precede, enable, "
            "trigger or except B, or is A explicitly stated NOT to block B? "
            "Answer only from the policy text.\n"
            'Answer strictly as JSON: {"decision": "RELATED" or "NOT_RELATED" '
            'or "UNKNOWN", "reason": "one short sentence"}')


def cls_user(case, a, b):
    defs = "\n".join(f"- {k}: {v}" for k, v in RELATION_DEFS.items())
    return (f"POLICY:\n{case['policy']}\n\n"
            f"{render_event(case, a, 'EVENT A')}\n"
            f"{render_event(case, b, 'EVENT B')}\n"
            f"Relation types:\n{defs}\n\n"
            "Question: which relation best describes how event A relates to "
            "event B in this policy? If two readings are genuinely plausible, "
            "list both in possible_relations (most plausible first). If the "
            "direction between the two events is uncertain, reflect that in "
            "direction_confidence.\n"
            'Answer strictly as JSON: {"relation": "<primary type>", '
            '"possible_relations": ["<primary type>", "..."], '
            '"direction_confidence": "high" or "low", '
            '"reason": "one short sentence"}')


def grp_user(case, target, parents):
    lines = "\n".join(f'{i}. "{p["source_span"]}" (role: {p["role"]})'
                      for i, p in enumerate(parents, 1))
    return (f"POLICY:\n{case['policy']}\n\n"
            f'TARGET OPERATION: "{target["source_span"]}" (role: {target["role"]})\n'
            f"Events that gate or precede the target:\n{lines}\n\n"
            "Question: does the policy require ALL of these events before the "
            "target operation (AND), or at least ONE of them (OR), or exactly "
            "one of them (XOR)?\n"
            'Answer strictly as JSON: {"logic": "AND" or "OR" or "XOR" or '
            '"UNKNOWN", "reason": "one short sentence"}')


def dir_user(case, a, b):
    return (f"POLICY:\n{case['policy']}\n\n"
            f"EVENT A: \"{a['source_span']}\" (role: {a['role']})\n"
            f"EVENT B: \"{b['source_span']}\" (role: {b['role']})\n\n"
            "Question: according to this policy, which event must happen "
            "first, or acts as the prerequisite/trigger for the other? "
            "If neither precedes the other in the policy, answer UNCLEAR.\n"
            'Answer strictly as JSON: {"first": "A" or "B" or "UNCLEAR", '
            '"reason": "one short sentence"}')


def e2e_user(case):
    by_name = tools_by_name(case)
    catalog = "\n".join(f"- {render_tool(t)}" for t in case["tools"])
    roles = "OPERATION_EFFECT, PRECONDITION_CHECK, STATE_OBSERVATION, COMMUNICATION, OTHER"
    rels = ", ".join(RELATION_DEFS.keys())
    return (f"POLICY:\n{case['policy']}\n\n"
            f"TOOL SEMANTICS (tool names are hidden; only semantics are given):\n{catalog}\n\n"
            "Extract the policy graph.\n"
            "1. events: every business action, executable check, state "
            "observation, communication or purely descriptive mention, each "
            "with its exact source span from the policy and its role.\n"
            f"   Roles: {roles}\n"
            "2. edges: for each pair of events where one gates, precedes, "
            "enables, triggers or excepts the other, give from_span (the "
            "earlier/gating/triggering event), to_span (the later/gated/"
            "obligated operation) and the relation.\n"
            f"   Relations: {rels}\n"
            "3. groups: when several conditions jointly (AND) or "
            "alternatively (OR) gate one operation, describe the group.\n"
            'Answer strictly as JSON: {"events": [{"span": "...", "role": '
            '"..."}], "edges": [{"from_span": "...", "to_span": "...", '
            '"relation": "..."}], "groups": [{"logic": "AND" or "OR", '
            '"members": ["span", "..."], "target": "span"}]}')


def detected_unordered_pairs(which, model_key):
    """POST-HOC detector combo: (ce score >= 0.35 band) AND mistral RELATED.
    Same rule as combo_band in rel_score.py (designed after opening the
    original results)."""
    from rel_common import FROZEN as FZ
    import json as _json
    gold_det = load_pairs_public(which, "DET_local")
    mist = load_pairs_public(which, f"det_{model_key}")
    cases = load_suite(which)
    out = {}
    for case in cases:
        cid = case["case_id"]
        m_ce = {(r["from_span"], r["to_span"]): r for r in gold_det.get(cid, [])}
        m_mi = {(r["from_span"], r["to_span"]): r for r in mist.get(cid, [])}
        ev_by_span = {e["source_span"]: e for e in case["events"]}
        spans = [e["source_span"] for e in case["events"] if e["role"] != "OTHER"]
        seen = set()
        pairs = []
        for i, a in enumerate(spans):
            for b in spans[i + 1:]:
                key = frozenset((a, b))
                if key in seen:
                    continue
                seen.add(key)

                def pos(x, y):
                    ce_row = m_ce.get((x, y)) or {}
                    ce_ok = ce_row.get("ce_decision") in ("RELATED", "UNKNOWN")
                    mi_ok = (m_mi.get((x, y)) or {}).get("decision") == "RELATED"
                    return ce_ok and mi_ok

                if pos(a, b) or pos(b, a):
                    pairs.append((ev_by_span[a], ev_by_span[b]))
        out[cid] = pairs
    return out


def load_pairs_public(which, arm_dir):
    outdir = out_dir(arm_dir + suffix_for(which))
    pairs = {}
    for f in sorted(outdir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        pairs[data["case_id"]] = data.get("pairs", [])
    return pairs


def run_phase(phase, model_key, which):
    model = MODELS[model_key]
    suite = load_suite(which)
    client = Mistral(model=model, cache_dir=out_dir(f"_cache_{model_key}"))
    outdir = out_dir(f"{phase}_{model_key}" + suffix_for(which))
    t0 = time.time()
    n_calls = 0

    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue

        if phase == "det":
            rows = []
            for a, b in pair_universe(case["events"]):
                rec = client.ask(SYSTEM, det_user(case, a, b), max_tokens=220)
                parsed, err = Mistral.parse_json(rec["raw"])
                n_calls += 0 if rec.get("cached") else 1
                dec = parsed.get("decision", "UNKNOWN") if parsed else "UNKNOWN"
                if dec not in ("RELATED", "NOT_RELATED", "UNKNOWN"):
                    dec = "UNKNOWN"
                rows.append({"from_span": a["source_span"], "to_span": b["source_span"],
                             "from_role": a["role"], "to_role": b["role"],
                             "decision": dec,
                             "reason": parsed.get("reason", "") if parsed else "",
                             "parse_error": err, "raw": rec["raw"][:400],
                             "cached": rec.get("cached", False),
                             "latency": rec.get("latency")})
            payload = {"case_id": case["case_id"], "pairs": rows}

        elif phase == "cls":
            rows = []
            for a, b in pair_universe(case["events"]):
                rec = client.ask(SYSTEM, cls_user(case, a, b), max_tokens=400)
                parsed, err = Mistral.parse_json(rec["raw"])
                n_calls += 0 if rec.get("cached") else 1
                rel = parsed.get("relation", "UNKNOWN") if parsed else "UNKNOWN"
                poss = parsed.get("possible_relations") or []
                if not isinstance(poss, list) or not poss:
                    poss = [rel] if rel else []
                rows.append({"from_span": a["source_span"], "to_span": b["source_span"],
                             "from_role": a["role"], "to_role": b["role"],
                             "relation": rel,
                             "possible_relations": poss,
                             "direction_confidence": parsed.get("direction_confidence", "") if parsed else "",
                             "reason": parsed.get("reason", "") if parsed else "",
                             "parse_error": err, "raw": rec["raw"][:400],
                             "cached": rec.get("cached", False),
                             "latency": rec.get("latency")})
            payload = {"case_id": case["case_id"], "pairs": rows}

        elif phase == "grp":
            det_dir = out_dir(f"det_{model_key}" + suffix_for(which))
            det_file = det_dir / f"{case['case_id']}.json"
            if not det_file.is_file():
                continue
            det = json.loads(det_file.read_text(encoding="utf-8"))
            parents_by_target = {}
            for row in det["pairs"]:
                if row["decision"] == "RELATED":
                    parents_by_target.setdefault(row["to_span"], []).append(row)
            events_by_span = {e["source_span"]: e for e in case["events"]}
            groups = []
            for target_span, prows in parents_by_target.items():
                if len(prows) < 2 or target_span not in events_by_span:
                    continue
                parents = [events_by_span[r["from_span"]] for r in prows
                           if r["from_span"] in events_by_span]
                if len(parents) < 2:
                    continue
                rec = client.ask(SYSTEM, grp_user(case, events_by_span[target_span],
                                                  parents), max_tokens=220)
                parsed, err = Mistral.parse_json(rec["raw"])
                n_calls += 0 if rec.get("cached") else 1
                logic = parsed.get("logic", "UNKNOWN") if parsed else "UNKNOWN"
                if logic not in ("AND", "OR", "XOR", "UNKNOWN"):
                    logic = "UNKNOWN"
                groups.append({"target": target_span,
                               "parents": [p["source_span"] for p in parents],
                               "logic": logic,
                               "reason": parsed.get("reason", "") if parsed else "",
                               "parse_error": err,
                               "cached": rec.get("cached", False),
                               "latency": rec.get("latency")})
            payload = {"case_id": case["case_id"], "groups": groups}

        elif phase == "dir":
            """POST-HOC direction arm: for every unordered pair detected by the
            ce-band + mistral combo, ask which event happens first."""
            det_pairs = detected_unordered_pairs(which, model_key)
            rows = []
            for a, b in det_pairs.get(case["case_id"], []):
                rec = client.ask(DIR_SYSTEM, dir_user(case, a, b), max_tokens=200)
                parsed, err = Mistral.parse_json(rec["raw"])
                n_calls += 0 if rec.get("cached") else 1
                first = parsed.get("first", "UNCLEAR") if parsed else "UNCLEAR"
                if first not in ("A", "B", "UNCLEAR"):
                    first = "UNCLEAR"
                rows.append({"a_span": a["source_span"], "b_span": b["source_span"],
                             "first": first,
                             "reason": parsed.get("reason", "") if parsed else "",
                             "parse_error": err,
                             "cached": rec.get("cached", False),
                             "latency": rec.get("latency")})
            payload = {"case_id": case["case_id"], "pairs": rows}

        elif phase == "e2e":
            rec = client.ask(SYSTEM, e2e_user(case), max_tokens=2000)
            parsed, err = Mistral.parse_json(rec["raw"])
            n_calls += 0 if rec.get("cached") else 1
            payload = {"case_id": case["case_id"], "graph": parsed or {},
                       "parse_error": err, "raw": rec["raw"][:6000],
                       "latency": rec.get("latency")}

        else:
            raise SystemExit(f"unknown phase {phase}")

        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    from rel_common import write_usage
    write_usage(f"{phase}_{model_key}" + suffix_for(which), {
        "wall_seconds": round(time.time() - t0, 1),
        "suite": which, "model": model, "fresh_calls": n_calls,
        "usage": client.usage_total,
    })
    print(f"{phase}_{model_key} done {which}: fresh_calls={n_calls} "
          f"tokens={client.usage_total.get('total_tokens', 0)}")


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "det"
    which = os.environ.get("REL_SUITE", "original")
    model_key = os.environ.get("REL_MODEL", "mistral")
    run_phase(phase, model_key, which)


if __name__ == "__main__":
    main()
