"""Failure analysis digest: reads score.json (+ raw arm outputs) and produces
report-ready facts: relation confusions, extra-edge patterns, hybrid role
failure breakdown, rename deltas, LLM call costs (cache file counts)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_common import OUTPUTS_DIR, FROZEN_DIR, suffix_for


def load_score(which):
    name = {"original": "score.json", "renamed": "score_renamed.json",
            "mini": "score_mini.json", "mini_renamed": "score_mini_renamed.json"}.get(which)
    p = OUTPUTS_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def relation_confusions(which):
    out = {}
    gold_name = {"original": "gold.json", "renamed": "gold_renamed.json",
                 "mini": "gold_mini.json"}.get(which)
    gold = {g["case_id"]: g for g in json.loads((FROZEN_DIR / gold_name).read_text(encoding="utf-8"))}
    for arm in ("relation", "relation_strong"):
        d = OUTPUTS_DIR / (arm + suffix_for(which))
        if not d.is_dir():
            continue
        conf = {}
        for f in d.glob("*.json"):
            if f.name.startswith("_"):
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            for ans in data.get("answers", []):
                gold_rel = ans.get("gold_relation")
                pred = ans.get("predicted")
                kind = ans.get("kind")
                conf.setdefault((gold_rel, pred, kind), 0)
                conf[(gold_rel, pred, kind)] += 1
        out[arm] = {f"{g}>{p} [{k}]": n for (g, p, k), n in
                    sorted(conf.items(), key=lambda kv: -kv[1])}
    return out


def arm_costs():
    out = {}
    for d in OUTPUTS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        cache = d / "_cache"
        calls = len(list(cache.glob("*.json"))) if cache.is_dir() else 0
        usage = {}
        up = d / "_usage.json"
        if up.is_file():
            usage = json.loads(up.read_text(encoding="utf-8"))
        out[d.name] = {"cache_calls": calls,
                       "wall_seconds": usage.get("wall_seconds"),
                       "usage": usage.get("usage") or usage.get("resolver_usage"),
                       "model": usage.get("model")}
    return out


def extra_edge_examples(which, arm="A_e2e", limit=12):
    gold_name = {"original": "gold.json", "renamed": "gold_renamed.json",
                 "mini": "gold_mini.json"}.get(which)
    gold = {g["case_id"]: g for g in json.loads((FROZEN_DIR / gold_name).read_text(encoding="utf-8"))}
    d = OUTPUTS_DIR / (arm + suffix_for(which))
    out = []
    if not d.is_dir():
        return out
    sys.path.insert(0, str(Path(__file__).parent))
    from oc_score import spans_equivalent
    from oc_common import load_suite
    suite = {c["case_id"]: c for c in load_suite(which)}
    for f in sorted(d.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        cid = data["case_id"]
        g = gold.get(cid)
        case = suite.get(cid)
        if not g or not case:
            continue
        used = set()
        for pe in data.get("edges", []):
            matched = False
            for k, ge in enumerate(g["condition_edges"]):
                if k in used:
                    continue
                cond_ok = spans_equivalent(case["policy"], pe.get("condition_span", ""),
                                           ge["condition_span"]) or \
                    ("ref_span" in ge and spans_equivalent(
                        case["policy"], pe.get("condition_span", ""), ge["ref_span"]))
                op_ok = spans_equivalent(case["policy"], pe.get("operation_span", ""),
                                         ge["operation_span"]) or \
                    ("ref_span" in ge and spans_equivalent(
                        case["policy"], pe.get("operation_span", ""), ge["ref_span"]))
                if cond_ok and op_ok:
                    matched = True
                    used.add(k)
                    break
            if not matched:
                out.append({"case": cid, "condition": pe.get("condition_span"),
                            "operation": pe.get("operation_span"),
                            "relation": pe.get("relation")})
    return out[:limit]


def hybrid_role_breakdown(which):
    """Which resolver labels did H's NLI logic assign to gold events?"""
    gold_name = {"original": "gold.json", "mini": "gold_mini.json"}.get(which)
    d = OUTPUTS_DIR / ("H_hybrid" + suffix_for(which))
    if not d.is_dir() or not gold_name:
        return {}
    gold = {g["case_id"]: g for g in json.loads((FROZEN_DIR / gold_name).read_text(encoding="utf-8"))}
    from oc_score import match_events
    from oc_common import load_suite
    suite = load_suite(which)
    pairs = {}
    for case in suite:
        a = d / f"{case['case_id']}.json"
        if not a.is_file():
            continue
        data = json.loads(a.read_text(encoding="utf-8"))
        g = gold.get(case["case_id"])
        if not g:
            continue
        matches, _, _ = match_events(case["policy"], data.get("events", []),
                                     g["candidate_events"])
        for i, j, _m in matches:
            gev = g["candidate_events"][j]
            pev = data["events"][i]
            key = (gev["role"], pev.get("role"))
            pairs.setdefault(key, 0)
            pairs[key] += 1
    return {f"gold={g} pred={p}": n for (g, p), n in sorted(pairs.items(), key=lambda kv: -kv[1])}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "original"
    score = load_score(which)
    digest = {"suite": which}
    if score:
        arms = score.get("arms", {})
        table = {}
        for arm, block in arms.items():
            ed = block.get("event_discovery")
            row = {}
            if ed:
                row["matched"] = f"{ed['matched']}/{ed['gold_events']}"
                row["role_correct"] = ed["matched_role_correct"]
                row["check_promoted"] = ed["check_promoted"]
                pr = ed.get("pr", {})
                row["op_recall"] = pr.get("OPERATION_EFFECT", {}).get("recall_role")
                row["check_recall"] = pr.get("PRECONDITION_CHECK", {}).get("recall_role")
            eg = block.get("edges")
            if isinstance(eg, dict) and eg.get("gold_edges"):
                row["edges"] = f"{eg['correct']}/{eg['gold_edges']}"
                row["extra"] = eg["extra"]
            if "pairs" in block:
                row["pair_acc"] = block["pairs"].get("accuracy")
            if "relation_only" in block:
                r = block["relation_only"]
                row["rel_gold"] = r.get("gold_accuracy")
                row["rel_neg"] = r.get("negative_accuracy")
            gc = block.get("grounding_components", {}).get("ranking", {})
            for k in ("E_embed", "F_cross", "G_nli"):
                if k in gc:
                    row[f"{k}_top1"] = f"{gc[k]['top1']}/{gc[k]['pairs']}"
                    row[f"{k}_top3"] = f"{gc[k]['top3']}/{gc[k]['pairs']}"
                    row[f"{k}_check2mut"] = f"{gc[k]['check_to_mutate']}/{gc[k]['check_events']}"
            table[arm] = row
        digest["arm_table"] = table
    digest["relation_confusions"] = relation_confusions(which)
    digest["hybrid_role_pairs"] = hybrid_role_breakdown(which)
    digest["extra_edges_A"] = extra_edge_examples(which)
    digest["costs"] = arm_costs()
    out = OUTPUTS_DIR / f"analysis_{which}.json"
    out.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out)
    print(json.dumps(digest.get("arm_table", {}), indent=1)[:2600])


if __name__ == "__main__":
    main()
