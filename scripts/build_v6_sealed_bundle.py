#!/usr/bin/env python3
"""Build the portable sealed bundle for Policy V6 (and V5 admission export) for
independent C-ALR Stage A analysis.

CRITICAL HONESTY RULES (per user spec):
  - NO LLM calls, NO new semantic judgments, NO gold edits, NO post-hoc changes;
  - bundle content = verbatim copies of historical sealed artifacts plus
    deterministic joins/extractions of them;
  - anything not historically logged -> the literal string "NOT_RECORDED",
    never a guess;
  - no KEEP/REJECT conclusion: that belongs to the independent Stage A run.

Input shapes follow the real V5/V6 artifact structures (learned from the
surviving session scripts verify_v5_artifacts_v6cycle.py / decompose_v6_failures.py /
audit_v5_coordination_stage_a.py):
  predictions: [{case_id, arm_c|arm_a: {...}, arm_b245|arm_b24: {value: {structure,
                program, mutations: [{mutation_type, admission: {code,
                grounded_spans}}], final_programs?}}}]
  results: {arm_c: {...}, arm_b4: {...}, mutation_ledger: [rows {case_id,
           mutation_type, licensed, admitted_b4, judged_status}] or
           {rows: [...], aggregate: {...}}, paired: [...], per_case?}
  cases doc: {schema_version, frozen_before_predictions, cases: [{case_id, policy,
             admissible_structures: [structure dicts], extra_atoms, atom_catalog?}]}
Any shape deviation degrades to NOT_RECORDED, never to a guess.

Usage:
  python3 scripts/build_v6_sealed_bundle.py --repo <repo> [--v6-prefix policy_v6]
      [--v5-prefix policy_v5] --out-root <dir>
  python3 scripts/build_v6_sealed_bundle.py --selftest --out-root <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from c_alr_stage_a import catalog_fields, field_diff  # noqa: E402  (deterministic shared logic)

PREREG = REPO / "docs/vnext/C_ALR_PREREG_GATES_V1.json"
NOT_RECORDED = "NOT_RECORDED"
C_ARM_KEYS = ("arm_c", "arm_a")
B4_ARM_KEYS = ("arm_b245", "arm_b24", "arm_b4")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def arm_value(prediction: dict, keys: tuple):
    """Return (arm_key, payload) where payload is the arm object with 'value'
    unwrapped if present. Tolerant to direct-value shapes."""
    for k in keys:
        if k in prediction:
            obj = prediction[k]
            if isinstance(obj, dict) and isinstance(obj.get("value"), (dict, type(None))):
                return k, (obj.get("value") or {})
            return k, obj
    return None, None


def find_case_correct(results: dict, failure_audit, case_id: str, arm_key: str):
    """Deterministic search for per-case sealed correctness. Returns True/False
    or NOT_RECORDED. Never guessed."""
    for container in (results.get("per_case"), results.get("case_results")):
        if isinstance(container, dict):
            entry = container.get(case_id)
            if isinstance(entry, dict):
                for k in (arm_key, "c_correct", "case_correct", "correct"):
                    if isinstance(entry.get(k), bool):
                        return entry[k]
                arm_entry = entry.get(arm_key)
                if isinstance(arm_entry, dict):
                    for k in ("case_correct", "correct"):
                        if isinstance(arm_entry.get(k), bool):
                            return arm_entry[k]
    if isinstance(failure_audit, list):
        for entry in failure_audit:
            if isinstance(entry, dict) and entry.get("case_id") == case_id:
                for k in (arm_key, "case_correct", "correct"):
                    if isinstance(entry.get(k), bool):
                        return entry[k]
                arms = entry.get("arms")
                if isinstance(arms, dict):
                    a = arms.get(arm_key)
                    if isinstance(a, dict) and isinstance(a.get("case_correct"), bool):
                        return a["case_correct"]
                break
    return NOT_RECORDED


def ledger_rows(results: dict) -> list:
    led = results.get("mutation_ledger", [])
    if isinstance(led, dict):
        for k in ("rows", "ledger", "entries"):
            if isinstance(led.get(k), list):
                return led[k]
        return []
    return led if isinstance(led, list) else []


def build_case_entry(case: dict, pred: dict, results: dict, failure_audit,
                     c_arm: str, b4_arm: str) -> dict:
    cid = case.get("case_id") or (pred or {}).get("case_id")
    structs = case.get("admissible_structures") or []
    gold_semantic = dict(structs[0]) if structs and isinstance(structs[0], dict) else NOT_RECORDED
    c_key, c_val = arm_value(pred or {}, C_ARM_KEYS) if pred else (None, None)
    b_key, b_val = arm_value(pred or {}, B4_ARM_KEYS) if pred else (None, None)

    mutations = []
    if isinstance(b_val, dict):
        for m in b_val.get("mutations") or []:
            if not isinstance(m, dict):
                continue
            adm = m.get("admission") or {}
            mutations.append({
                "mutation_type": m.get("mutation_type", NOT_RECORDED),
                "decision": adm.get("code", m.get("decision", NOT_RECORDED)),
                "support_span": adm.get("grounded_spans", m.get("support_span", NOT_RECORDED)),
                "candidate_before": m.get("candidate_before", m.get("old", NOT_RECORDED)),
                "candidate_after": m.get("candidate_after", m.get("new", NOT_RECORDED)),
            })

    c_pred_obj = (pred or {}).get(c_arm if c_arm else "arm_c", NOT_RECORDED)
    b_pred_obj = (pred or {}).get(b4_arm if b4_arm else "arm_b245", NOT_RECORDED)

    return {
        "case_id": cid,
        "family": (cid.split("::")[0] if isinstance(cid, str) and "::" in cid
                   else case.get("family", NOT_RECORDED)),
        "gold": {
            "semantic_fields": gold_semantic,
            "admissible_programs": structs if structs else NOT_RECORDED,
            "behavioral_worlds": case.get("behavioral_worlds",
                                          case.get("worlds", NOT_RECORDED)),
            "case_correctness_definition": case.get("case_correctness_definition",
                                                    case.get("correctness_definition", NOT_RECORDED)),
            "policy_text_verbatim": case.get("policy", case.get("policy_text", NOT_RECORDED)),
        },
        "arm_c": {
            "sealed_prediction": c_pred_obj,
            "case_correct": find_case_correct(results, failure_audit, cid,
                                              c_arm or "arm_c"),
            "behavioral_results": (find_behavioral(results, failure_audit, cid,
                                                   c_arm or "arm_c")),
        },
        "b4": {
            "sealed_prediction": b_pred_obj,
            "case_correct": find_case_correct(results, failure_audit, cid,
                                              b4_arm or "arm_b245"),
            "behavioral_results": (find_behavioral(results, failure_audit, cid,
                                                   b4_arm or "arm_b245")),
            "primary": (b_val.get("structure", b_val.get("program", NOT_RECORDED))
                        if isinstance(b_val, dict) else NOT_RECORDED),
            "generated_mutations": (b_val.get("mutations", NOT_RECORDED)
                                    if isinstance(b_val, dict) else NOT_RECORDED),
            "admissions": mutations if mutations else NOT_RECORDED,
            "final_programs": (b_val.get("final_programs", NOT_RECORDED)
                               if isinstance(b_val, dict) else NOT_RECORDED),
            "declared_error_stage": (b_val.get("declared_error_stage", NOT_RECORDED)
                                     if isinstance(b_val, dict) else NOT_RECORDED),
        },
    }


def find_behavioral(results: dict, failure_audit, case_id: str, arm_key: str):
    for container in (results.get("per_case"), results.get("case_results")):
        if isinstance(container, dict):
            entry = container.get(case_id)
            if isinstance(entry, dict):
                arm_entry = entry.get(arm_key)
                if isinstance(arm_entry, dict) and isinstance(arm_entry.get("behavioral_results"), list):
                    return arm_entry["behavioral_results"]
    if isinstance(failure_audit, list):
        for entry in failure_audit:
            if isinstance(entry, dict) and entry.get("case_id") == case_id:
                arms = entry.get("arms")
                if isinstance(arms, dict) and isinstance(arms.get(arm_key), dict):
                    br = arms[arm_key].get("behavioral_results")
                    if isinstance(br, list):
                        return br
                break
    return NOT_RECORDED


def aggregate(bundle_cases: list, prereg: dict) -> dict:
    catalog = catalog_fields(prereg)
    max_mut = int(prereg["stage_a_rules"]["max_local_mutations_per_case"])
    n = len(bundle_cases)
    c_ok = [c["arm_c"]["case_correct"] for c in bundle_cases]
    b_ok = [c["b4"]["case_correct"] for c in bundle_cases]
    known = [i for i in range(n) if isinstance(c_ok[i], bool) and isinstance(b_ok[i], bool)]
    quad = {"C_correct_B4_correct": 0, "C_correct_B4_wrong": 0,
            "C_wrong_B4_correct": 0, "C_wrong_B4_wrong": 0}
    for i in known:
        key = ("C_correct_" if c_ok[i] else "C_wrong_") + ("B4_correct" if b_ok[i] else "B4_wrong")
        quad[key] += 1

    attrib = {k: 0 for k in ("slot_primary", "mutation_generation", "admission",
                             "compiler", "gold_benchmark_issue", "unknown_not_attributable")}
    not_recorded_correctness = n - len(known)
    for c in bundle_cases:
        if c["b4"]["case_correct"] is False:
            stage = c["b4"]["declared_error_stage"]
            if isinstance(stage, str) and stage in attrib:
                attrib[stage] += 1
            elif c["b4"]["primary"] in (None, NOT_RECORDED):
                attrib["slot_primary"] += 1
            elif c["b4"]["admissions"] not in (NOT_RECORDED, None, []):
                # deterministic divergence evidence: any admission present while the
                # case failed is recorded under admission only when declared; here we
                # cannot guess -> unknown
                attrib["unknown_not_attributable"] += 1
            else:
                attrib["unknown_not_attributable"] += 1
        elif c["b4"]["case_correct"] is not True:
            # correctness NOT_RECORDED: attribution intentionally skipped
            continue

    rec1 = rec2 = 0
    c_wrong_evaluable = 0
    for c in bundle_cases:
        if c["arm_c"]["case_correct"] is not False:
            continue
        c_wrong_evaluable += 1
        gold = c["gold"]["semantic_fields"]
        pred = c["arm_c"]["sealed_prediction"]
        fields = None
        if isinstance(pred, dict):
            v = pred.get("value") if isinstance(pred.get("value"), dict) else pred
            fields = v.get("structure") if isinstance(v.get("structure"), dict) else v.get("semantic_fields")
        if not (isinstance(gold, dict) and isinstance(fields, dict)):
            continue
        diffs = field_diff(fields, gold, catalog)
        if diffs and all(d["catalog_covered"] for d in diffs):
            if len(diffs) == 1:
                rec1 += 1
            if len(diffs) <= max_mut:
                rec2 += 1

    ledger_ok = isinstance(bundle_cases, list)
    return {
        "n_cases": n,
        "per_case_correctness_available_for": len(known),
        "per_case_correctness_not_recorded": not_recorded_correctness,
        "C_accuracy": (sum(1 for i in known if c_ok[i]) / len(known)) if known else NOT_RECORDED,
        "B4_accuracy": (sum(1 for i in known if b_ok[i]) / len(known)) if known else NOT_RECORDED,
        "quadrants": quad,
        "b4_error_stage_attribution": attrib,
        "c_errors_recoverable_by_1_local_mutation": rec1,
        "c_errors_recoverable_by_le2_local_mutations": rec2,
        "c_wrong_cases_evaluable_for_recoverability": c_wrong_evaluable,
        "recoverability_note": "counted only over cases with sealed C-wrong correctness AND field-level phi_C + gold representations; catalog-restricted typed diff, at most the preregistered mutation budget",
        "note": "attribution uses ONLY declared_error_stage when recorded; parse-failure->slot_primary; everything else stays unknown_not_attributable (never guessed)",
    }


def admission_aggregates(preds: list, results: dict, cases_by_id: dict) -> dict:
    rows = ledger_rows(results)
    if not rows:
        return {"admission_precision_overall": NOT_RECORDED,
                "admission_precision_conditional_on_correct_primary": NOT_RECORDED,
                "reason": "mutation ledger absent or empty in sealed results"}
    admitted = [r for r in rows if r.get("admitted_b4") is True]
    correct_adm = [r for r in admitted if r.get("licensed") is True]
    overall = (len(correct_adm) / len(admitted)) if admitted else NOT_RECORDED
    # conditional on correct slot primary: only computable when per-case primary
    # correctness is recorded in sealed artifacts; never re-judged here
    cond = NOT_RECORDED
    pc = results.get("per_case") or {}
    primary_status = {}
    if isinstance(pc, dict) and pc:
        for cid, entry in pc.items():
            if isinstance(entry, dict):
                v = entry.get("primary_correct", entry.get("slot_primary_correct"))
                if isinstance(v, bool):
                    primary_status[cid] = v
    if primary_status:
        adm_ok = [r for r in admitted if primary_status.get(r.get("case_id")) is True]
        ok_ok = [r for r in adm_ok if r.get("licensed") is True]
        cond = (len(ok_ok) / len(adm_ok)) if adm_ok else NOT_RECORDED
    return {
        "n_ledger_rows": len(rows),
        "n_admitted": len(admitted),
        "n_admitted_and_licensed": len(correct_adm),
        "admission_precision_overall": overall,
        "admission_precision_conditional_on_correct_primary": cond,
        "definition": "precision = admitted AND licensed / admitted, from the sealed mutation ledger only",
    }


def collect_supporting(repo: Path, prefixes: list, out_root: Path) -> list:
    copied = []
    sup = out_root / "supporting_files"
    sup.mkdir(parents=True, exist_ok=True)
    candidates = []
    for p in prefixes:
        candidates += [
            repo / f"outputs/vnext/{p}_freeze.json",
            repo / f"outputs/vnext/{p}_prediction_seal.json",
            repo / f"outputs/vnext/{p}_gates.json",
            repo / f"outputs/vnext/{p}_results.json",
            repo / f"outputs/vnext/{p}_predictions.json",
            repo / f"outputs/vnext/{p}_failure_audit.json",
            repo / f"benchmarks/vnext/{p}_cases.json",
        ]
    candidates += sorted((repo / "src/guardian_truth/vnext").glob("policy_v*.py"))
    candidates += sorted((repo / "docs/vnext").glob("POLICY_V*.md"))
    for src in candidates:
        if src.exists() and src.is_file():
            dest = sup / src.name
            if not dest.exists():
                shutil.copy2(src, dest)
            copied.append({"file": src.name, "source_path": str(src),
                           "sha256": sha256_of(dest), "bytes": dest.stat().st_size})
    return copied


def build(prefix: str, repo: Path, out_root: Path) -> dict:
    cases_doc = load_json(repo / f"benchmarks/vnext/{prefix}_cases.json") or {}
    cases = cases_doc.get("cases", cases_doc if isinstance(cases_doc, list) else [])
    preds = load_json(repo / f"outputs/vnext/{prefix}_predictions.json") or []
    if isinstance(preds, dict):
        preds = preds.get("cases", [])
    if not cases and not preds:
        print(
            f"SOURCE ARTIFACTS NOT FOUND for prefix '{prefix}'. Expected:\n"
            f"  {repo}/benchmarks/vnext/{prefix}_cases.json\n"
            f"  {repo}/outputs/vnext/{prefix}_predictions.json\n"
            f"  {repo}/outputs/vnext/{prefix}_results.json\n"
            f"  {repo}/outputs/vnext/{prefix}_prediction_seal.json\n"
            f"Refusing to emit an empty or fabricated bundle. Re-supply the historical "
            f"sealed artifacts (verbatim) and re-run.", file=sys.stderr)
        sys.exit(2)
    results = load_json(repo / f"outputs/vnext/{prefix}_results.json") or {}
    failure_audit = load_json(repo / f"outputs/vnext/{prefix}_failure_audit.json")
    seal = load_json(repo / f"outputs/vnext/{prefix}_prediction_seal.json") or {}
    freeze = load_json(repo / f"outputs/vnext/{prefix}_freeze.json") or {}
    gates = load_json(repo / f"outputs/vnext/{prefix}_gates.json") or {}
    if isinstance(failure_audit, dict):
        failure_audit = failure_audit.get("cases", failure_audit.get("rows", []))

    preds_by_id = {p.get("case_id"): p for p in preds if isinstance(p, dict)}
    c_arm = b4_arm = None
    if preds:
        c_arm, _ = arm_value(preds[0], C_ARM_KEYS)
        b4_arm, _ = arm_value(preds[0], B4_ARM_KEYS)

    bundle_cases = []
    for case in cases:
        pred = preds_by_id.get(case.get("case_id"))
        bundle_cases.append(build_case_entry(case, pred, results, failure_audit,
                                             c_arm, b4_arm))

    prereg = json.loads(PREREG.read_text())
    agg = aggregate(bundle_cases, prereg)
    adm = admission_aggregates(preds, results, {})
    seal_block = {"seal_file": f"{prefix}_prediction_seal.json",
                  "seal_verbatim": seal,
                  "seal_digest_recheck": "NOT_RECORDED (integrity module unavailable in this environment; sha256 of the copied file is recorded in supporting_files)"}
    bundle = {
        "schema": "guardian-vnext-policy-v6-sealed-bundle-v1",
        "experiment": prefix,
        "provenance": {
            "source_repo": str(repo),
            "freeze_verbatim": freeze,
            "gates_verbatim": gates,
            "benchmark_frozen_before_predictions": cases_doc.get("frozen_before_predictions", NOT_RECORDED),
            "honesty_rules": ["no LLM", "no new semantic judgments", "no gold edits",
                              "no post-hoc prediction changes", "NOT_RECORDED instead of guesses"],
        },
        "seal": seal_block,
        "cases": bundle_cases,
        "machine_aggregates": {**agg, **adm},
        "verdict_note": "NO KEEP/REJECT conclusion here: decided only by the independent Stage A environment",
    }
    (out_root / f"{prefix}_sealed_bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    return bundle


def write_readme(out_root: Path, bundles: dict, supporting: list) -> None:
    lines = ["# Policy V6 / V5 sealed handoff for independent C-ALR Stage A", ""]
    lines.append("Built by scripts/build_v6_sealed_bundle.py - deterministic join/extraction of")
    lines.append("historical sealed artifacts only. No LLM, no new judgments, no gold edits;")
    lines.append("unlogged stage-level fields carry the literal value NOT_RECORDED.")
    lines.append("No KEEP/REJECT conclusion is expressed or implied here.")
    lines.append("")
    lines.append("## Bundles")
    for name, b in bundles.items():
        agg = b.get("machine_aggregates", {})
        lines.append(f"- `{name}_sealed_bundle.json` - experiment `{b.get('experiment')}`, "
                     f"{agg.get('n_cases')} cases, arms in predictions: "
                     f"C-arm + B4-arm (see per-case `arm_c` / `b4`).")
    lines.append("")
    lines.append("## Machine aggregates")
    lines.append("```json")
    lines.append(json.dumps({k: b["machine_aggregates"] for k, b in bundles.items()},
                            ensure_ascii=False, indent=1))
    lines.append("```")
    lines.append("")
    lines.append("## Supporting frozen files (verbatim copies, sha256)")
    lines.append("| file | sha256 | source |")
    lines.append("|---|---|---|")
    for s in supporting:
        lines.append(f"| {s['file']} | {s['sha256'][:16]}.. | {s['source_path']} |")
    lines.append("")
    lines.append("Freeze location: `outputs/vnext/<prefix>_freeze.json`; seal: "
                 "`outputs/vnext/<prefix>_prediction_seal.json`; gold: "
                 "`benchmarks/vnext/<prefix>_cases.json`; predictions: "
                 "`outputs/vnext/<prefix>_predictions.json`; scorer: sealed "
                 "`<prefix>_results.json` (scorer code = `src/guardian_truth/vnext/policy_v*.py` where copied).")
    (out_root / "README_BUNDLES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def synth_fixture(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "benchmarks/vnext").mkdir(parents=True, exist_ok=True)
    (root / "outputs/vnext").mkdir(parents=True, exist_ok=True)
    cases = []
    preds = []
    per_case = {}
    ledger = []
    specs = [
        ("SYNTH_TEST::000", "simple", True, True, {"modality": "IF"}, {"modality": "ONLY_IF"}, True, True),
        ("SYNTH_TEST::001", "simple", True, False, {"temporal": "BEFORE"}, {"temporal": "BEFORE"}, True, False),
        ("SYNTH_TEST::002", "scope", False, True, {"quantification": "ANY"}, {"quantification": "ALL"}, False, True),
        ("SYNTH_TEST::003", "scope", False, False, {"actor": "assistant"}, {"actor": "assistant"}, True, False),
        ("SYNTH_TEST::004", "only_if", True, True, {"exception_attachment": "a"}, {"exception_attachment": "a"}, True, True),
        ("SYNTH_TEST::005", "cardinality", False, True, {"regulated_kind": "kind_x"}, {"regulated_kind": "kind_y"}, False, True),
    ]
    for cid, fam, c_ok, b_ok, c_struct, gold_struct, primary_ok, mut_licensed in specs:
        cases.append({"case_id": cid, "family": fam, "policy": f"synthetic policy {cid}",
                      "admissible_structures": [gold_struct],
                      "behavioral_worlds": [{"world_id": f"{cid}::w0", "expected": "NO_VIOLATION"}],
                      "case_correctness_definition": "SYNTHETIC: behavioral agreement on distinguishing worlds"})
        preds.append({"case_id": cid,
                      "arm_c": {"value": {"structure": c_struct, "program": {}}},
                      "arm_b245": {"value": {"structure": dict(gold_struct if primary_ok else c_struct),
                                              "program": {},
                                              "mutations": [{"mutation_type": "IF_TO_ONLY_IF",
                                                             "admission": {"code": "SUPPORTED",
                                                                           "grounded_spans": ["span"]},
                                                             "candidate_before": c_struct,
                                                             "candidate_after": gold_struct}],
                                              "final_programs": [{}]}}})
        per_case[cid] = {"arm_c": {"case_correct": c_ok},
                         "arm_b245": {"case_correct": b_ok},
                         "primary_correct": primary_ok}
        ledger.append({"case_id": cid, "mutation_type": "IF_TO_ONLY_IF",
                       "licensed": mut_licensed,
                       "admitted_b4": True if mut_licensed else (False if cid.endswith("001") else True),
                       "judged_status": "SUPPORTED"})
    (root / "benchmarks/vnext/policy_v6_cases.json").write_text(
        json.dumps({"schema_version": "SYNTHETIC", "frozen_before_predictions": True, "cases": cases}, indent=1))
    (root / "outputs/vnext/policy_v6_predictions.json").write_text(json.dumps(preds, indent=1))
    (root / "outputs/vnext/policy_v6_results.json").write_text(json.dumps({
        "arm_c": {}, "arm_b4": {}, "per_case": per_case,
        "mutation_ledger": ledger, "paired": []}, indent=1))
    (root / "outputs/vnext/policy_v6_prediction_seal.json").write_text(
        json.dumps({"prediction_sha256": "SYNTHETIC", "gold_joined": False}))
    (root / "outputs/vnext/policy_v6_failure_audit.json").write_text(json.dumps([]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--v6-prefix", default="policy_v6")
    ap.add_argument("--v5-prefix", default=None)
    ap.add_argument("--out-root", default="/home/z/my-project/download/policy_v6_c_alr_handoff")
    ap.add_argument("--selftest", action="store_true",
                    help="run on an explicitly SYNTHETIC fixture (never real data)")
    args = ap.parse_args()

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    if args.selftest:
        fixture = Path("/tmp/c_alr_bundle_selftest_repo")
        if fixture.exists():
            shutil.rmtree(fixture)
        synth_fixture(fixture)
        repo = fixture
        prefixes = ["policy_v6"]
    else:
        repo = Path(args.repo)
        prefixes = [args.v6_prefix] + ([args.v5_prefix] if args.v5_prefix else [])

    bundles = {}
    for p in prefixes:
        b = build(p, repo, out_root)
        bundles[p] = b
        agg = b["machine_aggregates"]
        print(f"built {p}_sealed_bundle.json: n={agg['n_cases']} "
              f"C_acc={agg['C_accuracy']} B4_acc={agg['B4_accuracy']}")
    supporting = collect_supporting(repo, prefixes, out_root)
    write_readme(out_root, bundles, supporting)
    print(f"README written with {len(supporting)} supporting files; "
          f"out_root={out_root}")


if __name__ == "__main__":
    main()
