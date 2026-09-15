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
  python3 scripts/build_v6_sealed_bundle.py --absence-attested --repo <repo>
      [--captures-dir DIR] --out-root <dir> [--skip-stage-a-probe] [--emit-manifest]
  python3 scripts/build_v6_sealed_bundle.py --selftest-absence --out-root <dir>

The --absence-attested mode emits a contract-complete v6_sealed_bundle.json whose
case_count is 0 and whose sealed data fields are the literal NOT_RECORDED: an
honest, machine-attested record that the sealed artifacts are absent, usable to
carry the contract and the evidence to another environment. It never fabricates
sealed content and expresses no KEEP/REJECT verdict (Stage A refuses such a
bundle by design, which the mode records as a probe).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(SCRIPT_DIR))
from c_alr_stage_a import catalog_fields, field_diff  # noqa: E402  (deterministic shared logic)

_PREREG_CANDIDATES = [
    REPO / "docs/vnext/C_ALR_PREREG_GATES_V1.json",   # repo layout
    SCRIPT_DIR / "C_ALR_PREREG_GATES_V1.json",          # handoff-kit layout
]
PREREG = next((p for p in _PREREG_CANDIDATES if p.exists()), _PREREG_CANDIDATES[0])
_STAGE_A_CANDIDATES = [
    REPO / "scripts/c_alr_stage_a.py",                 # repo layout
    SCRIPT_DIR / "c_alr_stage_a.py",                   # handoff-kit layout
]
STAGE_A_SCRIPT = next((p for p in _STAGE_A_CANDIDATES if p.exists()), _STAGE_A_CANDIDATES[0])
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


# --------------------------------------------------------- absence-attested mode

LS_LINE = re.compile(
    r"^-(?P<perm>\S+)\s+(?P<links>\d+)\s+(?P<owner>\S+)\s+(?P<group>\S+)\s+"
    r"(?P<size>\d+)\s+(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+"
    r"(?P<time>[\d:]+)\s+(?P<name>\S+)$"
)
SEALED_BASENAMES = ("predictions.json", "results.json", "failure_audit.json",
                    "prediction_seal.json", "freeze.json", "gates.json", "cases.json",
                    "post_hoc_adjudication.json")
NOT_COMPUTABLE = "NOT_COMPUTABLE_NO_SEALED_CASES"


def parse_ls_inventory(capture_paths: list) -> dict:
    """Deterministic parse of `ls -l` lines inside verbatim session tool-result
    captures. Only lines that structurally match an ls listing count; tool-result
    line-number prefixes are stripped. Returns {name: {bytes, recorded_mtime,
    seen_in}} sorted by name. Pure function of capture content."""
    files: dict = {}
    for cap in capture_paths:
        if not cap.exists():
            continue
        text = cap.read_text(encoding="utf-8", errors="replace")
        for raw in text.splitlines():
            line = raw.strip()
            line = re.sub(r"^\s*\d+[\u2192:]\s*", "", line)
            m = LS_LINE.match(line)
            if not m:
                continue
            name = m.group("name")
            rec = {"bytes": int(m.group("size")),
                   "recorded_mtime": f"{m.group('month')} {m.group('day')} {m.group('time')}"}
            if name in files:
                if name not in files[name]["seen_in"]:
                    files[name]["seen_in"].append(cap.name)
            else:
                files[name] = {**rec, "seen_in": [cap.name]}
    return dict(sorted(files.items()))


def summarize_inventory(files: dict, prefix: str) -> dict:
    """Machine-verified inventory summary for one experiment prefix, derived
    ONLY from parsed capture evidence. No guesses: anything not in the capture
    listing is simply absent from the counts."""
    cat: dict = {}
    case_ids = set()
    bare_case_files = 0
    sealed = {}
    for name, rec in files.items():
        if not name.startswith(prefix + "_"):
            continue
        rest = name[len(prefix) + 1:]
        m = re.match(r"case_(\d+)(?:_(.*))?\.json$", rest)
        if m:
            case_ids.add(int(m.group(1)))
            tail = m.group(2) or ""
            if tail:
                kind = re.sub(r"_result$", "", tail)
                kind = re.sub(r"(?:_\d+)+$", "", kind)
                cat[kind] = cat.get(kind, 0) + 1
            else:
                bare_case_files += 1
            continue
        if rest in SEALED_BASENAMES:
            sealed[rest] = {"bytes": rec["bytes"],
                            "recorded_mtime": rec["recorded_mtime"]}
    return {
        "prefix": prefix,
        "distinct_case_ids": len(case_ids),
        "bare_case_file_count": bare_case_files,
        "case_id_range": [min(case_ids), max(case_ids)] if case_ids else [],
        "per_case_artifact_counts": dict(sorted(cat.items())),
        "sealed_files_recorded_in_inventory": sealed,
        "evidence_basis": "deterministic parse of verbatim ls listings in the surviving session tool-result captures",
    }


def machine_search_record(repo: Path, captures_dir: Path) -> dict:
    """Live machine verification (performed at emission time, recorded as data):
    where the sealed V5/V6 artifacts were searched and what was found."""
    rec: dict = {"repo": str(repo)}
    glob_hits: dict = {}
    for pattern in ("policy_v4*.json", "policy_v5*.json", "policy_v6*.json"):
        found = sorted(p.name for p in (repo / "outputs/vnext").glob(pattern))
        glob_hits[pattern] = len(found)
        if found:
            glob_hits[pattern + "_names"] = found[:20]
    bench_hits = {p.name: True for p in (repo / "benchmarks/vnext").glob("policy_v[456]_cases.json")}
    rec["repo_outputs_vnext_glob"] = glob_hits
    rec["repo_benchmarks_cases_present"] = bench_hits or "none"
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        rec["git_head"] = head.stdout.strip() if head.returncode == 0 else "NOT_A_GIT_REPO"
        log = subprocess.run(["git", "-C", str(repo), "log", "--all", "--name-only",
                              "--pretty=format:", "--", "outputs/vnext"],
                             capture_output=True, text=True, timeout=60)
        names = sorted({l.strip() for l in log.stdout.splitlines()
                        if re.search(r"policy_v[456]_", l.strip())})
        rec["git_all_refs_policy_v456_files_ever_committed"] = names or []
    except Exception as e:  # noqa: BLE001 - recorded, never guessed
        rec["git_head"] = f"NOT_RECORDED ({e.__class__.__name__})"
    for up in (repo / "upload", repo.parent / "upload"):
        rec[f"upload:{up}"] = {"exists": up.exists(),
                                "file_count": (len(list(up.iterdir())) if up.exists() else 0)}
    caps = sorted(captures_dir.glob("*.txt")) if captures_dir.exists() else []
    rec["captures"] = {
        "path": str(captures_dir),
        "exists": captures_dir.exists(),
        "files": [{"file": c.name, "sha256": sha256_of(c), "bytes": c.stat().st_size}
                  for c in caps],
    }
    return rec


def stage_a_probe(bundle_path: Path, prereg_path: Path) -> dict:
    """Run the Stage A tool against the emitted absence bundle and record its
    behavior as machine data. Expected: refusal (exit 2) because cases is empty.
    The record itself expresses no verdict."""
    cmd = [sys.executable, str(STAGE_A_SCRIPT),
           "--bundle", str(bundle_path), "--prereg", str(prereg_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {
            "invoked": "c_alr_stage_a.py --bundle v6_sealed_bundle.json --prereg <frozen gates>",
            "exit_code": proc.returncode,
            "stderr_tail": proc.stderr.strip()[-400:],
            "expected_behavior": "refusal with exit code 2: validate_bundle requires a non-empty cases list",
            "interpretation": "Stage A correctly refuses to evaluate an absence-attested bundle; the STOP/KEEP/REJECT decision belongs to real sealed per-case data only",
        }
    except Exception as e:  # noqa: BLE001
        return {"invoked": "c_alr_stage_a.py", "error": f"{e.__class__.__name__}: {e}",
                "note": "probe failed to run; refusal behavior documented in validate_bundle"}


def user_reported_claims() -> dict:
    """The V5/V6 numbers quoted in the conversation/protocol doc - carried as
    clearly-labelled UNVERIFIED claims, never as facts."""
    return {
        "source": "docs/vnext/C_ALR_CYCLE_PROTOCOL.md section 1 (user-reported, pending machine re-verification)",
        "verification_status": "UNVERIFIED_USER_REPORTED_NO_ARTIFACT",
        "v5": {"C_accuracy": 0.781, "B4_accuracy": 0.847, "delta_pp": 6.8,
               "mcnemar_p": 0.093, "n_cases": 142},
        "v6": {"B4_minus_C_pp": -1.65, "mcnemar_p": 0.84, "n_cases": "NOT_RECORDED"},
        "admission_claims": {
            "precision_conditional_on_correct_primary": 0.93,
            "false_admissions_downstream_of_wrong_slot_primary": "6_of_7"},
        "disclaimer": ("conversation-level claims in this environment; NOT machine-verified because the "
                       "sealed artifacts are lost; must not be used as facts until re-verified against "
                       "restored artifacts (recovered/session_scripts/verify_v5_artifacts_v6cycle.py)"),
    }


def write_kit_manifest(kit_root: Path) -> int:
    """Freeze manifest over the whole kit (sha256 per file, sorted paths)."""
    entries = []
    for p in sorted(kit_root.rglob("*")):
        if (p.is_file() and p.name != "MANIFEST.sha256"
                and "__pycache__" not in p.parts and not p.name.endswith(".pyc")):
            entries.append((str(p.relative_to(kit_root)), sha256_of(p)))
    (kit_root / "MANIFEST.sha256").write_text(
        "\n".join(f"{h}  {rel}" for rel, h in entries) + "\n", encoding="utf-8")
    return len(entries)


def build_absence_attested(repo: Path, out_root: Path, captures_dir: Path,
                           run_probe: bool = True, emit_manifest: bool = False) -> dict:
    search_rec = machine_search_record(repo, captures_dir)
    inv_files = parse_ls_inventory(sorted(captures_dir.glob("*.txt"))) \
        if captures_dir.exists() else {}
    inventories = {p: summarize_inventory(inv_files, p) for p in ("policy_v4", "policy_v5")}
    inventories["policy_v6"] = {
        "files_in_surviving_inventories": sum(1 for n in inv_files if n.startswith("policy_v6")),
        "note": ("surviving ls inventories were captured 2026-09-13 15:52 and 18:08; the V6 run "
                 "postdates them (recovered decompose_v6_failures.py references policy_v6 artifacts); "
                 "no policy_v6 file was ever inventoried, committed, or pushed"),
    }
    machine_aggs = {
        "n_cases": 0,
        "C_accuracy": NOT_COMPUTABLE,
        "B4_accuracy": NOT_COMPUTABLE,
        "quadrants": {"status": NOT_COMPUTABLE,
                      "counts": {"C_correct_B4_correct": 0, "C_correct_B4_wrong": 0,
                                 "C_wrong_B4_correct": 0, "C_wrong_B4_wrong": 0}},
        "b4_error_stage_attribution": NOT_COMPUTABLE,
        "admission_precision_overall": NOT_RECORDED,
        "admission_precision_conditional_on_correct_primary": NOT_RECORDED,
        "c_errors_recoverable_by_1_local_mutation": NOT_COMPUTABLE,
        "c_errors_recoverable_by_le2_local_mutations": NOT_COMPUTABLE,
        "status_reason": ("sealed V5/V6 per-case prediction/result files are absent from this "
                         "environment (see provenance.absence_evidence); aggregates stay "
                         "NOT_RECORDED/NOT_COMPUTABLE rather than guessed"),
    }
    bundle = {
        "schema": "guardian-vnext-policy-v6-sealed-bundle-v1",
        "bundle_status": "ABSENCE_ATTESTED_NOT_SEALED",
        "experiment": "policy_v6 (guardian-vnext policy semantics)",
        "benchmark_name": "NOT_RECORDED (benchmark module lost with the previous sandbox; see provenance.absence_evidence)",
        "case_count": 0,
        "cases": [],
        "provenance": {
            "source_repo": str(repo),
            "absence_evidence": search_rec,
            "inventories_from_captures": inventories,
            "honesty_rules": ["no LLM", "no new semantic judgments", "no gold edits",
                              "no post-hoc prediction changes", "NOT_RECORDED instead of guesses"],
        },
        "user_reported_claims_UNVERIFIED": user_reported_claims(),
        "machine_aggregates": machine_aggs,
        "stage_a_compatibility": {
            "expected_behavior": "scripts/c_alr_stage_a.py refuses this bundle (empty cases) with exit code 2 by design",
            "note": "the STOP/KEEP/REJECT decision is only valid on real sealed per-case data",
        },
        "verdict_note": ("NO KEEP/REJECT conclusion: this absence-attested bundle carries zero sealed "
                         "cases; no verdict is derivable or expressed"),
        "rebuild_instructions": {
            "restore_verbatim_then_rebuild": [
                "benchmarks/vnext/policy_v6_cases.json (gold, frozen_before_predictions=true)",
                "outputs/vnext/policy_v6_predictions.json (sealed predictions)",
                "outputs/vnext/policy_v6_results.json (sealed results + mutation ledger)",
                "outputs/vnext/policy_v6_prediction_seal.json",
                "outputs/vnext/policy_v6_failure_audit.json (if it existed)",
            ],
            "command": "python3 builder/build_v6_sealed_bundle.py --repo <repo> --out-root <dir> [--v5-prefix policy_v5]",
            "sealed_mode_behavior": "refuses (exit 2) until the sealed files exist verbatim at canonical paths",
        },
    }
    bundle_path = out_root / "v6_sealed_bundle.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")

    aggregates = {
        "schema": "guardian-vnext-policy-v6-absence-attested-aggregates-v1",
        "bundle_file": "v6_sealed_bundle.json",
        "bundle_sha256": sha256_of(bundle_path),
        "behavioral_aggregates": machine_aggs,
        "inventory_evidence": inventories,
        "machine_search_record": search_rec,
        "user_reported_claims_UNVERIFIED": user_reported_claims(),
        "verdict_note": ("NO KEEP/REJECT: no verdict is derivable from absent sealed artifacts; "
                         "Stage A refusal on this bundle is the correct terminal behavior of the "
                         "preregistered cycle in this environment"),
    }
    if run_probe:
        aggregates["stage_a_probe"] = stage_a_probe(bundle_path, PREREG)
    (out_root / "machine_verified_aggregates.json").write_text(
        json.dumps(aggregates, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if emit_manifest:
        n = write_kit_manifest(out_root)
        print(f"kit manifest written: {n} files")
    return bundle


def synth_absence_fixture(root: Path) -> Path:
    """Explicitly SYNTHETIC fixture for the absence selftest: an empty repo tree
    plus a tiny synthetic capture containing SYNTHETIC ls lines."""
    (root / "outputs/vnext").mkdir(parents=True, exist_ok=True)
    (root / "benchmarks/vnext").mkdir(parents=True, exist_ok=True)
    cap = root / "synthetic_capture.txt"
    cap.write_text(
        "-rw-rw-r-- 1 z z  4208 Sep 13 16:18 policy_v5_case_000.json\n"
        "-rw-rw-r-- 1 z z  3669 Sep 13 16:17 policy_v5_case_000_arm_a.json\n"
        "-rw-rw-r-- 1 z z  801 Sep 13 16:17 policy_v5_case_000_arm_a_result.json\n"
        "-rw-rw-r-- 1 z z  9173 Sep 13 16:17 policy_v5_case_000_arm_b24.json\n"
        "-rw-rw-r-- 1 z z  3774 Sep 13 16:18 policy_v5_case_000_arm_b24_adm_00.json\n"
        "-rw-rw-r-- 1 z z  443 Sep 13 17:52 policy_v5_prediction_seal.json\n"
        "-rw-rw-r-- 1 z z  750862 Sep 13 17:52 policy_v5_predictions.json\n",
        encoding="utf-8")
    return cap.parent


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
    ap.add_argument("--absence-attested", action="store_true",
                    help="emit a contract-complete, machine-attested ABSENCE bundle "
                         "(case_count=0, sealed fields NOT_RECORDED) instead of refusing; "
                         "no KEEP/REJECT expressed")
    ap.add_argument("--captures-dir", default="/tmp/my-project/tool-results",
                    help="session tool-result captures used as verbatim inventory evidence")
    ap.add_argument("--skip-stage-a-probe", action="store_true",
                    help="do not subprocess-run c_alr_stage_a.py against the absence bundle")
    ap.add_argument("--emit-manifest", action="store_true",
                    help="write MANIFEST.sha256 over the whole out-root (kit layout)")
    ap.add_argument("--selftest-absence", action="store_true",
                    help="absence mode on an explicitly SYNTHETIC fixture (never real data)")
    args = ap.parse_args()

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    if args.selftest_absence:
        fixture = Path("/tmp/c_alr_absence_selftest_repo")
        if fixture.exists():
            shutil.rmtree(fixture)
        captures = synth_absence_fixture(fixture)
        bundle = build_absence_attested(fixture, out_root, captures,
                                        run_probe=not args.skip_stage_a_probe,
                                        emit_manifest=args.emit_manifest)
        print(f"absence selftest bundle emitted: case_count={bundle['case_count']} "
              f"status={bundle['bundle_status']}")
        return
    if args.absence_attested:
        repo = Path(args.repo)
        bundle = build_absence_attested(repo, out_root, Path(args.captures_dir),
                                        run_probe=not args.skip_stage_a_probe,
                                        emit_manifest=args.emit_manifest)
        aggs = bundle["machine_aggregates"]
        print(f"built v6_sealed_bundle.json (ABSENCE_ATTESTED_NOT_SEALED): "
              f"case_count={bundle['case_count']}, C_acc={aggs['C_accuracy']}, "
              f"B4_acc={aggs['B4_accuracy']}, no KEEP/REJECT expressed")
        return
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
