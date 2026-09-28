"""Step 2 evidence runner (research-only; never touches scripts/predict.py).

Subcommands:

  run          — run one or more arms over a split; writes predictions JSONL
                 (deterministic arms need no key; LLM arms use the Mistral env)
  score        — score a predictions file against sealed gold
  temporal     — evaluate temporal queries via the fact ledger
  rename-check — run an arm on originals vs opaque-renamed suite, diff verdicts
  cf-check     — counterfactual flip rate (one evidence source changed)
  claim-probe  — section 31 diagnostic: proposition vs ledger

All outputs are JSON; every prediction row carries its input case hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from guardian_truth.step2.arms import (ALL_ARMS, apply_read_confirmation,
                                       build_ledger, run_arm)
from guardian_truth.step2.ledger import FactLedger, Proposition
from guardian_truth.step2.metrics import aggregate, score_case
from guardian_truth.step2.proposer import MistralProposer
from guardian_truth.step2.types import EffectStrength, Truth
from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> list[dict]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return json.loads(path.read_text(encoding="utf-8"))


def to_trajectory(case: dict) -> TrajectoryCase:
    calls, results = [], []
    for ev in case.get("trajectory", []):
        payload = ev.get("payload")
        if ev["kind"] == "call":
            calls.append(CallEvent(index=ev["index"], call_id=ev["call_id"],
                                    tool=ev["tool"], payload=payload,
                                    actor=ev.get("actor", "assistant")))
        elif ev["kind"] == "result":
            results.append(ResultEvent(index=ev["index"], call_id=ev["call_id"],
                                       tool=ev["tool"], payload=payload,
                                       raw_text=ev.get("raw"),
                                       actor=ev.get("actor", "tool")))
    return TrajectoryCase(case_id=case["case_id"], category=case.get("category", "?"),
                          domain=case.get("domain", "?"),
                          tools=tuple(case.get("tools", [])),
                          calls=tuple(calls), results=tuple(results),
                          oracle_contracts=case.get("oracle_contracts"))


def case_hash(case: dict) -> str:
    return hashlib.sha256(json.dumps(
        {k: case.get(k) for k in ("case_id", "category", "domain", "tools",
                                  "trajectory", "oracle_contracts")},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def answer_temporal(ledger: FactLedger, case: dict) -> list[dict]:
    out = []
    for q in case.get("temporal_queries", []):
        kind = q["query"]
        et, eid, pred = q["entity_type"], q["entity_id"], q["predicate"]
        try:
            if kind == "LATEST":
                view = ledger.latest(et, eid, pred)
                actual = view.value if view.truth is Truth.TRUE else "UNKNOWN"
            elif kind == "PRIOR_TRUE":
                view = ledger.prior_true(et, eid, pred, q.get("value", "null"),
                                         before=q.get("as_of", 10**9))
                actual = view.truth.value
            elif kind == "AT_TIME":
                view = ledger.at_time(et, eid, pred, q.get("as_of", 0))
                actual = view.value if view.truth is Truth.TRUE else "UNKNOWN"
            else:
                actual = "UNKNOWN"
        except Exception as exc:
            actual = f"ERROR:{type(exc).__name__}"
        out.append({"query": kind, "entity": f"{et}:{eid}", "predicate": pred,
                    "expected": q.get("expected"), "actual": actual})
    return out


def cmd_run(args) -> None:
    cases = load_cases(Path(args.input))
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proposer = None
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if any(a for a in arms if a not in ALL_ARMS):
        sys.exit(f"unknown arm in {arms}; valid: {ALL_ARMS}")
    needs_llm = any(a in ("A_name_desc", "B_desc_schema", "C_full",
                          "E_nameblind", "H_hybrid") for a in arms)
    if needs_llm:
        proposer = MistralProposer(Path(args.env_file))
    rows = []
    started = time.time()
    for i, case in enumerate(cases):
        traj = to_trajectory(case)
        for arm in arms:
            try:
                output = run_arm(traj, arm, proposer)
            except Exception as exc:
                output = run_arm(traj, "D_result_only") if arm in ALL_ARMS else None
                if output is None:
                    raise
                output.arm = arm
                output.errors.append(f"arm fallback: {type(exc).__name__}: {exc}")
            row = {"case_id": case["case_id"], "category": case.get("category"),
                   "arm": arm, "input_hash": case_hash(case),
                   "output": output.as_dict()}
            if args.j_layer:
                ledger = build_ledger(traj, output)
                ledger, upgrades = apply_read_confirmation(ledger)
                row["upgrades"] = upgrades
                row["temporal"] = answer_temporal(ledger, case)
            rows.append(row)
        if (i + 1) % 10 == 0:
            print(f"[{i+1}/{len(cases)}] cases done", flush=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = {"input": str(args.input), "input_sha256": sha256_file(Path(args.input)),
            "output": str(out_path), "output_sha256": sha256_file(out_path),
            "arms": arms, "j_layer": bool(args.j_layer),
            "cases": len(cases), "rows": len(rows),
            "elapsed_s": round(time.time() - started, 1),
            "llm_calls": proposer.calls if proposer else 0,
            "prompt_tokens": proposer.prompt_tokens if proposer else 0,
            "completion_tokens": proposer.completion_tokens if proposer else 0}
    print(json.dumps(meta, ensure_ascii=False, indent=1))


def cmd_score(args) -> None:
    cases = {c["case_id"]: c for c in load_cases(Path(args.input))}
    preds = [json.loads(line) for line in Path(args.predictions).read_text(encoding="utf-8").splitlines() if line.strip()]
    by_arm: dict[str, list] = {}
    for row in preds:
        by_arm.setdefault(row["arm"], []).append(row)
    report = {}
    for arm, rows in sorted(by_arm.items()):
        scores = []
        for row in rows:
            case = cases.get(row["case_id"])
            if case is None:
                continue
            temporal = row.get("temporal")
            if temporal is None and args.j_layer:
                temporal = []
            scores.append(score_case(case, row["output"], temporal))
        agg = aggregate(scores)
        report[arm] = agg.as_dict()
    out = {"input": str(args.input), "predictions": str(args.predictions),
           "predictions_sha256": sha256_file(Path(args.predictions)),
           "j_layer": bool(args.j_layer), "arms": report}
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for arm, agg in sorted(report.items()):
        print(f"--- {arm} ---")
        print(f"  WorldFact precision: {agg['worldfact_precision']}")
        print(f"  WorldFact recall:    {agg['worldfact_recall']}")
        print(f"  unsupported rate:    {agg['unsupported_effect_rate']}")
        print(f"  strength exact:      {agg['strength_exact_frac']}")
        print(f"  provenance correct:  {agg['provenance_correct_frac']}")
        print(f"  temporal accuracy:   {agg['temporal_accuracy']}")
        print(f"  UNKNOWN on unsupp.:  {agg['unknown_rate_on_unsupported']}")


def _fact_signature(row: dict) -> set:
    sig = set()
    for v in row["output"].get("verified", []):
        f = v["fact"]
        sig.add((f["predicate"], f["entity_id"], f["value"], f["strength"]))
    for u in row["output"].get("ungrounded", []):
        sig.add((u["predicate"], u["entity_id"], u["value"], u["strength"]))
    return sig


def cmd_rename_check(args) -> None:
    originals = {c["case_id"]: c for c in load_cases(Path(args.originals))}
    renamed = load_cases(Path(args.renamed))
    proposer = None
    if args.arm in ("A_name_desc", "B_desc_schema", "C_full", "E_nameblind", "H_hybrid"):
        proposer = MistralProposer(Path(args.env_file))
    same, diff, total = 0, 0, 0
    details = []
    for rc in renamed:
        base_id = rc["case_id"].replace("::RN", "")
        base = originals.get(base_id)
        if base is None:
            continue
        out_orig = run_arm(to_trajectory(base), args.arm, proposer).as_dict()
        out_ren = run_arm(to_trajectory(rc), args.arm, proposer).as_dict()
        row_o = {"output": out_orig}
        row_r = {"output": out_ren}
        sig_o, sig_r = _fact_signature(row_o), _fact_signature(row_r)
        total += 1
        if sig_o == sig_r:
            same += 1
        else:
            diff += 1
            details.append({"case_id": rc["case_id"],
                            "original_only": sorted(sig_o - sig_r),
                            "renamed_only": sorted(sig_r - sig_o)})
    result = {"arm": args.arm, "total": total, "identical": same, "changed": diff,
              "invariance": (same / total if total else None), "diffs": details[:40]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "diffs"}, ensure_ascii=False, indent=1))


def _established_map(row_or_case: dict) -> set:
    return _fact_signature(row_or_case)


def cmd_cf_check(args) -> None:
    base = {c["case_id"]: c for c in load_cases(Path(args.originals))}
    cfs = load_cases(Path(args.cf))
    proposer = None
    if args.arm in ("A_name_desc", "B_desc_schema", "C_full", "E_nameblind", "H_hybrid"):
        proposer = MistralProposer(Path(args.env_file))
    flipped, stable, total = 0, 0, 0
    details = []
    for cf in cfs:
        base_id = cf["case_id"].split("::")[0]
        orig = base.get(base_id)
        if orig is None:
            continue
        sig_o = _established_map({"output": run_arm(to_trajectory(orig), args.arm, proposer).as_dict()})
        sig_c = _established_map({"output": run_arm(to_trajectory(cf), args.arm, proposer).as_dict()})
        total += 1
        if sig_o != sig_c:
            flipped += 1
        else:
            stable += 1
            details.append({"case_id": cf["case_id"], "note": "no flip despite evidence change"})
    result = {"arm": args.arm, "total": total, "flipped": flipped,
              "not_flipped": stable, "flip_rate": (flipped / total if total else None),
              "stable_details": details[:30]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "stable_details"}, ensure_ascii=False, indent=1))


def cmd_claim_probe(args) -> None:
    """Section 31: small diagnostic — candidate propositions vs the ledger."""
    cases = load_cases(Path(args.input))
    propositions = json.loads(Path(args.propositions).read_text(encoding="utf-8"))
    by_id = {c["case_id"]: c for c in cases}
    results = []
    for prop in propositions:
        case = by_id.get(prop["case_id"])
        if case is None:
            continue
        traj = to_trajectory(case)
        output = run_arm(traj, args.arm)
        ledger = build_ledger(traj, output)
        if args.j_layer:
            ledger, _ = apply_read_confirmation(ledger)
        answer = ledger.probe(Proposition(
            entity_type=prop["entity_type"], entity_id=prop["entity_id"],
            predicate=prop["predicate"], expected_value=prop.get("expected_value"),
            as_of=prop.get("as_of")))
        results.append({"case_id": prop["case_id"], "proposition": prop["claim"],
                        "expected_support": prop.get("expected_support"),
                        "actual_support": answer.support.value,
                        "note": answer.note,
                        "fact": answer.view.as_dict()})
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    correct = sum(1 for r in results if r["expected_support"] == r["actual_support"])
    print(f"claim probe: {correct}/{len(results)} correct")
    for r in results:
        mark = "OK " if r["expected_support"] == r["actual_support"] else "ERR"
        print(f"  [{mark}] {r['case_id']}: {r['proposition'][:70]} -> {r['actual_support']} (want {r['expected_support']})")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--arms", default="D_result_only,F_structural,G_extractive,I_contract")
    run.add_argument("--env-file", default="/workspace/guardian/secrets/mistral.env")
    run.add_argument("--j-layer", action="store_true")
    run.set_defaults(func=cmd_run)

    score = sub.add_parser("score")
    score.add_argument("--input", required=True)
    score.add_argument("--predictions", required=True)
    score.add_argument("--output", required=True)
    score.add_argument("--j-layer", action="store_true")
    score.set_defaults(func=cmd_score)

    ren = sub.add_parser("rename-check")
    ren.add_argument("--originals", required=True)
    ren.add_argument("--renamed", required=True)
    ren.add_argument("--arm", required=True)
    ren.add_argument("--output", required=True)
    ren.add_argument("--env-file", default="/workspace/guardian/secrets/mistral.env")
    ren.set_defaults(func=cmd_rename_check)

    cf = sub.add_parser("cf-check")
    cf.add_argument("--originals", required=True)
    cf.add_argument("--cf", required=True)
    cf.add_argument("--arm", required=True)
    cf.add_argument("--output", required=True)
    cf.add_argument("--env-file", default="/workspace/guardian/secrets/mistral.env")
    cf.set_defaults(func=cmd_cf_check)

    probe = sub.add_parser("claim-probe")
    probe.add_argument("--input", required=True)
    probe.add_argument("--propositions", required=True)
    probe.add_argument("--arm", default="I_contract")
    probe.add_argument("--j-layer", action="store_true")
    probe.add_argument("--output", required=True)
    probe.set_defaults(func=cmd_claim_probe)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
