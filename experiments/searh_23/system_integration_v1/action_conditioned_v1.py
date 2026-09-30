"""Action-conditioned policy program proposal on frozen short policies.

This is a model proposal, NEVER a ReviewedProgram. Exact source quotes and
catalog IDs are syntax checks; they do not prove NL semantic entailment.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "operation_check"))

from oc_common import Mistral

FROZEN = HERE / "frozen" / "action_conditioned_v1"

SYSTEM = """You analyze ONE candidate tool action against the ORIGINAL policy.
The action and possible condition predicates are supplied from a structured
tool catalog. Do not invent other predicates. Return one JSON object with:
{
  "action_quote": "exact substring of policy identifying the governed action",
  "required": [{"predicate":"catalog predicate ID", "quote":"exact policy substring stating this requirement"}],
  "combine": "ALL|ANY|UNKNOWN",
  "exceptions": [{"when":"catalog predicate ID", "waives":"required predicate ID", "quote":"exact policy substring stating the exception"}],
  "activation": null OR {"field":"tool input field", "op":"GT", "value":NUMBER, "quote":"exact policy substring stating threshold"},
  "temporal": "LATEST_PRIOR|EVER_PRIOR|AFTER_ACTION|UNKNOWN"
}
Find ALL conditions that must hold for THIS tool action, including conditions
shared across a sentence and ones that exceptions do not waive. An exception
waives only the specified requirement. Distinguish a check tool from the
business action it checks. A descriptive sentence saying one action is not
another is not an extra prerequisite. Source quotes must be copied exactly.
LATEST_PRIOR means the latest applicable state before the action. EVER_PRIOR
requires explicit wording that any earlier occurrence suffices. Do not infer
permission or a requirement from a tool name alone. If uncertain use UNKNOWN
and leave uncertain items out; never guess a predicate."""


def _valid_quote(policy: str, quote: object) -> bool:
    return isinstance(quote, str) and bool(quote) and quote in policy


def validate(query: dict, raw: str) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {"valid": False, "issues": ["invalid_json"]}
    if not isinstance(value, dict):
        return {"valid": False, "issues": ["not_object"]}
    issues = []
    policy = query["policy"]
    menu = {x["predicate"] for x in query["condition_menu"]}
    if not _valid_quote(policy, value.get("action_quote")):
        issues.append("action_quote_not_source")
    required = value.get("required")
    if not isinstance(required, list):
        required = []
        issues.append("required_not_list")
    required_ids = []
    for index, item in enumerate(required):
        if not isinstance(item, dict) or item.get("predicate") not in menu:
            issues.append(f"required:{index}:predicate_unlicensed")
            continue
        if not _valid_quote(policy, item.get("quote")):
            issues.append(f"required:{index}:quote_not_source")
        required_ids.append(item["predicate"])
    if len(required_ids) != len(set(required_ids)):
        issues.append("required_duplicate")
    combine = value.get("combine")
    if combine not in {"ALL", "ANY", "UNKNOWN"}:
        issues.append("combine_invalid")
    exceptions = value.get("exceptions")
    if not isinstance(exceptions, list):
        exceptions = []
        issues.append("exceptions_not_list")
    exception_pairs = []
    for index, item in enumerate(exceptions):
        if (not isinstance(item, dict) or item.get("when") not in menu
                or item.get("waives") not in required_ids):
            issues.append(f"exception:{index}:predicate_unlicensed")
            continue
        if not _valid_quote(policy, item.get("quote")):
            issues.append(f"exception:{index}:quote_not_source")
        exception_pairs.append({"when": item["when"], "waives": item["waives"]})
    activation = value.get("activation")
    canonical_activation = None
    if activation is not None:
        if (not isinstance(activation, dict)
                or activation.get("field") not in query["governed_action"]["input_fields"]
                or activation.get("op") != "GT"
                or isinstance(activation.get("value"), bool)
                or not isinstance(activation.get("value"), (int, float))
                or not _valid_quote(policy, activation.get("quote"))):
            issues.append("activation_invalid")
        else:
            canonical_activation = {k: activation[k] for k in ("field", "op", "value")}
    temporal = value.get("temporal")
    if temporal not in {"LATEST_PRIOR", "EVER_PRIOR", "AFTER_ACTION", "UNKNOWN"}:
        issues.append("temporal_invalid")
    return {"valid": not issues, "issues": issues,
            "canonical": {"id": query["id"], "required": sorted(required_ids),
                          "combine": combine, "exceptions": sorted(
                              exception_pairs, key=lambda x: (x["when"], x["waives"])),
                          "activation": canonical_activation, "temporal": temporal},
            "source_quotes": {"action": value.get("action_quote"),
                              "required": [x.get("quote") for x in required
                                           if isinstance(x, dict)],
                              "exceptions": [x.get("quote") for x in exceptions
                                             if isinstance(x, dict)]}}


def run(split: str) -> dict:
    queries = json.loads((FROZEN / f"{split}_queries.json").read_text(encoding="utf-8"))
    client = Mistral(cache_dir=HERE / "outputs" / "action_conditioned_cache")
    predictions = []
    for query in queries:
        response = client.ask(SYSTEM, json.dumps(query, ensure_ascii=False),
                              max_tokens=1300)
        parsed = validate(query, response["raw"])
        predictions.append({"id": query["id"], "proposal": parsed,
                            "raw": response["raw"], "usage": response.get("usage", {}),
                            "finish_reason": response.get("finish_reason")})
    gold = {x["id"]: x for x in json.loads((FROZEN / f"{split}_gold.json").read_text(
        encoding="utf-8"))}
    counts = Counter()
    for pred in predictions:
        oracle = gold[pred["id"]]
        got = pred["proposal"]
        canonical = got.get("canonical") or {}
        fields = ("required", "combine", "exceptions", "activation", "temporal")
        field_matches = {field: canonical.get(field) == oracle[field] for field in fields}
        pred["gold"] = oracle
        pred["field_matches"] = field_matches
        pred["exact_program"] = got["valid"] and all(field_matches.values())
        counts.update({"total": 1, "valid_source_schema": int(got["valid"]),
                       "exact_program": int(pred["exact_program"]),
                       **{field + "_correct": int(match)
                          for field, match in field_matches.items()}})
    report = {"split": split, "track": "model_proposed_action_conditioned_policy",
              "model": client.model, "api_calls": client.calls,
              "usage": client.usage_total, "counts": dict(counts),
              "per_case": predictions}
    out = HERE / "outputs" / f"action_conditioned_{split}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_case"},
                     ensure_ascii=False))
    return report


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"dev", "sealed"}:
        raise SystemExit("usage: action_conditioned_v1.py dev|sealed")
    run(sys.argv[1])
