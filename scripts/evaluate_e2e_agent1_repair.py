"""E2E-agent-1 causal-repair experiment runner (dev causal study only).

Causal arms over the SEALED E2E V1 semantic outputs (zero LLM calls, fully
deterministic replay — the repairs are lower-layer only):

    A0  unchanged E2E-agent-1                (repair=None; must reproduce the
        sealed E0 predictions exactly — hard-verified)
    A1  A0 + scoped claim-UNKNOWN composition (scoped_status_v1)
    A2  A1 + deterministic claim value anchoring (claim_adapter_v2)
    A3  A2 + catalog-identity binding of unexercised atoms (binding_repair_v1)

Phases (write-once, refuse out of order):

    arms    compose A0-A3 from the sealed semantic outputs; per-arm
            predictions sealed BEFORE gold join; A0 == sealed E0 hard check
    score   gold join + the full metric set + paired stats + per-case ledger
            + hard invariants + the frozen selection rule
    freeze  freeze the selected candidate: commit SHA, configuration, all
            frozen component hashes, runnable command; STOP (no headline
            fresh evaluation — the shared Agent-1/Agent-2 holdout has not
            been provided; nothing in this runner generates or reads future
            shared gold)

Preregistration: docs/vnext/e2e/E2E_AGENT1_REPAIR_PREREG_V1.json (frozen
before the score phase; the selection rule below is its machine copy).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from guardian_truth.vnext.integrity import digest, prediction_seal, write_new  # noqa: E402
from guardian_truth.vnext.e2e import fresh_corpus_v1  # noqa: E402
from guardian_truth.vnext.e2e.core_v1 import analyze_e2e_v1  # noqa: E402
from guardian_truth.vnext.e2e.scoped_status_v1 import RepairConfig  # noqa: E402
from scripts.evaluate_vnext_e2e_v1 import _rehydrate, mcnemar_exact_p, newcombe_paired_ci  # noqa: E402

OUT = ROOT / "outputs" / "vnext"
PREFIX = "e2e_agent1_repair"
PREREG = ROOT / "docs" / "vnext" / "e2e" / "E2E_AGENT1_REPAIR_PREREG_V1.json"

SOURCES = ("src/guardian_truth/vnext/e2e", "scripts/evaluate_e2e_agent1_repair.py")

ARM_CONFIGS = {
    "A0": None,
    "A1": RepairConfig(scoped_unknown=True),
    "A2": RepairConfig(scoped_unknown=True, value_anchoring=True),
    "A3": RepairConfig(scoped_unknown=True, value_anchoring=True, catalog_binding=True),
}

# frozen selection rule (machine copy of the preregistration)
HARD_INVARIANTS = {
    "false_certified_no_error_eq": 0,
    "uncertified_definitive_eq": 0,
    "crash_eq": 0,
    "no_a0_correct_definitive_regressions": True,
}
FALSE_ERROR_BUDGET = "A0"          # no arm may exceed A0's false-certified ERROR
TIE_BREAK = ["max_error_f1", "min_false_certified_error", "max_cdc", "lowest_arm_index"]


def _commit_clean() -> str:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *SOURCES],
                      cwd=ROOT).returncode:
        raise ValueError("commit the repair implementation before running arms")
    return commit


def _compose(commit: str) -> int:
    cases = fresh_corpus_v1.build_fresh_corpus()
    case_ids = [item.case_id for item in cases]
    sealed_e0 = {row["case_id"]: row["status"] for row in json.loads(
        (OUT / "e2e_v1_E0_predictions.json").read_text(encoding="utf-8"))["rows"]}
    outputs_path = OUT / "e2e_v1_semantic_outputs"
    for item in cases:
        if not (outputs_path / f"{item.case_id}.json").exists():
            raise ValueError(f"sealed semantic outputs missing: {item.case_id}")
    for arm, repair in ARM_CONFIGS.items():
        rows = []
        for item in cases:
            record = json.loads((outputs_path / f"{item.case_id}.json").read_text(encoding="utf-8"))
            semantic = _rehydrate(item, record)
            try:
                output = analyze_e2e_v1(item.sources, semantic, "E0",
                                        max_worlds=4096, repair=repair)
                rows.append({
                    "case_id": item.case_id, "arm": arm,
                    "status": output.result.status.value,
                    "binary": output.product_decision.binary_label,
                    "certificate_valid": bool(output.result.certificate_check.valid)
                    if output.result.certificate_check else None,
                    "required_worlds": output.required_worlds,
                    "binding_repairs": output.diagnostics["binding_repairs"],
                    "claim_anchors": output.diagnostics["claim_anchors"],
                    "scoped_rationale": output.diagnostics["scoped_rationale"][:6],
                })
            except Exception as error:  # noqa: BLE001 - crash is a recorded outcome
                rows.append({"case_id": item.case_id, "arm": arm, "status": "CRASH",
                             "error": f"{type(error).__name__}: {error}"})
        if arm == "A0":
            mismatches = [row["case_id"] for row in rows
                          if row["status"] != sealed_e0[row["case_id"]]]
            if mismatches:
                raise ValueError("A0 does not reproduce the sealed E0 predictions: "
                                 + ",".join(mismatches[:5]))
        config = {"arm": arm,
                  "repair": (None if repair is None else
                             {"scoped_unknown": repair.scoped_unknown,
                              "value_anchoring": repair.value_anchoring,
                              "catalog_binding": repair.catalog_binding}),
                  "base": "E2E-agent-1 @ " + commit,
                  "semantic_outputs": "outputs/vnext/e2e_v1_semantic_outputs (sealed)",
                  "e0_semantic_pass": "frozen E2E V1 prompts/schemas (untouched)"}
        seal = prediction_seal(rows, case_ids, architecture_commit=commit,
                               configuration_sha256=digest(config))
        write_new(OUT / f"{PREFIX}_{arm}_predictions.json",
                  {"rows": rows, "seal": seal, "configuration": config,
                   "gold_joined": False})
        print(json.dumps({"arm": arm, "sealed": len(rows),
                          "prediction_sha256": seal["prediction_sha256"][:16]}))
    return 0


def _metrics(rows: dict, gold: dict, cohorts: dict):
    statuses = {cid: row["status"] for cid, row in rows.items()}
    error_gold = {cid for cid in gold if gold[cid].value == "PROVED_ERROR"}
    no_error_gold = {cid for cid in gold if gold[cid].value == "PROVED_NO_ERROR"}
    tp = sum(1 for cid in error_gold if statuses[cid] == "PROVED_ERROR")
    fp = sum(1 for cid in statuses
             if statuses[cid] == "PROVED_ERROR" and cid not in error_gold)
    fn = sum(1 for cid in error_gold if statuses[cid] != "PROVED_ERROR")
    tn = len(gold) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    definitive = {cid for cid in statuses
                  if statuses[cid] in ("PROVED_ERROR", "PROVED_NO_ERROR")}
    correct = {cid for cid in definitive if statuses[cid] == gold[cid].value}
    return {
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "error_precision": round(precision, 4),
        "error_recall": round(recall, 4),
        "error_f1": round(f1, 4),
        "proved_no_error_recall": round(
            sum(1 for cid in no_error_gold if statuses[cid] == "PROVED_NO_ERROR")
            / len(no_error_gold), 4) if no_error_gold else None,
        "unresolved": sum(1 for cid in statuses if statuses[cid] == "UNRESOLVED"),
        "inconsistent": sum(1 for cid in statuses if statuses[cid] == "INCONSISTENT"),
        "crashes": sum(1 for cid in statuses if statuses[cid] == "CRASH"),
        "false_certified_error": sorted(
            cid for cid in definitive if statuses[cid] == "PROVED_ERROR"
            and gold[cid].value != "PROVED_ERROR"),
        "false_certified_no_error": sorted(
            cid for cid in definitive if statuses[cid] == "PROVED_NO_ERROR"
            and gold[cid].value != "PROVED_NO_ERROR"),
        "gold_unresolved_but_system_error": sorted(
            cid for cid in statuses if statuses[cid] == "PROVED_ERROR"
            and gold[cid].value == "UNRESOLVED"),
        "uncertified_definitive": sorted(
            cid for cid in definitive if rows[cid].get("certificate_valid") is not True),
        "correct_definitive_coverage": round(len(correct) / len(gold), 4),
        "definitive_coverage": round(len(definitive) / len(gold), 4),
        "binding_repairs_applied": sum(rows[cid].get("binding_repairs", 0)
                                       for cid in rows),
        "claim_anchors_applied": sum(rows[cid].get("claim_anchors", 0)
                                     for cid in rows),
    }


def _paired(rows_a: dict, rows_b: dict, gold: dict) -> dict:
    def correct(row, cid):
        return (row["status"] == gold[cid].value
                and row["status"] in ("PROVED_ERROR", "PROVED_NO_ERROR"))
    b = sum(1 for cid in gold if correct(rows_a[cid], cid)
            and not correct(rows_b[cid], cid))
    c = sum(1 for cid in gold if not correct(rows_a[cid], cid)
            and correct(rows_b[cid], cid))
    lower, upper = newcombe_paired_ci(b, c, len(gold))
    return {"corrections": b, "regressions": c,
            "mcnemar_p": round(mcnemar_exact_p(b, c), 4),
            "newcombe_ci": [round(lower, 4), round(upper, 4)],
            "a0_correct_now_wrong": sorted(
                cid for cid in gold if correct(rows_b[cid], cid)
                and rows_a[cid]["status"] in ("PROVED_ERROR", "PROVED_NO_ERROR")
                and not correct(rows_a[cid], cid))}


def _select(arms_metrics: dict, rows: dict, gold: dict) -> dict:
    """The frozen selection rule (preregistration machine copy)."""
    eligible = {}
    for arm, metrics in arms_metrics.items():
        a0_correct = {cid for cid in gold
                      if rows["A0"][cid]["status"] in ("PROVED_ERROR", "PROVED_NO_ERROR")
                      and rows["A0"][cid]["status"] == gold[cid].value}
        regressions = sorted(
            cid for cid in a0_correct
            if rows[arm][cid]["status"] in ("PROVED_ERROR", "PROVED_NO_ERROR")
            and rows[arm][cid]["status"] != gold[cid].value)
        invariants_ok = (not metrics["false_certified_no_error"]
                         and not metrics["uncertified_definitive"]
                         and metrics["crashes"] == 0 and not regressions)
        budget_ok = (len(metrics["false_certified_error"])
                     <= len(arms_metrics["A0"]["false_certified_error"]))
        eligible[arm] = {"hard_invariants_pass": bool(invariants_ok),
                         "false_error_budget_pass": bool(budget_ok),
                         "a0_correct_regressions": regressions}
    order = {"A0": 0, "A1": 1, "A2": 2, "A3": 3}
    passing = [arm for arm, state in eligible.items()
               if state["hard_invariants_pass"] and state["false_error_budget_pass"]]
    selected = min(passing, key=lambda arm: (
        -arms_metrics[arm]["error_f1"],
        len(arms_metrics[arm]["false_certified_error"]),
        -arms_metrics[arm]["correct_definitive_coverage"],
        order[arm])) if passing else None
    return {"selected_arm": selected, "eligibility": eligible,
            "tie_break": TIE_BREAK, "false_error_budget": FALSE_ERROR_BUDGET}


def _score() -> int:
    cases = fresh_corpus_v1.build_fresh_corpus()
    gold = {item.case_id: item.gold.status for item in cases}
    cohorts = {item.case_id: item.cohort for item in cases}
    per_arm_rows, arms_metrics = {}, {}
    for arm in ARM_CONFIGS:
        document = json.loads((OUT / f"{PREFIX}_{arm}_predictions.json").read_text(encoding="utf-8"))
        if document.get("gold_joined") is not False:
            raise ValueError(f"{arm} predictions must stay sealed until this phase")
        per_arm_rows[arm] = {row["case_id"]: row for row in document["rows"]}
        arms_metrics[arm] = _metrics(per_arm_rows[arm], gold, cohorts)
    results = {
        "schema_version": "guardian-e2e-agent1-repair-results-v1",
        "corpus": "E2E V1 fresh corpus (69 cases, 42 cohorts) — DEVELOPMENT data",
        "gold_distribution": {status.value: sum(1 for item in cases
                                                if item.gold.status is status)
                              for status in set(item.gold.status for item in cases)},
        "arms": arms_metrics,
        "paired_vs_a0": {arm: _paired(per_arm_rows[arm], per_arm_rows["A0"], gold)
                         for arm in ("A1", "A2", "A3")},
        "selection": _select(arms_metrics, per_arm_rows, gold),
        "per_case_flips_to_error_vs_a0": {
            arm: sorted(cid for cid in per_arm_rows[arm]
                        if per_arm_rows[arm][cid]["status"] == "PROVED_ERROR"
                        and per_arm_rows["A0"][cid]["status"] != "PROVED_ERROR")
            for arm in ("A1", "A2", "A3")},
        "hard_invariants": HARD_INVARIANTS,
    }
    write_new(OUT / f"{PREFIX}_results.json", results)
    for arm in ARM_CONFIGS:
        document = json.loads((OUT / f"{PREFIX}_{arm}_predictions.json").read_text(encoding="utf-8"))
        document["gold_joined"] = True
        (OUT / f"{PREFIX}_{arm}_predictions.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({arm: {"f1": metrics["error_f1"], "fp": metrics["FP"],
                            "fn": metrics["FN"],
                            "false_no_error": metrics["false_certified_no_error"]}
                      for arm, metrics in arms_metrics.items()}, ensure_ascii=False))
    print(json.dumps({"selected": results["selection"]["selected_arm"]}))
    return 0


def _freeze() -> int:
    results = json.loads((OUT / f"{PREFIX}_results.json").read_text(encoding="utf-8"))
    selected = results["selection"]["selected_arm"]
    if selected is None:
        raise ValueError("no arm passed the frozen selection rule; nothing to freeze")
    commit = _commit_clean()
    config = ARM_CONFIGS[selected]
    component_files = sorted(str(path.relative_to(ROOT))
                             for path in (ROOT / "src" / "guardian_truth" / "vnext" / "e2e").glob("*.py")) + [
        "scripts/evaluate_e2e_agent1_repair.py",
        "tests/test_e2e_scoped_repair.py",
        "scripts/evaluate_vnext_e2e_v1.py",
        "src/guardian_truth/vnext/solver.py",
        "src/guardian_truth/vnext/proof_evidence.py",
        "src/guardian_truth/vnext/certificates.py",
        "src/guardian_truth/vnext/binder.py",
        "src/guardian_truth/vnext/claims.py",
    ]
    from guardian_truth.vnext.integrity import file_digest
    document = {
        "schema_version": "guardian-e2e-agent1-repair-freeze-v1",
        "selected_arm": selected,
        "frozen_commit": commit,
        "repair_configuration": (None if config is None else
                                 {"scoped_unknown": config.scoped_unknown,
                                  "value_anchoring": config.value_anchoring,
                                  "catalog_binding": config.catalog_binding}),
        "frozen_components_sha256": {name: file_digest(ROOT / name)
                                     for name in component_files},
        "frozen_semantic_frontends": {
            "policy": "historical frozen H0 (byte-identity chain to C-ALR; unchanged)",
            "goal": "Conservative frontend v1 (unchanged prompts/schemas)",
            "grs": "frozen GRS (diagnostic only; unchanged)"},
        "frozen_registries": {
            "t1_registry": "per-case trusted contracts (E2E V1 corpus; unchanged)",
            "repair_registry": "catalog-identity binding rule (binding_repair_v1)",
            "claim_adapter": "claim_adapter_v2 anchors",
            "scorer": "_metrics/_paired/_select in scripts/evaluate_e2e_agent1_repair.py"},
        "headline_fresh_evaluation": "STOP — shared Agent-1/Agent-2 holdout not yet "
                                     "provided; this freeze is the comparison candidate",
        "runnable_command": (
            "PYTHONPATH=src python scripts/evaluate_e2e_agent1_repair.py arms  # dev replay\n"
            "PYTHONPATH=src python scripts/evaluate_e2e_agent1_repair.py score\n"
            "PYTHONPATH=src python scripts/evaluate_e2e_agent1_repair.py freeze\n"
            "# future shared-holdout protocol: run the E2E V1 semantic passes on the "
            "holdout corpus with the frozen prompts, then compose the frozen arm "
            "(analyze_e2e_v1(..., repair=<frozen RepairConfig>)) with the SAME scorer"),
        "post_freeze_code_change_allowed": False,
    }
    write_new(OUT / f"{PREFIX}_freeze.json", document)
    print(json.dumps({"status": "FROZEN", "arm": selected, "commit": commit}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["arms", "score", "freeze"])
    args = parser.parse_args()
    if not PREREG.exists():
        raise ValueError("preregistration missing: " + str(PREREG))
    if args.phase == "arms":
        return _compose(_commit_clean())
    if args.phase == "score":
        return _score()
    return _freeze()


if __name__ == "__main__":
    raise SystemExit(main())
