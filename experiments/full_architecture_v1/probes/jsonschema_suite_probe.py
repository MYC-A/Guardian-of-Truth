"""full_architecture_v1 — Phase B probe: official JSON Schema Test Suite subset.

Directive §5: "official JSON Schema Test Suite if practical".

Practical interpretation for a strict-subset validator: run every suite test
group (draft 2020-12) whose SCHEMA uses only the shared language
{type, properties, required, additionalProperties, items, enum} (after
ignoring the purely declarative "$schema" key), through BOTH the incumbent
and the jsonschema adapter, and measure:
  1. PARITY between the two implementations (verdict + diagnostic sets)
  2. AGREEMENT with the suite's expected verdict, where both are defined
     (incumbent semantics: "valid" maps to True; "invalid" to False;
     fail-closed None counts as abstention, not disagreement)
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

from guardian_truth.vnext.e2e.schema_validation_v1 import (
    validate_declared_json)
from probes.jsonschema_adapter import validate_with_jsonschema

SUITE = Path("/tmp/jsts/tests/draft2020-12")
OUT = REPO / "outputs" / "full_architecture_v1" / "probes"
SUPPORTED = {"type", "properties", "required", "additionalProperties",
             "items", "enum"}


def _schema_supported(schema, top: bool = True) -> bool:
    if isinstance(schema, bool):
        return False
    if not isinstance(schema, dict):
        return False
    keys = set(schema) - ({"$schema"} if top else set())
    if not keys <= SUPPORTED:
        return False
    kind = schema.get("type")
    if kind == "object":
        for child in schema.get("properties", {}).values():
            if not _schema_supported(child, top=False):
                return False
    if kind == "array":
        if not _schema_supported(schema.get("items", {}), top=False):
            return False
    return True


def _strip_declarative(schema):
    """Remove the declarative-only "$schema" key (never emitted by the
    competition declaration grammar; documented strip for suite testing)."""
    if not isinstance(schema, dict):
        return schema
    out = {k: v for k, v in schema.items() if k != "$schema"}
    return out


def main() -> None:
    groups = sorted(SUITE.glob("*.json"))
    stats = {"groups": 0, "tests": 0, "parity_failures": 0,
             "agreement": {"agree": 0, "abstain": 0, "disagree": 0},
             "fail_examples": []}
    for group in groups:
        data = json.loads(group.read_text(encoding="utf-8"))
        group_used = False
        for case in data:
            raw = case.get("schema")
            schema = _strip_declarative(raw)
            if not _schema_supported(schema):
                continue
            for test in case.get("tests", []):
                value = test.get("data")
                try:
                    cur = validate_declared_json(value, schema)
                except TypeError:
                    # incumbent crash on standard type-arrays
                    # ("type": ["integer","string"]); never emitted by the
                    # competition declaration grammar.  Counted as
                    # incumbent-abstain and recorded as a robustness gap.
                    cur = (None, ("INCUMBENT_TYPE_ARRAY_CRASH",))
                    stats.setdefault("incumbent_type_array_crashes", 0)
                    stats["incumbent_type_array_crashes"] += 1
                new = validate_with_jsonschema(value, schema)
                stats["tests"] += 1
                group_used = True
                crashed = "INCUMBENT_TYPE_ARRAY_CRASH" in cur[1]
                if crashed:
                    # parity N/A for incumbent crashes; adapter abstains
                    # fail-closed (UNSUPPORTED_SCHEMA_TYPE) — recorded only
                    stats["agreement"]["abstain"] += 1
                    continue
                parity = (cur[0] == new[0]) and \
                    (sorted(cur[1]) == sorted(new[1]))
                if not parity:
                    stats["parity_failures"] += 1
                    if len(stats["fail_examples"]) < 20:
                        stats["fail_examples"].append(
                            {"group": group.name, "description": case.get("description"),
                             "test": test.get("description"),
                             "cur": [cur[0], list(cur[1])],
                             "new": [new[0], list(new[1])]})
                expected = bool(test.get("valid"))
                # N1 divergence: incumbent (and adapter) say 3.0 is not an
                # integer; the suite (Draft 6+) says it is.  Intentional.
                is_n1 = (schema.get("type") == "integer"
                         and isinstance(value, float)
                         and isinstance(value, float) and value.is_integer())
                for name, res in (("cur", cur), ("new", new)):
                    if res[0] is None:
                        if name == "new":
                            stats["agreement"]["abstain"] += 1
                    elif bool(res[0]) == expected:
                        if name == "new":
                            stats["agreement"]["agree"] += 1
                    else:
                        if name == "new":
                            if is_n1:
                                stats["agreement"].setdefault(
                                    "intentional_n1_divergence", 0)
                                stats["agreement"]["intentional_n1_divergence"] += 1
                            else:
                                stats["agreement"]["disagree"] += 1
                            if len(stats["fail_examples"]) < 20:
                                stats["fail_examples"].append(
                                    {"group": group.name, "disagreement": True,
                                     "test": test.get("description"),
                                     "expected": expected, "new": [res[0], list(res[1])]})
        if group_used:
            stats["groups"] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "jsonschema_official_suite.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "fail_examples"},
                     indent=1))
    print("fail examples:", len(stats["fail_examples"]))


if __name__ == "__main__":
    main()
