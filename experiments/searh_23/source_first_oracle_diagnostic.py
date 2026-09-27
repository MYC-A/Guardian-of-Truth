"""Post-hoc diagnostic: unchanged frozen E_detail prompt with gold action anchors.

This is NOT a competitive arm; gold supplies the action spans. It isolates
condition attachment and typing after correct action discovery.
"""
from __future__ import annotations

import json

import policy_architecture_abcd_v1 as old
import source_first_compare as cmp
import source_first_score as scorer

OUT = cmp.OUT / "oracle_action_diagnostic"


def gold_anchor(policy: str, quote: str) -> dict:
    a = policy.index(quote)
    b = a + len(quote)
    toks = cmp.tokens(policy)
    start = next(i for i, t in enumerate(toks) if t["start"] == a)
    end = next(i + 1 for i, t in enumerate(toks) if t["end"] == b)
    return cmp.source_span(policy, toks, {"start": start, "end": end})


def run() -> None:
    protocol = json.loads((cmp.BASE / "frozen.json").read_text(encoding="utf-8"))
    gold = json.loads((cmp.BASE / "gold.json").read_text(encoding="utf-8"))
    model = old.MistralRaw()
    old.OUT = cmp.OUT
    rows = []
    for case in protocol["cases"]:
        policy = case["query"]["policy"]
        indexed = [{"i": t["i"], "text": t["text"]} for t in cmp.tokens(policy)]
        for gi, g in enumerate(gold[case["id"]]):
            oracle_case = {"id": f"{case['id']}__{gi}", "query": case["query"]}
            rec = cmp.recorder(protocol, model, "E_oracle_detail", oracle_case)
            anchor = gold_anchor(policy, g["action_quote"])
            answer = rec.ask("E_detail", {"policy": policy, "indexed_tokens": indexed,
                                           "tools": case["query"]["tools"], "action": anchor})
            conds = []
            for c in answer.get("conditions", []):
                sp = cmp.source_span(policy, cmp.tokens(policy), c.get("span")) if isinstance(c, dict) else None
                if sp:
                    conds.append({"quote": sp["exact_source_text"], "temporal": c.get("temporal")})
            expected = scorer.atoms(g.get("condition"))
            used = set(); hits = 0; temporal_hits = 0
            for ec in expected:
                options = [(j, pc) for j, pc in enumerate(conds) if j not in used and
                           scorer.matched(policy, ec["quote"], pc["quote"])]
                if options:
                    j, pc = max(options, key=lambda x: scorer.similarity(policy, ec["quote"], x[1]["quote"]))
                    used.add(j); hits += 1; temporal_hits += pc["temporal"] == ec["temporal"]
            rows.append({"case": case["id"], "gold_index": gi, "gold_action": g["action_quote"],
                         "oracle_anchor": anchor, "gold_kind": g["kind"], "pred_kind": answer.get("kind"),
                         "gold_tools": g["governed_tools"], "pred_tools": answer.get("governed_tools"),
                         "gold_conditions": expected, "pred_conditions": conds,
                         "gold_condition_op": scorer.shape(g.get("condition")),
                         "pred_condition_op": answer.get("condition_op"),
                         "binding_hits": hits, "binding_missing": len(expected) - hits,
                         "binding_extra": len(conds) - len(used), "temporal_hits": temporal_hits,
                         "gold_before": g.get("before_quote", ""),
                         "pred_before": (cmp.source_span(policy, cmp.tokens(policy), answer.get("before")) or {}).get("exact_source_text", ""),
                         "gold_exception": g.get("exception_quote", ""),
                         "pred_exception": (cmp.source_span(policy, cmp.tokens(policy), answer.get("exception")) or {}).get("exact_source_text", ""),
                         "calls": rec.calls})
            print(json.dumps({"case": case["id"], "gold_index": gi, "binding_hits": hits,
                              "binding_missing": len(expected) - hits}), flush=True)
    aggregate = {"gold_actions": len(rows), "gold_condition_edges": sum(len(r["gold_conditions"]) for r in rows),
                 "binding_hits": sum(r["binding_hits"] for r in rows),
                 "binding_extra": sum(r["binding_extra"] for r in rows),
                 "kind_correct": sum(r["gold_kind"] == r["pred_kind"] for r in rows),
                 "tool_set_correct": sum(set(r["gold_tools"]) == set(r["pred_tools"] or []) for r in rows),
                 "condition_op_correct": sum(r["gold_condition_op"] == r["pred_condition_op"] for r in rows),
                 "temporal_hits": sum(r["temporal_hits"] for r in rows)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps({"aggregate": aggregate, "per_case": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(aggregate), flush=True)


if __name__ == "__main__":
    run()
