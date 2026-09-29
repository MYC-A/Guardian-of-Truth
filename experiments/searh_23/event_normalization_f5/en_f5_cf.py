"""EN-6b: CF twin minimal-pair flip checks (directive §13).

For each of the 5 frozen CF twins (sides a/b, expected 4-way labels):
  systems checked on the FOCUS pair of each side:
    - v10_nodes   : are the two focus spans members of the SAME predicted
                    node? (node-level identity decision)
    - v11_nodes   : same, v11 build
    - H_v10       : compatible_nodes pair decision (deterministic)
    - D_all       : UD-signature IR decision (deterministic)
    - F4way       : narrow LLM 4-way judge (policy-only)

Metrics per system: per-side prediction vs expected; both_correct (both
sides match the expected 4-way label); binary_flip (SAME vs non-SAME
follows the expected binary pattern); confusion.

Node builds come from the round driver's `nodes cf` outputs (outputs/
nodes_cf/v10.json / v11.json). The v10/v11 node builds there use the
frozen build functions on the CF frontend chain.

Run (server): /workspace/guardian/venv/bin/python en_f5_cf.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
W1 = HERE.parent / "step1_working_v1"
sys.path[:0] = [str(W1), str(HERE)]

from en_identity import (arm_h, arm_d_subset, ir_features,  # noqa: E402
                          pair_metrics, LABELS)
import en_identity_llm as idl  # noqa: E402
from pl_common import Mistral  # noqa: E402

OUTD = HERE / "outputs" / "cf"
OUTD.mkdir(parents=True, exist_ok=True)


def twins() -> list[dict]:
    return json.loads((HERE / "f5_frozen" / "f5_cf_twins.json")
                      .read_text(encoding="utf-8"))["twins"]


def cf_bench() -> list[dict]:
    bench = []
    for t in twins():
        for side in ("a", "b"):
            s = t[side]
            policy = s["policy"]
            fa, fb = s["focus"]
            bench.append({"case": f"{t['twin_id']}_{side}",
                          "twin": t["twin_id"], "side": side,
                          "policy": policy,
                          "a_mid": fa, "b_mid": fb,
                          "a_span": fa, "b_span": fb,
                          "a_start": policy.find(fa),
                          "b_start": policy.find(fb),
                          "gold": s["expected"],
                          "mechanism": t["mechanism"]})
    return bench


def node_decision(nodes_file: Path, case_id: str) -> str:
    """SAME_EVENT iff both focus spans are member forms of one node."""
    if not nodes_file.exists():
        return "MISSING"
    nodes = json.loads(nodes_file.read_text(encoding="utf-8")).get(
        case_id, [])
    focus = [p for p in cf_bench() if p["case"] == case_id][0]
    f_a, f_b = focus["a_span"], focus["b_span"]
    for n in nodes:
        forms = set(n.get("member_spans") or [n.get("span", "")])
        if f_a in forms and f_b in forms:
            return "SAME_EVENT"
    return "DIFFERENT_EVENT"


def main() -> None:
    bench = cf_bench()
    out = {"per_pair": [], "systems": {}}

    # deterministic arms
    ph = dict(((p["case"], p["a_mid"], p["b_mid"]), d)
              for p, d in zip(bench, arm_h(bench)))
    import stanza
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)
    ir = ir_features(bench, nlp)
    pd_all = dict(((p["case"], p["a_mid"], p["b_mid"]), d)
                  for p, d in zip(
                      bench, arm_d_subset(
                          bench, ir, {"predicate", "entities", "arguments",
                                      "polarity", "modality", "event_mode",
                                      "temporal"})))

    # F4way LLM judge
    client = Mistral(model="ministral-14b-latest", cache_dir=OUTD / "_cache")
    f4 = idl.run_f4way(bench, client)
    f4_by = {(d["case"], d["a"], d["b"]): d["label"] for d in f4}

    # node-based decisions
    v10_nodes = HERE / "outputs" / "nodes_cf" / "v10.json"
    v11_nodes = HERE / "outputs" / "nodes_cf" / "v11.json"

    systems = {}
    for p in bench:
        key = (p["case"], p["a_mid"], p["b_mid"])
        row = {"case": p["case"], "twin": p["twin"], "side": p["side"],
               "mechanism": p["mechanism"], "gold": p["gold"],
               "H_v10": ph.get(key, {}).get("label", "MISSING"),
               "D_all": pd_all.get(key, {}).get("label", "MISSING"),
               "F4way": f4_by.get(key, "MISSING"),
               "v10_nodes": node_decision(v10_nodes, p["case"]),
               "v11_nodes": node_decision(v11_nodes, p["case"])}
        out["per_pair"].append(row)

    # per-system metrics
    def sys_metric(name):
        both = flip = 0
        per_twin = {}
        for t in twins():
            ta = next(r for r in out["per_pair"]
                      if r["twin"] == t["twin_id"] and r["side"] == "a")
            tb = next(r for r in out["per_pair"]
                      if r["twin"] == t["twin_id"] and r["side"] == "b")
            pa, pb = ta[name], tb[name]
            ea, eb = ta["gold"], tb["gold"]
            ok = (pa == ea and pb == eb)
            binflip = ((pa == "SAME_EVENT") != (pb == "SAME_EVENT")) == \
                ((ea == "SAME_EVENT") != (eb == "SAME_EVENT"))
            both += ok
            flip += binflip
            per_twin[t["twin_id"]] = {"a": pa, "b": pb,
                                      "expected_a": ea, "expected_b": eb,
                                      "both_correct": ok,
                                      "binary_flip_pattern": binflip}
        return {"both_sides_correct": both, "of": len(twins()),
                "binary_flip_correct": flip,
                "per_twin": per_twin}

    for name in ("H_v10", "D_all", "F4way", "v10_nodes", "v11_nodes"):
        systems[name] = sys_metric(name)
        print(f"[cf] {name}: both_correct={systems[name]['both_sides_correct']}"
              f"/{systems[name]['of']} "
              f"binary_flip={systems[name]['binary_flip_correct']}",
              flush=True)

    # pair metrics (4-way strictness collapsed: gold vs pred on all 10 sides)
    for name in ("H_v10", "D_all", "F4way", "v10_nodes", "v11_nodes"):
        preds = [{"label": r[name]} for r in out["per_pair"]]
        systems[name]["pair_metrics"] = pair_metrics(
            [dict(p) for p in bench], preds)

    out["systems"] = systems
    (OUTD / "f5_cf.json").write_text(json.dumps(out, indent=1))
    print("saved ->", OUTD / "f5_cf.json", flush=True)


if __name__ == "__main__":
    main()
