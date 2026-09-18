"""full_architecture_v1 — Phase B probe driver: jsonschema vs incumbent validator.

Corpora:
  1. SYNTHETIC EDGE CASES — hand-built (value, schema) pairs covering the whole
     accepted language plus boundary shapes (bool vs 1, integral float, nested
     unknown keyword, empty schema, malformed enums, arrays of objects...).
  2. REAL46 — every (tool schema, call arguments) pair the competition adapter
     can extract from the 46 real-valid cases (prompt trace calls + response
     calls; deterministic, no LLM).

Comparison per pair:
  verdict equality (True/False/None)
  diagnostic SET equality (order-independent; ordering documented as N3)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for p in (str(REPO / "src"), str(HERE.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from guardian_truth.parsing import parse_events
from guardian_truth.vnext.e2e.competition_adapter_v1 import adapt_competition_input
from guardian_truth.vnext.e2e.schema_validation_v1 import (
    certification_schema, validate_declared_json)
from probes.jsonschema_adapter import validate_with_jsonschema

OUT = REPO / "outputs" / "full_architecture_v1" / "probes"


# ------------------------------------------------------------------ corpus 1

def _synthetic_pairs() -> list[tuple[str, dict, dict]]:
    S = lambda **kw: dict(kw)
    pairs: list[tuple[str, dict, dict]] = []

    pairs += [
        ("bool-is-not-integer", {"a": True}, S(type="object", properties={"a": S(type="integer")}, required=["a"])),
        ("one-is-not-bool", {"a": 1}, S(type="object", properties={"a": S(type="boolean")})),
        ("integral-float-integer", {"a": 3.0}, S(type="object", properties={"a": S(type="integer")})),
        ("plain-integer-ok", {"a": 3}, S(type="object", properties={"a": S(type="integer")})),
        ("float-number-ok", {"a": 3.5}, S(type="object", properties={"a": S(type="number")})),
        ("int-number-ok", {"a": 3}, S(type="object", properties={"a": S(type="number")})),
        ("required-missing-two", {"b": 1}, S(type="object", properties={"a": S(type="integer"), "b": S(type="integer")}, required=["a", "b"])),
        ("additional-two", {"a": 1, "x": 2, "y": 3}, S(type="object", properties={"a": S(type="integer")}, additionalProperties=False)),
        ("additional-open", {"a": 1, "x": 2}, S(type="object", properties={"a": S(type="integer")})),
        ("enum-hit", {"a": "x"}, S(type="object", properties={"a": S(type="string", enum=["x", "y"])})),
        ("enum-miss", {"a": "z"}, S(type="object", properties={"a": S(type="string", enum=["x", "y"])})),
        ("enum-bool-vs-one", {"a": True}, S(type="object", properties={"a": S(enum=[1])})),
        ("enum-num-vs-bool", {"a": 1}, S(type="object", properties={"a": S(enum=[True])})),
        ("nested-type-error", {"a": {"b": "s"}}, S(type="object", properties={"a": S(type="object", properties={"b": S(type="integer")})})),
        ("array-items-ok", {"a": [1, 2]}, S(type="object", properties={"a": S(type="array", items=S(type="integer"))})),
        ("array-items-bad", {"a": [1, "x"]}, S(type="object", properties={"a": S(type="array", items=S(type="integer"))})),
        ("array-of-objects", {"a": [{"b": 1}, {"b": "s"}]}, S(type="object", properties={"a": S(type="array", items=S(type="object", properties={"b": S(type="integer")}, additionalProperties=False))})),
        ("array-of-objects-extra", {"a": [{"b": 1, "c": 2}]}, S(type="object", properties={"a": S(type="array", items=S(type="object", properties={"b": S(type="integer")}, additionalProperties=False))})),
        ("array-empty-schema-items", {"a": [1, "x", None]}, S(type="object", properties={"a": S(type="array", items={})})),
        ("empty-schema", {"anything": 1}, {}),
        ("top-level-type-mismatch", [1, 2], S(type="object")),
        ("top-level-ok", {"a": 1}, S(type="object")),
        ("null-type", None, S(type="null")),
        ("null-mismatch", "x", S(type="null")),
        ("unknown-keyword", {"a": 1}, S(type="object", properties={"a": S(type="integer")}, minLength=2)),
        ("nested-unknown-keyword", {"a": 1}, S(type="object", properties={"a": S(type="string", pattern="x")})),
        ("unsupported-type", {"a": 1}, S(type="object", properties={"a": S(type="unknownkind")})),
        ("malformed-enum", {"a": 1}, S(type="object", properties={"a": S(type="integer", enum=7)})),
        ("malformed-object-props", {"a": 1}, S(type="object", properties=[("a", 1)])),
        ("malformed-schema-root", {"a": 1}, "not-a-dict"),
        ("no-type-but-enum", 5, S(enum=[1, 2, 3])),
        ("bool-additional-missing", {"a": 1}, S(type="object", properties={"a": S(type="integer")}, required=["a"])),
        ("deep-nest-all-ok", {"a": {"b": [{"c": {"d": "x"}}]}}, _deep_schema()),
        ("deep-nest-bad-leaf", {"a": {"b": [{"c": {"d": 5, "e": 1}}]}}, _deep_schema()),
    ]
    return pairs


def _deep_schema() -> dict:
    leaf = {"type": "object", "properties": {"d": {"type": "string"}},
            "additionalProperties": False}
    item = {"type": "object", "properties": {"c": leaf},
            "additionalProperties": False}
    return {"type": "object", "properties": {"a": {
        "type": "object",
        "properties": {"b": {"type": "array", "items": item}}}}}


# ------------------------------------------------------------------ corpus 2

def _real46_pairs() -> tuple[list[tuple[str, dict, dict]], dict]:
    import pyarrow.parquet as pq
    table = pq.read_table(REPO / "valid.parquet")
    rows = table.to_pylist()
    pairs = []
    stats = {"cases": 0, "calls": 0, "skipped_unparsed": 0}
    for row in rows:
        record = {"id": row["id"], "prompt": row["prompt"],
                  "response": row["response"]}
        adapted = adapt_competition_input(record)
        stats["cases"] += 1
        schemas = {tool["name"]: tool["parameters"]
                   for tool in adapted.case.tool_schemas}
        cert = {name: certification_schema(
                    schema, object_fields_closed=adapted.case.object_fields_closed)
                for name, schema in schemas.items()}
        # calls from the prompt trace (history) and from the response text
        documents = [("prompt", row["prompt"]), ("response", row["response"])]
        for doc_name, doc in documents:
            for event in parse_events(doc, doc_name):
                if event.kind != "call" or not event.name:
                    continue
                stats["calls"] += 1
                if not event.json_valid or event.value is None:
                    stats["skipped_unparsed"] += 1
                    continue
                schema = cert.get(event.name)
                if schema is None:
                    continue
                pairs.append((f"{row['id']}::{event.name}@{doc_name}",
                              event.value, schema))
    return pairs, stats


# ------------------------------------------------------------------ compare

def _run(pairs, label):
    rows, mismatches = [], []
    for name, value, schema in pairs:
        cur_valid, cur_diag = validate_declared_json(value, schema)
        new_valid, new_diag = validate_with_jsonschema(value, schema)
        verdict_eq = cur_valid == new_valid
        diag_eq = (sorted(cur_diag) == sorted(new_diag))
        rows.append({"name": name, "cur": [cur_valid, list(cur_diag)],
                     "new": [new_valid, list(new_diag)],
                     "verdict_eq": verdict_eq, "diag_eq": diag_eq})
        if not verdict_eq or not diag_eq:
            mismatches.append(rows[-1])
    summary = {
        "corpus": label,
        "pairs": len(pairs),
        "verdict_mismatches": sum(1 for r in rows if not r["verdict_eq"]),
        "diag_mismatches": sum(1 for r in rows if r["verdict_eq"] and not r["diag_eq"]),
        "examples": mismatches[:25],
    }
    return summary, rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    syn_pairs = _synthetic_pairs()
    real_pairs, real_stats = _real46_pairs()
    syn_summary, _ = _run(syn_pairs, "synthetic-edge-cases")
    real_summary, _ = _run(real_pairs, "real46-declared-schemas")
    payload = {
        "synthetic": syn_summary,
        "real46": {**real_summary, "extraction_stats": real_stats},
        "normalizations": {
            "N1_integer_float": "incumbent rejects 3.0 as integer; jsonschema accepts; adapter enforces incumbent semantics",
            "N2_required_additional": "adapter recomputes per-key diagnostics (jsonschema collapses messages)",
            "N3_ordering": "diagnostic order differs; sets compared",
        },
    }
    (OUT / "jsonschema_comparison.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "examples"}
                      for k, v in payload.items() if isinstance(v, dict)},
                     indent=1))
    print("mismatch examples (synthetic):",
          len(syn_summary["examples"]), "| (real46):", len(real_summary["examples"]))


if __name__ == "__main__":
    main()
