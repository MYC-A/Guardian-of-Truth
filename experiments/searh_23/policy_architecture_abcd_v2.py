"""Format-controlled repeat of V1, frozen before any V1 gold scoring.

V1 exposed a transport/contract failure: JSON mode returned nested objects and
arrays for fields that its runner required as strings/scalars. V2 changes the
response format for *all* arms to explicit stage schemas. Inputs, manual gold,
model, temperature, parser algorithms and scorer remain the same. V1 raw data
are preserved separately and must be reported as a failed protocol pilot.
"""
from __future__ import annotations

import argparse
import json

import policy_architecture_abcd_v1 as v1


BASE = v1.ROOT / "experiments/searh_23/policy_architecture_abcd_v2"
OUT = v1.ROOT / "outputs/searh_23/policy_architecture_abcd_v2"


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required or list(properties), "additionalProperties": False}


def string_enum(*items: str) -> dict:
    return {"type": "string", "enum": list(items)}


S = {"type": "string"}
STRING_ARRAY = {"type": "array", "items": S}
COND_NODE = obj({"op": string_enum("ATOM", "AND", "OR", "NOT"),
                 "quote": S, "temporal": string_enum("NONE", "LATEST", "PRIOR_TRUE"),
                 "children": {"type": "array", "items": {"$ref": "#/$defs/Cond"}}})
COND = {"anyOf": [{"$ref": "#/$defs/Cond"}, {"type": "null"}]}
DIRECTIVE = obj({"kind": string_enum(*sorted(v1.KINDS)), "action_quote": S,
                 "governed_tools": STRING_ARRAY, "condition": COND,
                 "before_quote": S, "exception_quote": S,
                 "exception_type": string_enum("NONE", "EXCEPT", "EVEN_IF"),
                 "scope_quote": S})
DIRECTIVES_SCHEMA = {**obj({"directives": {"type": "array", "items": DIRECTIVE}}),
                     "$defs": {"Cond": COND_NODE}}
SCHEMAS = {
    "A": DIRECTIVES_SCHEMA,
    "B_inventory": obj({"heads": {"type": "array", "items": obj({
        "kind": string_enum(*sorted(v1.KINDS)), "head_quote": S})}}),
    "B_detail": DIRECTIVES_SCHEMA,
    "C_macro": obj({"scope": string_enum("GLOBAL", "MODE", "EVENTUAL"),
                    "scope_quote": S, "clause": S}),
    "C_node": obj({"op": string_enum("ATOM", "AND", "OR", "GATE", "ORDER",
                                       "PERMIT", "FORBID", "EXCEPT", "EVEN_IF"),
                   "left": S, "right": S}),
    "D_rephrase": obj({"rephrased": S}),
    "D_select": obj({"type": string_enum("ATOMIC", "QUANTIFIED", "LOGICAL", "NEGATION")}),
    "D_logical": obj({"op": string_enum("AND", "OR", "GATE", "ORDER", "PERMIT",
                                          "FORBID", "EXCEPT", "EVEN_IF"),
                      "left": S, "right": S}),
    "D_quantified": obj({"quantifier": string_enum("FORALL", "EXISTS"),
                         "variable": S, "clause": S}),
    "D_negation": obj({"op": string_enum("NOT"), "clause": S}),
    "leaf": obj({"role": string_enum("ACTION", "CONDITION", "RESPONSE", "DESCRIPTIVE"),
                 "source_quote": S, "tools": STRING_ARRAY,
                 "temporal": string_enum("NONE", "LATEST", "PRIOR_TRUE")}),
}


def freeze() -> None:
    original = json.loads((v1.BASE / "frozen.json").read_text(encoding="utf-8"))
    original["version"] = 2
    for stage in ("A", "B_detail"):
        original["systems"][stage] += (" For the strict condition schema, EVERY condition node has"
            " op, quote, temporal, children. For ATOM set children=[]; for AND/OR/NOT"
            " set quote='' and temporal='NONE'. A missing condition is null.")
    original["schemas"] = {stage: {"type": "json_schema", "json_schema":
                            {"name": "Guardian" + stage.replace("_", ""),
                             "schema_definition": schema, "strict": True}}
                           for stage, schema in SCHEMAS.items()}
    original["note"] = "V1 pilot failed output contract; V2 schema correction frozen before V1 gold scoring"
    BASE.mkdir(parents=True, exist_ok=True)
    for name, data in (("frozen.json", original),
                       ("gold.json", json.loads((v1.BASE / "gold.json").read_text(encoding="utf-8")))):
        path = BASE / name
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != payload:
            raise ValueError("frozen V2 changed: " + name)
        path.write_text(payload, encoding="utf-8")
    print(json.dumps({"protocol_sha256": v1.digest(original), "gold_sha256":
                      v1.digest(json.loads((BASE / "gold.json").read_text(encoding="utf-8")))}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    args = parser.parse_args()
    v1.BASE, v1.OUT = BASE, OUT
    if args.phase == "freeze":
        # Source path is V1's immutable frozen protocol, not an output cache.
        v1.BASE = v1.ROOT / "experiments/searh_23/policy_architecture_abcd_v1"
        freeze()
    elif args.phase == "run":
        v1.run()
    else:
        print(json.dumps(v1.score(), ensure_ascii=False, indent=2))
