"""Gold scoring for the frozen source-first architecture probe; never imported by run."""
from __future__ import annotations

import json
from collections import Counter

import policy_architecture_abcd_v1 as old
import source_first_compare as cmp


def loc(policy: str, quote: str) -> tuple[int, int] | None:
    if not quote or policy.count(quote) != 1:
        return None
    a = policy.index(quote)
    return a, a + len(quote)


def similarity(policy: str, a: str, b: str) -> float:
    x, y = loc(policy, a), loc(policy, b)
    if not x or not y:
        return 0.0
    common = max(0, min(x[1], y[1]) - max(x[0], y[0]))
    union = max(x[1], y[1]) - min(x[0], y[0])
    return common / union if union else 0.0


def matched(policy: str, a: str, b: str) -> bool:
    return a == b or similarity(policy, a, b) >= 0.5


def atoms(cond: dict | None) -> list[dict]:
    if not cond:
        return []
    if cond.get("op") == "ATOM":
        return [cond]
    result = []
    for child in cond.get("children", []):
        result.extend(atoms(child))
    return result


def shape(cond: dict | None) -> str:
    if not cond:
        return "NONE"
    return cond.get("op", "UNKNOWN")


def pair(policy: str, gold: list[dict], pred: list[dict]) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    used = set()
    pairs = []
    for gi, g in enumerate(gold):
        candidates = [(pi, p) for pi, p in enumerate(pred)
                      if pi not in used and p.get("kind") == g["kind"] and
                      matched(policy, p.get("action_quote", ""), g["action_quote"])]
        if candidates:
            pi, _ = max(candidates, key=lambda x: similarity(policy, x[1]["action_quote"], g["action_quote"]))
            used.add(pi)
            pairs.append((gi, pi))
    return pairs, [i for i in range(len(gold)) if i not in {x[0] for x in pairs}], [i for i in range(len(pred)) if i not in used]


def score_case(case: dict, gold: list[dict], result: dict) -> dict:
    policy, pred = case["query"]["policy"], result["directives"]
    pairs, misses, extras = pair(policy, gold, pred)
    bind_tp = bind_fp = bind_fn = tool_correct = logic_correct = temporal_correct = relation_correct = 0
    condition_total = sum(len(atoms(g.get("condition"))) for g in gold)
    for gi, pi in pairs:
        g, p = gold[gi], pred[pi]
        tool_correct += set(g["governed_tools"]) == set(p.get("governed_tools", []))
        logic_correct += shape(g.get("condition")) == shape(p.get("condition"))
        relation_correct += (g["kind"] == p.get("kind") and g.get("exception_type") == p.get("exception_type") and
                             bool(g.get("before_quote")) == bool(p.get("before_quote")))
        ga, pa = atoms(g.get("condition")), atoms(p.get("condition"))
        used = set()
        for gc in ga:
            options = [(j, pc) for j, pc in enumerate(pa) if j not in used and
                       matched(policy, pc.get("quote", ""), gc["quote"])]
            if options:
                j, pc = max(options, key=lambda x: similarity(policy, x[1]["quote"], gc["quote"]))
                used.add(j); bind_tp += 1
                temporal_correct += pc.get("temporal") == gc.get("temporal")
            else:
                bind_fn += 1
        bind_fp += len(pa) - len(used)
    for gi in misses:
        bind_fn += len(atoms(gold[gi].get("condition")))
    for pi in extras:
        bind_fp += len(atoms(pred[pi].get("condition")))
    span_nodes = sum(1 for gi, pi in pairs if loc(policy, pred[pi].get("action_quote", ""))) + bind_tp
    total_nodes = len(gold) + condition_total
    exact = len(pred) == len(gold) and Counter(old.exact(d) for d in pred) == Counter(old.exact(d) for d in gold)
    verify = result.get("verification", {})
    checks = {x.get("id"): x for x in verify.get("checks", []) if isinstance(x, dict)}
    mutation_ids = [x["id"] for x in verify.get("candidates", []) if not x["id"].startswith("base_")]
    detected = sum(bool(checks.get(k)) and (not checks[k].get("valid") or checks[k].get("reason") == "UNCERTAIN") for k in mutation_ids)
    return {"case": case["id"], "arm": result["arm"], "gold_count": len(gold), "pred_count": len(pred),
            "directive_count_correct": len(pred) == len(gold), "action_matched": len(pairs),
            "matched_pairs": pairs, "missing_directives": [gold[i]["action_quote"] for i in misses],
            "extra_directives": [pred[i].get("action_quote", "") for i in extras],
            "tools_correct_on_matched": tool_correct, "relation_correct_on_matched": relation_correct,
            "logic_correct_on_matched": logic_correct,
            "binding_tp": bind_tp, "binding_fp": bind_fp, "binding_fn": bind_fn,
            "temporal_correct_on_bound": temporal_correct, "condition_total": condition_total,
            "source_span_recall_numerator": span_nodes, "source_span_recall_denominator": total_nodes,
            "exact_ir": exact, "unknown": result.get("unknown", False) or bool(result["errors"]),
            "errors": result["errors"], "mutation_count": len(mutation_ids),
            "mutations_rejected_or_unknown": detected,
            "mutation_checks": [{"id": k, "check": checks.get(k)} for k in mutation_ids]}


def score() -> dict:
    protocol = json.loads((cmp.BASE / "frozen.json").read_text(encoding="utf-8"))
    gold = json.loads((cmp.BASE / "gold.json").read_text(encoding="utf-8"))
    rows = []
    for case in protocol["cases"]:
        for arm in protocol["arms"]:
            path = cmp.OUT / "results" / arm / (case["id"] + ".json")
            result = json.loads(path.read_text(encoding="utf-8"))
            if result["protocol_sha256"] != old.digest(protocol) or result["query_sha256"] != old.digest(case["query"]):
                raise ValueError("result/protocol mismatch: " + str(path))
            rows.append(score_case(case, gold[case["id"]], result))
    aggregate = {}
    for arm in protocol["arms"]:
        group = [r for r in rows if r["arm"] == arm]
        fields = ("directive_count_correct", "action_matched", "tools_correct_on_matched", "relation_correct_on_matched",
                  "logic_correct_on_matched", "binding_tp", "binding_fp", "binding_fn", "temporal_correct_on_bound",
                  "source_span_recall_numerator", "source_span_recall_denominator", "exact_ir", "unknown",
                  "mutation_count", "mutations_rejected_or_unknown")
        aggregate[arm] = {k: sum(r[k] for r in group) for k in fields}
        aggregate[arm].update({"cases": len(group), "gold_directives": sum(r["gold_count"] for r in group),
                               "missing_directives": sum(len(r["missing_directives"]) for r in group),
                               "extra_directives": sum(len(r["extra_directives"]) for r in group),
                               "gold_condition_edges": sum(r["condition_total"] for r in group)})
    payload = {"protocol_sha256": old.digest(protocol), "gold_sha256": old.digest(gold),
               "aggregate": aggregate, "per_case": rows}
    cmp.OUT.mkdir(parents=True, exist_ok=True)
    (cmp.OUT / "score.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
