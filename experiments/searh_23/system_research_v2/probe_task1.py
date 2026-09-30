#!/usr/bin/env python3
"""Model role probe (directive §74): which model for which role.

Task 1 — raw policy extractor: RAW POLICY + tool catalog -> Policy Program JSON.
Scored on v1 DEV reviewed programs (4) + 2 new author calibration policies.
All data here is dev material; sealed v2 is frozen separately and later.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))

from v2_llm import chat, MODELS  # noqa: E402

SI = HERE.parent / "system_integration_v1"


def catalog_view(tools: list[dict]) -> list[dict]:
    """What the extractor may see: catalog + documented observable/effect predicates."""
    out = []
    for t in tools:
        predicates = []
        for c in t.get("documented_contracts", []):
            predicates.append({
                "predicate": c["predicate"],
                "entity_argument": c["entity_argument"],
                "result_value_path": c["result_value_path"],
                "strength": c["strength"],
                "allowed_values": c.get("allowed_values", []),
                "meaning": c.get("meaning", ""),
            })
        out.append({
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("parameters", {}),
            "result_schema": t.get("result_schema", {}),
            "documented_predicates": predicates,
        })
    return out


SYSTEM = """You convert a policy into an executable policy program. You receive:
- RAW POLICY (the only source of rules; copy quotes character-by-character)
- TOOL CATALOG with documented predicates (the only allowed predicates)

Return JSON:
{"programs":[
 {"governed_tool":"<catalog tool name governed by a rule>",
  "entity_argument":"<parameter naming the entity the rule scopes to>",
  "activation":null,
  "gate":<gate>,
  "complete":true,
  "governing_quote":"<exact policy substring licensing the rule>"
 }]}

"activation" is non-null ONLY when the rule applies to a numeric subset of
entities, e.g. refunds above 200:
  {"field":"<parameter>","op":"GT","value":<number>,"quote":"<exact substring>"}

<gate> is one of:
 {"all":[<gate>,...]}            every condition must hold
 {"any":[<gate>,...]}            at least one must hold
 {"unless":{"base":<gate>,"exception":<gate>}}  exception waives the base
 {"source":{"quote":"<exact policy substring>","gate":<gate>}}  span licensing
 {"atom":{"predicate":"<catalog predicate>","entity_type":"<entity type>",
   "value":<required scalar>,"allowed_strengths":["OBSERVED"],
   "scope_joins":{"<target param>":"<source param>"}}}

Rules:
- one program per governed tool; include a program only if the policy states
  a rule about performing/using that tool
- "complete"=true only if you listed every rule the policy states for this tool
- atom.value is the value the policy REQUIRES (inspection passed -> true)
- allowed_strengths: ["OBSERVED"] when a documented read can verify it;
  use ["EXECUTED"] only when the policy demands a completed action
- scope_joins maps the governed call's parameter names to the observing
  call's parameter names when they differ; {} when identical
- every quote must be an exact contiguous substring of the policy
- use only predicates from the catalog; never invent predicate names"""


def build_messages(policy: str, tools: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(
            {"RAW POLICY": policy, "TOOL CATALOG": catalog_view(tools)},
            ensure_ascii=False)},
    ]


def normalize_gate(node, policy: str):
    """Recursively validate a model gate; convert quotes to spans."""
    if not isinstance(node, dict) or len(node) != 1:
        return None, ["gate_shape_invalid"]
    op, body = next(iter(node.items()))
    if op in {"all", "any"}:
        if not isinstance(body, list) or not body:
            return None, ["conjunction_empty"]
        kids, kid_issues = [], []
        for child in body:
            k, iss = normalize_gate(child, policy)
            kid_issues += iss
            if k is not None:
                kids.append(k)
        if len(kids) != len(body):
            return None, kid_issues + ["conjunction_child_invalid"]
        return {op: kids}, kid_issues
    if op == "unless":
        if not isinstance(body, dict) or set(body) != {"base", "exception"}:
            return None, ["unless_shape_invalid"]
        base, i1 = normalize_gate(body["base"], policy)
        exc, i2 = normalize_gate(body["exception"], policy)
        if base is None or exc is None:
            return None, i1 + i2 + ["unless_child_invalid"]
        return {"unless": {"base": base, "exception": exc}}, i1 + i2
    if op == "source":
        if not isinstance(body, dict) or set(body) != {"quote", "gate"}:
            return None, ["source_shape_invalid"]
        q = body["quote"]
        if not isinstance(q, str) or q not in policy:
            return None, ["source_quote_not_substring"]
        child, iss = normalize_gate(body["gate"], policy)
        if child is None:
            return None, iss + ["source_child_invalid"]
        start = policy.index(q)
        return {"source": {"start": start, "end": start + len(q), "gate": child}}, iss
    if op == "atom":
        need = {"predicate", "entity_type", "value", "allowed_strengths", "scope_joins"}
        if not isinstance(body, dict) or not need.issubset(body):
            return None, ["atom_missing_fields"]
        if not isinstance(body.get("scope_joins"), dict):
            return None, ["atom_scope_joins_invalid"]
        return {"atom": {k: body[k] for k in need}}, []
    return None, ["operator_unsupported"]


def compile_programs(parsed, policy: str, tools: list[dict]):
    """Validate model output into program dicts + issues (no trust promotion)."""
    issues: list[str] = []
    if not isinstance(parsed, dict) or not isinstance(parsed.get("programs"), list):
        return [], ["top_shape_invalid"]
    catalog = {t["name"]: t for t in tools}
    out = []
    for i, item in enumerate(parsed["programs"]):
        tag = f"program[{i}]"
        if not isinstance(item, dict):
            issues.append(f"{tag}:not_object")
            continue
        tool = item.get("governed_tool")
        if tool not in catalog:
            issues.append(f"{tag}:tool_not_in_catalog")
            continue
        gate, gissues = normalize_gate(item.get("gate"), policy)
        if gate is None:
            issues += [f"{tag}:{x}" for x in gissues] + [f"{tag}:gate_invalid"]
            continue
        issues += [f"{tag}:{x}" for x in gissues]
        activation = None
        act = item.get("activation")
        if isinstance(act, dict):
            if (set(act) >= {"field", "op", "value", "quote"}
                    and act.get("op") == "GT" and isinstance(act.get("value"), (int, float))
                    and not isinstance(act.get("value"), bool)
                    and isinstance(act.get("quote"), str) and act["quote"] in policy):
                activation = {"field": act["field"], "op": "GT",
                              "value": act["value"]}
            else:
                issues.append(f"{tag}:activation_invalid")
        out.append({
            "policy": policy,
            "governed_tool": tool,
            "governed_description": catalog[tool].get("description", ""),
            "entity_argument": item.get("entity_argument"),
            "gate": gate,
            "when": activation,
            "complete_for_governed_action": bool(item.get("complete")),
            "governing_quote": item.get("governing_quote"),
        })
    return out, issues


# --- scoring vs reviewed gold (structure-normalized comparison) -------------

def _normalize_atom(atom: dict, entity_argument) -> dict | None:
    """Deterministic conventions: entity_type from predicate namespace,
    drop identity joins on the entity field (already enforced)."""
    a = dict(atom)
    pred = a.get("predicate")
    if not isinstance(pred, str) or "." not in pred:
        return None
    namespace = pred.split(".", 1)[0]
    if a.get("entity_type") in (None, namespace + "_id", namespace):
        a["entity_type"] = namespace
    joins = a.get("scope_joins") or {}
    a["scope_joins"] = {k: v for k, v in joins.items()
                        if not (k == v and k == entity_argument)}
    return a


def gate_signature(node: dict):
    """Signature ignoring source spans and conjunction order (semantics only)."""
    if "atom" in node:
        a = node["atom"]
        return ("atom", a.get("predicate"), a.get("entity_type"),
                json.dumps(a.get("value"), sort_keys=True),
                tuple(sorted(a.get("allowed_strengths", []))),
                tuple(sorted((a.get("scope_joins") or {}).items())))
    if "source" in node:
        return gate_signature(node["source"]["gate"])
    if "all" in node or "any" in node:
        op = "all" if "all" in node else "any"
        return (op, tuple(sorted(gate_signature(c) for c in node[op])))
    if "unless" in node:
        return ("unless", gate_signature(node["unless"]["base"]),
                gate_signature(node["unless"]["exception"]))
    return ("invalid",)


def program_signature(p: dict):
    gate = p.get("gate", {})
    ea = p.get("entity_argument")
    # normalize atoms recursively before signing
    def walk(node):
        if "atom" in node:
            fixed = _normalize_atom(node["atom"], ea)
            return {"atom": fixed} if fixed else {"atom": node["atom"]}
        if "source" in node:
            return {"source": {"start": 0, "end": 0, "gate": walk(node["source"]["gate"])}}
        if "all" in node or "any" in node:
            op = "all" if "all" in node else "any"
            return {op: [walk(c) for c in node[op]]}
        if "unless" in node:
            return {"unless": {"base": walk(node["unless"]["base"]),
                               "exception": walk(node["unless"]["exception"])}}
        return node
    return (p.get("governed_tool"), p.get("entity_argument"),
            json.dumps(p.get("when"), sort_keys=True),
            gate_signature(walk(gate)))


def score_against_gold(pred_programs, gold_programs):
    pred_set = set(program_signature(p) for p in pred_programs)
    gold_set = set(program_signature(p) for p in gold_programs)
    pred_tools = {p.get("governed_tool") for p in pred_programs}
    gold_tools = {p.get("governed_tool") for p in gold_programs}
    return {
        "governed_tool_recall": len(pred_tools & gold_tools) / max(1, len(gold_tools)),
        "governed_tool_precision": len(pred_tools & gold_tools) / max(1, len(pred_tools)),
        "program_exact": len(pred_set & gold_set),
        "program_gold": len(gold_set),
        "program_pred": len(pred_set),
    }


# --- dev material: 4 reviewed v1 policies + 2 author calibration policies ---

def _atom(predicate, entity_type, value, strengths=("OBSERVED",), joins=None):
    return {"atom": {"predicate": predicate, "entity_type": entity_type,
                     "value": value, "allowed_strengths": list(strengths),
                     "scope_joins": dict(joins or {})}}


def _src(start, end, gate):
    return {"source": {"start": start, "end": end, "gate": gate}}


def _tool(name, desc, params, schema, predicate, strength, values, meaning):
    return {"name": name, "description": desc, "parameters": params,
            "result_schema": schema,
            "documented_contracts": [
                {"entity_argument": list(params)[0],
                 "result_entity_path": "$." + list(params)[0],
                 "result_value_path": "$." + list(schema)[1],
                 "predicate": predicate, "strength": strength,
                 "allowed_values": values, "meaning": meaning}]}


def _mk_calibration():
    pol_a = ("A tank may be drained only after its salinity check was logged. "
             "Emergency draining is permitted without a logged check when the "
             "tank is overheated.")
    q1 = "A tank may be drained only after its salinity check was logged."
    q2 = ("Emergency draining is permitted without a logged check when the "
          "tank is overheated.")
    s1, e1 = pol_a.index(q1), pol_a.index(q1) + len(q1)
    s2, e2 = pol_a.index(q2), pol_a.index(q2) + len(q2)
    aquarium = {
        "family": "calib.aquarium",
        "policy": pol_a,
        "tools": [
            _tool("check_salinity", "Reads the current salinity of the tank.",
                  {"tank_id": "string"}, {"tank_id": "string", "salinity": "scalar"},
                  "tank.salinity", "OBSERVED", [],
                  "Reads the current salinity of the tank."),
            _tool("log_check", "Records that a salinity check was performed for the tank.",
                  {"tank_id": "string"}, {"tank_id": "string", "logged": "scalar"},
                  "tank.check_logged", "OBSERVED", [],
                  "Records whether a salinity check was logged."),
            _tool("read_temperature", "Reads the current water temperature of the tank.",
                  {"tank_id": "string"}, {"tank_id": "string", "overheated": "scalar"},
                  "tank.overheated", "OBSERVED", [],
                  "Reads whether the tank is overheated."),
            _tool("drain_tank", "Drains the tank; state=drained means completion.",
                  {"tank_id": "string"}, {"tank_id": "string", "state": "scalar"},
                  "tank.drain_state", "EXECUTED", ["drained"],
                  "Drains the tank; state=drained means completion."),
        ],
        "gold": [
            {"policy": None, "governed_tool": "drain_tank",
             "governed_description": "Drains the tank; state=drained means completion.",
             "governed_producer": None, "entity_argument": "tank_id",
             "gate": {"unless": {
                 "base": _src(s1, e1, _atom("tank.check_logged", "tank", True)),
                 "exception": _src(s2, e2, _atom("tank.overheated", "tank", True))}},
             "when": None, "evidence_source": "HUMAN_REVIEWED",
             "complete_for_governed_action": True},
        ],
    }
    pol_g = ("Repotting a plant above 40 centimetres requires both a humidity "
             "check and a pest inspection. Spraying is allowed at any time.")
    qg = ("Repotting a plant above 40 centimetres requires both a humidity "
          "check and a pest inspection.")
    sg, eg = pol_g.index(qg), pol_g.index(qg) + len(qg)
    greenhouse = {
        "family": "calib.greenhouse",
        "policy": pol_g,
        "tools": [
            _tool("check_humidity", "Reports whether a humidity check was completed for the plant.",
                  {"plant_id": "string"}, {"plant_id": "string", "checked": "scalar"},
                  "plant.humidity_checked", "OBSERVED", [],
                  "Reports whether a humidity check was completed for the plant."),
            _tool("inspect_pests", "Reports whether pests were found on the plant.",
                  {"plant_id": "string"}, {"plant_id": "string", "pests_found": "scalar"},
                  "plant.pest_inspected", "OBSERVED", [],
                  "Reports whether a pest inspection happened for the plant."),
            _tool("repot_plant", "Repots the plant; state=repotted means completion.",
                  {"plant_id": "string", "height": "number"},
                  {"plant_id": "string", "state": "scalar"},
                  "plant.repot_state", "EXECUTED", ["repotted"],
                  "Repots the plant; state=repotted means completion."),
        ],
        "gold": [
            {"policy": None, "governed_tool": "repot_plant",
             "governed_description": "Repots the plant; state=repotted means completion.",
             "governed_producer": None, "entity_argument": "plant_id",
             "gate": {"all": [
                 _src(sg, eg, _atom("plant.humidity_checked", "plant", True)),
                 _src(sg, eg, _atom("plant.pest_inspected", "plant", True))]},
             "when": {"field": "height", "op": "GT", "value": 40},
             "evidence_source": "HUMAN_REVIEWED",
             "complete_for_governed_action": True},
        ],
    }
    return [aquarium, greenhouse]


CALIBRATION = _mk_calibration()


def load_dev_cases():
    traj = json.loads((SI / "frozen" / "trajectories_v1" / "dev_inputs.json").read_text())
    reviewed = json.loads((SI / "reviewed_policy_programs_dev.json").read_text())
    by_policy: dict[str, list] = {}
    for p in reviewed["programs"]:
        by_policy.setdefault(p["policy"], []).append(p)
    cases = []
    seen = set()
    for row in traj:
        pol = row["system_policy"]
        if pol in by_policy and pol not in seen:
            seen.add(pol)
            cases.append({"policy": pol, "tools": row["available_tools"],
                          "gold": by_policy[pol], "family": row["family"]})
    cases.extend(CALIBRATION)
    return cases


def main():
    cases = load_dev_cases()
    models = sys.argv[1:] or list(MODELS)
    results = {}
    for model in models:
        per_case = []
        for case in cases:
            resp = chat(model, build_messages(case["policy"], case["tools"]),
                        max_tokens=3500)
            parsed = resp.get("parsed")
            if parsed is None:
                per_case.append({"family": case["family"], "error": "unparsed",
                                 "head": (resp.get("content") or "")[:150]})
                continue
            programs, issues = compile_programs(parsed, case["policy"], case["tools"])
            score = score_against_gold(programs, case["gold"])
            per_case.append({"family": case["family"], "n_pred": len(programs),
                             "issues": issues, **score})
        agg = {
            "tool_recall": round(sum(c.get("governed_tool_recall", 0)
                                     for c in per_case) / len(per_case), 3),
            "tool_precision": round(sum(c.get("governed_tool_precision", 0)
                                        for c in per_case) / len(per_case), 3),
            "program_exact": sum(c.get("program_exact", 0) for c in per_case),
            "program_gold": sum(c.get("program_gold", 0) for c in per_case),
            "parse_failures": sum(1 for c in per_case if "error" in c),
            "issue_count": sum(len(c.get("issues", [])) for c in per_case),
        }
        results[model] = {"aggregate": agg, "per_case": per_case}
        print(model, json.dumps(agg))
        sys.stdout.flush()
    out = HERE / "outputs" / "probe_task1.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", out)


if __name__ == "__main__":
    main()
