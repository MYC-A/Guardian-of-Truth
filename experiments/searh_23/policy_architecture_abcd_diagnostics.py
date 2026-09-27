"""Post-run diagnostics only; does not modify the frozen primary score.

Operator presence in an intermediate tree is a loose upper bound: it does not
prove that the operator governs the right action or even the right clause.
"""
from __future__ import annotations

import json
from collections import defaultdict

from policy_architecture_abcd_v1 import ROOT, all_quotes

BASE = ROOT / "outputs/searh_23/policy_architecture_abcd_v2"
GOLD = ROOT / "experiments/searh_23/policy_architecture_abcd_v2/gold.json"
OPERATORS = {"AND", "OR", "NOT", "EXCEPT", "EVEN_IF"}


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def directive_ops(directives: list[dict]) -> set[str]:
    result = {n["op"] for n in walk(directives) if n.get("op") in OPERATORS}
    return result | {d["exception_type"] for d in directives
                     if d.get("exception_type") in OPERATORS}


def main() -> None:
    primary = json.loads((BASE / "score.json").read_text(encoding="utf-8"))
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    rows = []
    totals = defaultdict(lambda: {"operator_tp": 0, "operator_fp": 0, "operator_fn": 0,
                                  "tree_leaf_span_hit": 0, "tree_leaf_span_total": 0,
                                  "api_tokens": 0})
    for row in primary["rows"]:
        arm, case_id = row["arm"], row["case_id"]
        result = json.loads((BASE / "results" / arm / (case_id + ".json")).read_text(encoding="utf-8"))
        required = directive_ops(gold[case_id])
        if arm in {"C_onionl", "D_nl2logic"}:
            nodes = list(walk(result["tree"]))
            observed = {n["op"] for n in nodes if n.get("op") in OPERATORS}
            leaf_quotes = {n.get("quote") for n in nodes if n.get("op") == "ATOM" and n.get("quote")}
            leaf_hit = len(leaf_quotes & set(all_quotes(gold[case_id])))
        else:
            observed = directive_ops(result["directives"])
            leaf_hit = None
        usage = 0
        for call in result["calls"]:
            raw = json.loads((BASE / call["path"]).read_text(encoding="utf-8"))
            usage += raw.get("usage", {}).get("total_tokens", 0)
        item = {"case_id": case_id, "arm": arm,
                "required_operators": sorted(required), "observed_operators": sorted(observed),
                "operator_tp": len(required & observed),
                "operator_fp": len(observed - required),
                "operator_fn": len(required - observed),
                "tree_leaf_span_hit": leaf_hit,
                "tree_leaf_span_total": len(set(all_quotes(gold[case_id]))) if leaf_hit is not None else None,
                "api_tokens": usage}
        rows.append(item)
        total = totals[arm]
        for key in ("operator_tp", "operator_fp", "operator_fn", "api_tokens"):
            total[key] += item[key]
        if leaf_hit is not None:
            total["tree_leaf_span_hit"] += leaf_hit
            total["tree_leaf_span_total"] += item["tree_leaf_span_total"]
    output = {"status": "posthoc_diagnostic_not_primary_score", "summary": dict(totals), "rows": rows}
    (BASE / "diagnostics.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
