"""E2E-agent-1 causal-repair dev diagnostic (DEVELOPMENT phase only).

Replays the sealed E2E V1 semantic outputs through analyze_e2e_v1 (arm E0)
deterministically — zero LLM calls — and classifies every UNRESOLVED case by
the repair channel that could release it:

  scoped      an axis-attributable FALSE safety conjunct exists in every
              world (a certified independent violation) but claim/global
              markers currently force UNRESOLVED  -> A1 scoped UNKNOWN
  anchoring   a typed STATE/RESULT_FIELD/ATTRIBUTION claim whose object is a
              single literal token, currently reduced to boolean true and
              therefore unprovable                      -> A2 value anchoring
  binding     a policy/goal atom appears in binding.unbound_units or a
              lowering failure references an unbound atom     -> A3 catalog
              identity binding

Usage: PYTHONPATH=src python scripts/e2e_repair_diagnose.py [--arm E0]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from guardian_truth.vnext.types import CoreStatus, Truth  # noqa: E402
from guardian_truth.vnext.e2e import fresh_corpus_v1  # noqa: E402
from guardian_truth.vnext.e2e.core_v1 import analyze_e2e_v1  # noqa: E402
from scripts.evaluate_vnext_e2e_v1 import _rehydrate  # noqa: E402

OUT = ROOT / "outputs" / "vnext"


def conjunct_axis(obligation) -> str | None:
    """Axis attribution of one obligation (policy:/goal:/claim-id prefixes)."""
    if obligation.hypothesis_id == "GUARDIAN_FACTUAL_CONSISTENCY_V1":
        return obligation.claim_id
    if obligation.hypothesis_id.startswith("policy:"):
        return "policy"
    if obligation.hypothesis_id.startswith("goal:"):
        return "goal"
    return None


def axis_completeness(problem) -> dict[str, bool]:
    return {axis.name: bool(axis.enumeration_complete) for axis in problem.axes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="E0")
    args = parser.parse_args()

    cases = fresh_corpus_v1.build_fresh_corpus()
    sealed = {row["case_id"]: row["status"] for row in
              json.loads((OUT / f"e2e_v1_{args.arm}_predictions.json").read_text())["rows"]}

    tally = {"match": 0, "mismatch": []}
    unresolved_diag = []
    for item in cases:
        record = json.loads((OUT / "e2e_v1_semantic_outputs" / f"{item.case_id}.json").read_text())
        semantic = _rehydrate(item, record)
        output = analyze_e2e_v1(item.sources, semantic, args.arm, max_worlds=4096)
        status = output.result.status.value
        if status == sealed[item.case_id]:
            tally["match"] += 1
        else:
            tally["mismatch"].append((item.case_id, sealed[item.case_id], status))

        if status != "UNRESOLVED":
            continue
        completeness = axis_completeness(output.problem)
        # per-world: does ANY safety conjunct evaluate FALSE, and is it
        # attributable to a complete axis?
        world_info = []
        for world, proof in zip(output.problem.worlds, output.result.world_proofs):
            false_conjuncts = [oid for oid, value in proof.obligation_safety
                               if value is Truth.FALSE]
            certifiable = [oid for oid in false_conjuncts
                           if conjunct_axis(next(o for o in world.obligations
                                                 if o.obligation_id == oid)) is not None
                           and completeness.get(conjunct_axis(next(o for o in world.obligations
                                                                   if o.obligation_id == oid)), False)]
            world_info.append({
                "world": world.world_id,
                "markers": [r.value for r in world.unresolved_reasons],
                "false_conjuncts": false_conjuncts,
                "certifiable_false": certifiable,
                "safety": [(oid, value.value) for oid, value in proof.obligation_safety],
            })
        scoped_release = all(w["certifiable_false"] for w in world_info) and world_info
        # claim anchoring potential: typed claims with literal single-token objects
        anchor_candidates = []
        response = None
        from guardian_truth.vnext.e2e.source_adapter_v1 import render_response
        response = render_response(item.sources)
        for claim in semantic.claim_graph.claims:
            if claim.kind is None or claim.object is None:
                continue
            if claim.kind.value in {"STATE", "RESULT_FIELD", "ATTRIBUTION"} \
                    and claim.polarity == "POSITIVE" and claim.object.strip() \
                    and " " not in claim.object.strip():
                span_text = response[claim.span.start:claim.span.end]
                anchor_candidates.append({"claim": claim.claim_id, "kind": claim.kind.value,
                                          "predicate": claim.predicate, "object": claim.object,
                                          "in_span": claim.object in span_text})
        unbound_atoms = list(semantic.binding.unbound_units)
        unresolved_diag.append({
            "case_id": item.case_id,
            "cohort": item.cohort,
            "gold": item.gold.status.value,
            "scoped_release": bool(scoped_release),
            "axes_complete": completeness,
            "worlds": world_info,
            "anchor_candidates": anchor_candidates,
            "unbound_atoms": unbound_atoms,
        })

    print(json.dumps({"replay_vs_sealed": tally}, ensure_ascii=False))
    scoped = [d for d in unresolved_diag if d["scoped_release"]]
    print(f"\nUNRESOLVED cases: {len(unresolved_diag)}; scoped-release (A1): {len(scoped)}")
    for diag in scoped:
        print(f"  A1-RELEASABLE {diag['case_id']:38s} gold={diag['gold']:16s} "
              f"axes={diag['axes_complete']}")
    anchoring = [d for d in unresolved_diag if d["anchor_candidates"] and not d["scoped_release"]]
    print(f"\nA2 anchor-candidate UNRESOLVED (not A1-releasable): {len(anchoring)}")
    binding = [d for d in unresolved_diag if d["unbound_atoms"] and not d["scoped_release"]]
    print(f"A3 unbound-atom UNRESOLVED (not A1-releasable): {len(binding)}")
    for diag in binding[:15]:
        print(f"  {diag['case_id']:38s} unbound={diag['unbound_atoms'][:6]}")
    with open(OUT / "e2e_repair_diagnosis.json", "w", encoding="utf-8") as handle:
        json.dump(unresolved_diag, handle, ensure_ascii=False, indent=1)
    print("\nfull diagnosis -> outputs/vnext/e2e_repair_diagnosis.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
