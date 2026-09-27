"""Staged source-policy interpretation probe; never makes a global SAFE claim.

The model chooses action scope, then enumerates source conditions, then binds
each condition to declared Boolean evidence. Code validates exact source spans,
the declared catalog, an explicit-AND coverage gate, and unsupported syntax.
This is a diagnostic comparison with the earlier one-shot atom extractor.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from build_policy_atoms_v1 import BASE as ATOM_BASE, ROOT
from policy_model_ab_v1 import sha
from source_scope_probe_v2 import bullets, read_source
from tq_questions import Mistral


BASE = ROOT / "experiments/searh_23/staged_policy_tree_v1"
OUT = ROOT / "outputs/searh_23/staged_policy_tree_v1"
NAMES = ("warehouse_dev", "records_dev", "finance_holdout",
         "credentials_holdout", "booking_followup", "exception_holdout",
         "numeric_followup")

SCOPE_SYSTEM = """Read ONE original policy clause and the declared tool catalog.
Choose the action that the clause restricts, separating it from a lookup,
request, or earlier prerequisite action. Return one JSON object only:
{"kind":"PRECONDITION|ORDERING|UNSUPPORTED","governed_tool":"exact declared name or empty","prerequisite_tool":"exact declared name for ORDERING, otherwise empty","action_quote":"exact continuous substring of the policy naming the restricted action, or empty for UNSUPPORTED"}.
For ORDERING(A before B), B is the restricted current action and A is the
prerequisite. Do not evaluate any trace. Copy rather than paraphrase the quote.
"""

INVENTORY_SYSTEM = """Read ONE original PRECONDITION policy clause. List EVERY
independently necessary prerequisite for the governed action. Return one JSON
object only: {"condition_quotes":["exact continuous substring of the policy",...]}.
Use a separate, minimal source phrase for each prerequisite, including each
side of an explicit AND. Do not include the governed action, explanatory
request-versus-execution sentence, or whole clause in a condition quote.
Do not infer tools, fields, temporal operators, or a verdict yet.
"""

BIND_SYSTEM = """Read ONE cited prerequisite from the original clause and the
declared typed tool catalog. Bind this condition to a prior result. Return one
JSON object only:
{"evidence_tool":"exact declared name","join_key":"exact target argument and evidence ID field","result_field":"exact Boolean field in evidence result","required_value":true,"temporal":"LATEST|PRIOR_TRUE"}.
LATEST requires the newest same-ID observation to have the required value.
PRIOR_TRUE means a prior same-ID observation with the required value suffices.
Use LATEST only when the cited requirement asks for newest/current/latest
state; a check that 'has returned' or 'was verified' is a prior witness unless
the policy explicitly says it can be superseded. If the clause or catalog does
not support this Boolean form, use an empty object. No case verdict.
"""

EXCEPTION = re.compile(r"\b(?:unless|except|other than|waived|notwithstanding)\b", re.I)
NUMERIC = re.compile(r"\b(?:does not exceed|at most|no more than|less than|greater than|numeric\s+.*?limit)\b", re.I)
EXPLICIT_AND = re.compile(r"\bAND\b")


def unsupported_reason(policy: str) -> str | None:
    """Pre-model grammar gate, intentionally incomplete outside these controls."""
    if EXCEPTION.search(policy):
        return "exception_not_in_boolean_conjunction_grammar"
    if NUMERIC.search(policy):
        return "numeric_comparison_not_in_boolean_conjunction_grammar"
    return None


def unique_span(policy: str, quote: object) -> dict | None:
    if not isinstance(quote, str) or not quote:
        return None
    start = policy.find(quote)
    if start < 0 or start != policy.rfind(quote):
        return None
    return {"start": start, "end": start + len(quote)}


def inventory_spans(policy: str, quotes: object) -> list[dict] | None:
    if not isinstance(quotes, list) or not quotes or len(set(map(str, quotes))) != len(quotes):
        return None
    spans = [unique_span(policy, quote) for quote in quotes]
    if any(span is None or span["start"] == 0 and span["end"] == len(policy) for span in spans):
        return None
    # The supported grammar has an explicit uppercase AND between independent
    # prerequisites. Every resulting source segment needs a distinct condition.
    markers = list(EXPLICIT_AND.finditer(policy))
    if markers:
        sections = list(zip([0] + [m.end() for m in markers],
                            [m.start() for m in markers] + [len(policy)]))
        ownership = []
        for span in spans:
            matches = [index for index, (left, right) in enumerate(sections)
                       if left <= span["start"] and span["end"] <= right]
            if len(matches) != 1:
                return None
            ownership.append(matches[0])
        if len(spans) != len(sections) or set(ownership) != set(range(len(sections))):
            return None
    return spans


def valid_binding(answer: object, tools: dict, target_argument_keys: list[str]) -> bool:
    if not isinstance(answer, dict) or set(answer) != {"evidence_tool", "join_key",
                                                   "result_field", "required_value", "temporal"}:
        return False
    tool = answer["evidence_tool"]
    return (isinstance(tool, str) and tool in tools
            and answer["join_key"] in target_argument_keys
            and answer["join_key"] == tools[tool].get("id")
            and answer["result_field"] == tools[tool].get("result")
            and tools[tool].get("result_type", "boolean") == "boolean"
            and type(answer["required_value"]) is bool
            and answer["temporal"] in {"LATEST", "PRIOR_TRUE"})


def freeze() -> None:
    tasks = []
    for name in NAMES:
        data = json.loads((ATOM_BASE / (name + ".json")).read_text(encoding="utf-8"))
        tasks.append({"id": name, "split": data["split"],
                      "query": {"policy": data["policy"], "tools": data["tools"],
                                "target_argument_keys": sorted(data["ids"])},
                      "expected": {"kind": "UNSUPPORTED" if data["expected_unsupported"] else "PRECONDITION",
                                   "governed_tool": data["target"],
                                   "atoms": data["gold_atoms"]}})
    hotel = read_source("hotel_v2_calls")
    clause = bullets(hotel["policy"])[6]
    tasks.append({"id": "hotel_cancellation_order", "split": "viewed_hotel",
                  "query": {"policy": clause,
                            "tools": {name: {"description": desc.splitlines()[0]}
                                      for name, desc in hotel["tools"].items()},
                            "target_argument_keys": []},
                  "expected": {"kind": "ORDERING", "governed_tool": "process_refund",
                               "prerequisite_tool": "cancel_reservation", "atoms": []}})
    protocol = {"systems": {"scope": SCOPE_SYSTEM, "inventory": INVENTORY_SYSTEM,
                            "binding": BIND_SYSTEM}, "tasks": tasks, "max_tokens": 350,
                "note": "viewed authored fixtures; component mechanism, no binary benchmark"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen protocol changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


def _ask(model: Mistral, protocol: dict, task: dict, stage: str, query: dict,
         suffix: str) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (task["id"] + suffix + ".json")
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if (old["protocol_sha256"] != sha(protocol) or
                old["query_sha256"] != sha(query) or old["requested_model"] != model.model):
            raise ValueError("existing response uses another source, prompt or model")
        return old
    try:
        answer = model.ask(protocol["systems"][stage], json.dumps(query, ensure_ascii=False),
                           max_tokens=protocol["max_tokens"])
    except ValueError as exc:
        if str(exc) != "model returned non-object JSON":
            raise
        answer = {"value": {}, "finish_reason": "non_object_json", "usage": {}}
    record = {"id": task["id"], "stage": stage, "protocol_sha256": sha(protocol),
              "query_sha256": sha(query), "requested_model": model.model,
              "answer": answer["value"], "finish_reason": answer["finish_reason"],
              "usage": answer["usage"]}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": task["id"], "stage": stage,
                      "finish_reason": record["finish_reason"]}), flush=True)
    return record


def run() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    model = Mistral()
    for task in protocol["tasks"]:
        query = task["query"]
        policy = query["policy"]
        if unsupported_reason(policy):
            print(json.dumps({"id": task["id"], "stage": "preflight_unsupported"}), flush=True)
            continue
        scope = _ask(model, protocol, task, "scope",
                     {"policy": policy, "tools": query["tools"]}, "__scope")
        # Routing must depend on the model response, never on frozen gold.
        if scope["answer"].get("kind") != "PRECONDITION":
            continue
        inventory = _ask(model, protocol, task, "inventory",
                         {"policy": policy, "governed_tool": scope["answer"].get("governed_tool", "")},
                         "__inventory")
        quotes = inventory["answer"].get("condition_quotes")
        if inventory_spans(policy, quotes) is None:
            continue
        for index, quote in enumerate(quotes):
            _ask(model, protocol, task, "binding",
                 {"policy": policy, "condition_quote": quote,
                  "governed_tool": scope["answer"].get("governed_tool", ""),
                  "tools": query["tools"],
                  "target_argument_keys": query["target_argument_keys"]},
                 f"__bind_{index}")


def _read(task: dict, protocol: dict, stage: str, query: dict, suffix: str) -> dict | None:
    path = OUT / (task["id"] + suffix + ".json")
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if (record["protocol_sha256"] != sha(protocol) or record["query_sha256"] != sha(query)
            or record["stage"] != stage):
        raise ValueError("source or prompt mismatch")
    return record


def score() -> dict:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    rows = []
    for task in protocol["tasks"]:
        query, gold = task["query"], task["expected"]
        policy = query["policy"]
        reason = unsupported_reason(policy)
        if reason:
            rows.append({"id": task["id"], "split": task["split"], "stage": "preflight",
                         "valid": True, "exact": gold["kind"] == "UNSUPPORTED",
                         "reason": reason, "tree": None, "global_verdict": "UNKNOWN"})
            continue
        scope_query = {"policy": policy, "tools": query["tools"]}
        scope_record = _read(task, protocol, "scope", scope_query, "__scope")
        if scope_record is None:
            raise ValueError("missing scope response: " + task["id"])
        scope = scope_record["answer"]
        kind, governed, prerequisite = (scope.get(k) for k in ("kind", "governed_tool", "prerequisite_tool"))
        action_span = unique_span(policy, scope.get("action_quote"))
        scope_valid = (scope_record["finish_reason"] == "stop" and
                       kind in {"PRECONDITION", "ORDERING", "UNSUPPORTED"} and
                       isinstance(governed, str) and governed in query["tools"] and
                       isinstance(prerequisite, str) and action_span is not None and
                       (prerequisite in query["tools"] if kind == "ORDERING" else prerequisite == ""))
        if kind != "PRECONDITION" or gold["kind"] == "ORDERING":
            exact = (scope_valid and kind == "ORDERING" and
                     governed == gold["governed_tool"] and
                     prerequisite == gold.get("prerequisite_tool"))
            tree = ({"type": "ORDERING", "before_tool": prerequisite,
                     "after_tool": governed, "action_span": action_span}
                    if scope_valid else None)
            rows.append({"id": task["id"], "split": task["split"], "stage": "scope",
                         "valid": scope_valid, "exact": exact, "tree": tree,
                         "global_verdict": "UNKNOWN"})
            continue
        inventory_query = {"policy": policy, "governed_tool": governed or ""}
        inventory_record = _read(task, protocol, "inventory", inventory_query, "__inventory")
        if inventory_record is None:
            raise ValueError("missing inventory response: " + task["id"])
        quotes = inventory_record["answer"].get("condition_quotes")
        spans = inventory_spans(policy, quotes)
        inventory_valid = inventory_record["finish_reason"] == "stop" and spans is not None
        bindings = []
        if inventory_valid:
            for index, quote in enumerate(quotes):
                bind_query = {"policy": policy, "condition_quote": quote,
                              "governed_tool": governed or "", "tools": query["tools"],
                              "target_argument_keys": query["target_argument_keys"]}
                record = _read(task, protocol, "binding", bind_query, f"__bind_{index}")
                if record is None:
                    raise ValueError("missing binding response: " + task["id"])
                answer = record["answer"]
                bindings.append({"source_span": spans[index], "source_quote": quote,
                                 "answer": answer,
                                 "valid": (record["finish_reason"] == "stop" and
                                           valid_binding(answer, query["tools"],
                                                         query["target_argument_keys"]))})
        actual = sorted(tuple(binding["answer"].get(key) for key in
                              ("evidence_tool", "join_key", "result_field", "required_value", "temporal"))
                        for binding in bindings if binding["valid"])
        expected = sorted(tuple(atom[key] for key in
                                ("evidence_tool", "join_key", "result_field", "required_value", "temporal"))
                          for atom in gold["atoms"])
        exact = (scope_valid and kind == "PRECONDITION" and
                 governed == gold["governed_tool"] and inventory_valid and
                 len(bindings) == len(gold["atoms"]) and
                 all(binding["valid"] for binding in bindings) and actual == expected)
        tree = ({"type": "BEFORE_ACTION", "governed_tool": governed,
                 "action_span": action_span,
                 "condition": {"type": "AND", "children": bindings}}
                if scope_valid and inventory_valid else None)
        rows.append({"id": task["id"], "split": task["split"],
                     "stage": "binding" if inventory_valid else "inventory",
                     "valid": bool(scope_valid and inventory_valid and
                                   all(binding["valid"] for binding in bindings)),
                     "exact": bool(exact), "scope_exact": bool(scope_valid and kind == gold["kind"] and
                                                                governed == gold["governed_tool"]),
                     "inventory_valid": bool(inventory_valid),
                     "expected_atoms": expected, "actual_atoms": actual,
                     "tree": tree, "global_verdict": "UNKNOWN"})
    result = {"protocol_sha256": sha(protocol), "requested_model": next(
              (json.loads(path.read_text(encoding="utf-8"))["requested_model"]
               for path in sorted(OUT.glob("*__scope.json"))), None),
              "rows": rows, "exact": sum(row["exact"] for row in rows),
              "total": len(rows)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    return {k: v for k, v in result.items() if k != "rows"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    elif args.phase == "run":
        run()
    else:
        print(json.dumps(score()))
