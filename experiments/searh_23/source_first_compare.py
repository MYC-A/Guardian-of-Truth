"""Frozen A/B/E policy parser comparison; run never imports or opens gold.

E creates every semantic node from source token intervals. JSON schemas, prompts,
case selection and scorer are frozen in experiments/.../source_first_v1 before API.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import policy_architecture_abcd_v1 as old
import policy_architecture_abcd_v2 as old2

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "experiments/searh_23/source_first_v1"
OUT = ROOT / "outputs/searh_23/source_first_v1"
sys.path.insert(0, str(ROOT / "experiments/searh_23"))


def obj(fields: dict) -> dict:
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


I = {"type": "integer"}
S = {"type": "string"}
SPAN = obj({"start": I, "end": I})  # token interval [start,end), not free text
NULL_SPAN = {"anyOf": [SPAN, {"type": "null"}]}
COND = obj({"span": SPAN, "temporal": {"type": "string", "enum": ["NONE", "LATEST", "PRIOR_TRUE"]}})
HEADS = obj({"actions": {"type": "array", "items": SPAN}})
DETAIL = obj({
    "kind": {"type": "string", "enum": sorted(old.KINDS)},
    "governed_tools": {"type": "array", "items": S},
    "conditions": {"type": "array", "items": COND},
    "condition_op": {"type": "string", "enum": ["NONE", "ATOM", "AND", "OR", "NOT"]},
    "before": NULL_SPAN,
    "exception": NULL_SPAN,
    "exception_type": {"type": "string", "enum": ["NONE", "EXCEPT", "EVEN_IF"]},
    "scope": NULL_SPAN,
})
AUDIT = obj({"missing_actions": {"type": "array", "items": SPAN}})
VERIFY_ITEM = obj({"id": S, "valid": {"type": "boolean"},
                   "reason": {"type": "string", "enum": ["SUPPORTED", "WRONG_ACTION", "WRONG_BINDING", "MISSING_CONDITION", "WRONG_ORDER", "WRONG_SPAN", "OTHER", "UNCERTAIN"]}})
VERIFY = obj({"checks": {"type": "array", "items": VERIFY_ITEM}})

SYSTEMS_E = {
    "E_heads": "Find every distinct SOURCE directive governed action or response, including permission/prohibition facets, response duties and explicit descriptive non-equivalence. Return ONLY token intervals [start,end) for the minimal action phrase in the indexed ORIGINAL policy. Do not return conditions, derived contrapositives, or paraphrases. Each interval must name the action of an independently stated direction. Preserve all directions, including separate actions with shared conditions.",
    "E_detail": "For the ONE given source-anchored action, attach only source clauses that govern THAT action. Return kind, exact catalog names of tools executing it, every necessary condition as a token interval, connective AND/OR/NOT or ATOM/NONE, temporal type of each condition, an earlier operation for ORDER, exception, and contextual scope as token intervals or null. A check/lookup is not the later action. Do not invent any text or create another directive. If the action cannot be grounded, leave fields empty; the compiler will mark UNKNOWN. Condition clauses for another nearby action must not attach here. GATE is a state or check prerequisite; ORDER is a separate operation preceding another operation. For FORBID, conditions specify when forbidden. FORBID with EXCEPT is a base prohibition with an exception.",
    "E_audit": "Independently read the complete indexed ORIGINAL policy and already found action spans. Return token intervals for any EXPLICIT independent policy directions omitted from the found spans. Do not return conditions, examples, or logically derived contrapositives. If none, return empty array. This is a completeness audit, not a rewrite.",
    "E_verify": "Verify each candidate IR against the ORIGINAL policy, using source span text and semantic parent binding. For each candidate ID, decide whether the action, condition attachment, relation, temporal ordering and all source spans are supported. A condition attached to the wrong neighboring action is invalid even when both quotes exist. A required condition dropped is invalid. Correct operator with wrong span is invalid. Return one check per ID; use UNCERTAIN if source does not determine the answer. Do not repair candidates.",
}


def tokens(policy: str) -> list[dict]:
    return [{"i": i, "start": m.start(), "end": m.end(), "text": m.group()}
            for i, m in enumerate(re.finditer(r"\w+|[^\w\s]", policy))]


def source_span(policy: str, toks: list[dict], value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    a, b = value.get("start"), value.get("end")
    if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(toks):
        return None
    start, end = toks[a]["start"], toks[b - 1]["end"]
    return {"source_start": start, "source_end": end,
            "exact_source_text": policy[start:end], "token_start": a, "token_end": b}


def freeze() -> None:
    from source_first_cases import cases
    prior = json.loads((old2.BASE / "frozen.json").read_text(encoding="utf-8"))
    rows = cases()
    for row in rows:
        policy = row["policy"]
        for q in old.all_quotes(row["gold"]):
            if policy.count(q) != 1:
                raise ValueError(f"gold quote missing/ambiguous {row['id']}: {q}")
    protocol = {"version": 1, "arms": ["A_one_shot", "B_staged", "E_source_first"],
                "model_note": "Same server MISTRAL_MODEL, temperature 0, all arms paired. New authored cases only.",
                "max_tokens": 3000, "systems": {**{k: prior["systems"][k] for k in ("A", "B_inventory", "B_detail")}, **SYSTEMS_E},
                "schemas": {**{k: prior["schemas"][k] for k in ("A", "B_inventory", "B_detail")},
                    **{k: {"type": "json_schema", "json_schema": {"name": "Guardian" + k, "schema": v, "strict": True}}
                       for k, v in {"E_heads": HEADS, "E_detail": DETAIL, "E_audit": AUDIT, "E_verify": VERIFY}.items()}},
                "cases": [{"id": r["id"], "origin": "unseen_authored", "query": {"policy": r["policy"], "tools": r["tools"]}} for r in rows],
                "scoring": {"action_match": "exact quote OR token character IoU >= 0.5, one-to-one same kind",
                            "condition_match": "exact quote OR token character IoU >= 0.5, same matched parent",
                            "strict_ir": "old.exact tuple equality, unordered directives",
                            "coverage": "gold directive action and condition nodes grounded to same parent; no broad policy-span credit",
                            "unknown": "any malformed source span, invalid tool, invalid condition cardinality, or audit missing action"},
                "counterfactuals": ["neighbor_action", "wrong_parent", "drop_condition", "swap_order", "wrong_span"]}
    gold = {r["id"]: r["gold"] for r in rows}
    BASE.mkdir(parents=True, exist_ok=True)
    for name, value in (("frozen.json", protocol), ("gold.json", gold)):
        target = BASE / name
        serialized = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if target.exists() and target.read_text(encoding="utf-8") != serialized:
            raise ValueError("frozen file changed: " + str(target))
        target.write_text(serialized, encoding="utf-8")
    print(json.dumps({"protocol_sha256": old.digest(protocol), "gold_sha256": old.digest(gold), "cases": len(rows)}))


def recorder(protocol: dict, model: old.MistralRaw, arm: str, case: dict) -> old.Recorder:
    old.OUT = OUT
    return old.Recorder(protocol, model, arm, case)


def compile_e(protocol: dict, model: old.MistralRaw, case: dict) -> dict:
    rec = recorder(protocol, model, "E_source_first", case)
    query, policy = case["query"], case["query"]["policy"]
    toks = tokens(policy)
    indexed = [{"i": t["i"], "text": t["text"]} for t in toks]
    base = {"policy": policy, "indexed_tokens": indexed, "tools": query["tools"]}
    heads = rec.ask("E_heads", base).get("actions", [])
    errors, nodes, directives = [], [], []
    if not isinstance(heads, list):
        heads, errors = [], ["invalid_heads"]
    seen = set()
    for ix, raw in enumerate(heads[:12]):
        action = source_span(policy, toks, raw)
        if not action or (action["source_start"], action["source_end"]) in seen:
            errors.append(f"invalid_or_duplicate_action_{ix}")
            continue
        seen.add((action["source_start"], action["source_end"]))
        answer = rec.ask("E_detail", {**base, "action": action})
        kind = answer.get("kind")
        tools = answer.get("governed_tools")
        if kind not in old.KINDS or not isinstance(tools, list) or any(t not in query["tools"] for t in tools):
            errors.append(f"invalid_kind_or_tools_{ix}")
            continue
        conds = []
        invalid = False
        for raw_cond in answer.get("conditions", []):
            span = source_span(policy, toks, raw_cond.get("span") if isinstance(raw_cond, dict) else None)
            temporal = raw_cond.get("temporal") if isinstance(raw_cond, dict) else None
            if not span or temporal not in {"NONE", "LATEST", "PRIOR_TRUE"}:
                invalid = True
                break
            conds.append({**span, "temporal": temporal, "parent_action_id": ix})
        before = source_span(policy, toks, answer.get("before")) if answer.get("before") else None
        exception = source_span(policy, toks, answer.get("exception")) if answer.get("exception") else None
        scope = source_span(policy, toks, answer.get("scope")) if answer.get("scope") else None
        if invalid or any(answer.get(k) is not None and v is None for k, v in (("before", before), ("exception", exception), ("scope", scope))):
            errors.append(f"invalid_child_span_{ix}")
            continue
        op = answer.get("condition_op")
        if (not conds and op != "NONE") or (len(conds) == 1 and op != "ATOM") or (len(conds) > 1 and op not in {"AND", "OR"}):
            errors.append(f"invalid_condition_cardinality_{ix}")
            continue
        exc_type = answer.get("exception_type")
        if exc_type not in {"NONE", "EXCEPT", "EVEN_IF"} or bool(exception) != (exc_type != "NONE"):
            errors.append(f"invalid_exception_{ix}")
            continue
        cond = None
        if len(conds) == 1:
            cond = old.atom(conds[0]["exact_source_text"], conds[0]["temporal"])
        elif len(conds) > 1:
            cond = old.connective(op, *(old.atom(c["exact_source_text"], c["temporal"]) for c in conds))
        d = old.directive(kind, action["exact_source_text"], sorted(set(tools)), cond,
                          before=before["exact_source_text"] if before else "",
                          exception=exception["exact_source_text"] if exception else "",
                          exception_type=exc_type,
                          scope=scope["exact_source_text"] if scope else "")
        directives.append(d)
        nodes.append({"id": ix, "action": action, "kind": kind, "governed_tools": sorted(set(tools)),
                      "conditions": conds, "condition_op": op, "before": before,
                      "exception": exception, "exception_type": exc_type, "scope": scope})
    if len(heads) > 12:
        errors.append("too_many_heads")
    audit = rec.ask("E_audit", {**base, "found_actions": [n["action"] for n in nodes]})
    missing = []
    for raw in audit.get("missing_actions", []):
        span = source_span(policy, toks, raw)
        if span:
            missing.append(span)
        else:
            errors.append("invalid_audit_span")
    if missing:
        errors.append("audit_found_missing_actions")
    result = {"case_id": case["id"], "arm": "E_source_first", "model": model.model,
              "protocol_sha256": old.digest(protocol), "query_sha256": old.digest(query),
              "directives": directives, "nodes": nodes, "audit_missing": missing,
              "unknown": bool(errors), "errors": errors, "calls": rec.calls}
    return result


def mutate(nodes: list[dict]) -> list[dict]:
    """Frozen generic perturbations of accepted nodes, no gold or domain terms."""
    base = [{"id": "base_" + str(n["id"]), "node": n} for n in nodes]
    out = list(base)
    for n in nodes:
        i = n["id"]
        others = [x for x in nodes if x["id"] != i]
        if others:
            changed = json.loads(json.dumps(n)); changed["action"] = others[0]["action"]
            out.append({"id": f"neighbor_action_{i}", "node": changed})
        if n["conditions"] and others:
            changed = json.loads(json.dumps(n)); changed["conditions"][0]["parent_action_id"] = others[0]["id"]
            out.append({"id": f"wrong_parent_{i}", "node": changed})
        if n["conditions"]:
            changed = json.loads(json.dumps(n)); changed["conditions"].pop(0)
            out.append({"id": f"drop_condition_{i}", "node": changed})
        if n["before"]:
            changed = json.loads(json.dumps(n)); changed["action"], changed["before"] = changed["before"], changed["action"]
            out.append({"id": f"swap_order_{i}", "node": changed})
        if n["conditions"]:
            changed = json.loads(json.dumps(n)); changed["conditions"][0].update({k: n["action"][k] for k in ("source_start", "source_end", "exact_source_text", "token_start", "token_end")})
            out.append({"id": f"wrong_span_{i}", "node": changed})
    return out


def verify_e(protocol: dict, model: old.MistralRaw, case: dict, result: dict) -> dict:
    rec = recorder(protocol, model, "E_verify", case)
    candidates = mutate(result["nodes"])
    if not candidates:
        return {"candidates": [], "checks": [], "calls": []}
    query = {"policy": case["query"]["policy"], "candidates": candidates}
    answer = rec.ask("E_verify", query)
    checks = answer.get("checks", [])
    return {"candidates": candidates, "checks": checks if isinstance(checks, list) else [], "calls": rec.calls}


def run() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    model = old.MistralRaw()
    old.OUT = OUT
    print(json.dumps({"model": model.model, "cases": len(protocol["cases"]), "protocol_sha256": old.digest(protocol)}), flush=True)
    for case in protocol["cases"]:
        for arm in protocol["arms"]:
            path = OUT / "results" / arm / (case["id"] + ".json")
            if path.exists():
                continue
            if arm == "E_source_first":
                result = compile_e(protocol, model, case)
                v = verify_e(protocol, model, case, result)
                result["verification"] = v
            else:
                result = old.run_one(protocol, model, arm, case)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"case": case["id"], "arm": arm, "directives": len(result["directives"]),
                              "errors": result["errors"], "calls": len(result["calls"])}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    phase = parser.parse_args().phase
    if phase == "freeze":
        freeze()
    elif phase == "run":
        run()
    else:
        import source_first_score
        print(json.dumps(source_first_score.score(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
