"""semantic_pipeline_v1 — Phase 15D: FINAL GUARDIAN delta (A0 vs A8).

A0: incumbent E2E core at HEAD production defaults (h0_hist policy frontend,
conservative goal frontend, claims, T2, binding; premises gated OFF) with a
fresh Mistral semantic cache.

A8: the SAME incumbent core with the policy frontend SUBSTITUTED by the
semantic-pipeline Phi (oracle_policy=True with rows built deterministically
from Phi candidates via the core_adapter).  The ledger, world algebra, solver
and certificate checker are untouched; the goal/claim/T2 modules and their
cache entries are shared between A0 and A8.

Also runs the pipeline frontend on the synthetic held-out set.

Honest limitations carried into the core (documented in the report):
  - RuleIR comparisons/cardinalities are recorded as unresolved terms;
  - KB-derived rules enter Phi but their quotes do not ground in the policy
    normative text, so the lowering keeps them unresolved (never fabricated).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace as dataclass_replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
_SRC = str(REPO / "src")
for path in (_SRC, str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from guardian_truth.vnext.e2e.competition_adapter_v1 import adapt_competition_input
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, SEMANTICS_ARMS
from guardian_truth.vnext.adapters import AdapterMode

from source_segments import build_timeline, load_development_rows
from rule_ir import RuleIR
from core_adapter import compile_rule_ir_reading
from synthetic_cases import load_synthetic_cases

OUT = REPO / "outputs" / "vnext" / "semantic_pipeline_v1"
PHI_RESULTS = OUT / "phi.jsonl"
CACHE = OUT / "e2e_semantic_cache.json"
PROGRESS_A0 = OUT / "final_guardian_A0_progress.json"
PROGRESS_A8 = OUT / "final_guardian_A8_progress.json"
PROGRESS_A8_SYN = OUT / "final_guardian_A8_synthetic_progress.json"


def build_backend():
    from guardian_truth.settings import load_env_file
    from guardian_truth.vnext.e2e.backend_v1 import build_live_backend
    load_env_file(REPO / ".env")   # makes MISTRAL_API_KEY visible; never printed
    return build_live_backend(provider="mistral", model="ministral-14b-latest",
                              api_key_env="MISTRAL_API_KEY", cache_path=CACHE,
                              max_output_tokens=4096, reasoning_effort=None,
                              fail_fast_error_categories=("rate_limit", "insufficient_user_quota", "quota"))


class SemanticPipelineGuardian:
    """Experiment-side wrapper: the policy frontend is REPLACED by the
    semantic-pipeline Phi (compiled via core_adapter + the incumbent's own
    compile_h0).  Implemented by TRUE subclassing of the incumbent guardian -
    no core file is modified; the ledger, world algebra, solver and
    certificate checker are the incumbent's.

    Candidate ADMISSION (Phase 13: grounding, schema validity, NLI check and
    entity binding jointly decide admissibility - never a vote):
      - NLI-contradicted candidates are excluded (cannot be the only
        interpretation);
      - UNKNOWN modality / UNKNOWN target are excluded (adapter abstains);
      - the target must BIND (BOUND, or AMBIGUOUS containing the target ref)
        - unbound semantic actions cannot produce obligations, only noise;
      - NEUTRAL candidates are kept (uncertainty preserved), ENTAILMENT kept.
    """

    def __init__(self, backend, phi_candidates: list[dict], kb_normative: str,
                 tool_names: frozenset, **kwargs):
        from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
        pipeline = self
        self.phi_candidates = phi_candidates
        self.kb_normative = kb_normative
        # incumbent-lowering-compatible admission: the action key must name a
        # DECLARED tool exactly (the H0 normalized_key convention); rules
        # about non-tool behavior belong to the claims stage, not the policy
        # axis
        self.admitted = _admit_candidates(phi_candidates, tool_names)

        class _Guardian(GuardianE2EV1):
            def _policy_readings(self, inner_case, state_contract, catalog):
                rules = [RuleIR.model_validate(candidate["rule"])
                         for candidate in pipeline.admitted]
                normative = inner_case.system_policy + pipeline.kb_normative
                reading, notes = compile_rule_ir_reading(rules, normative, state_contract, catalog)
                if reading is None:
                    return (), (("policy_semantic_pipeline", "COMPILE",
                                 f"no lowerable rule ({notes})"),), inner_case.system_policy
                return (reading,), (), normative

        self.guardian = _Guardian(backend, **kwargs)

    def analyze_e2e_v1(self, case):
        return self.guardian.analyze_e2e_v1(case)


class RetrievalAugmentedGuardian:
    """A1: the INCUMBENT frontends unchanged, but the policy-frontend input is
    augmented with retrieved KB/document normative text (the new retrieval
    layer).  Measures what retrieval alone contributes before any new
    extractor is used."""

    def __init__(self, backend, kb_normative: str, **kwargs):
        from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
        outer = self
        self.kb_normative = kb_normative

        class _Guardian(GuardianE2EV1):
            def _policy_readings(self, inner_case, state_contract, catalog):
                if not outer.kb_normative:
                    return super()._policy_readings(inner_case, state_contract, catalog)
                from dataclasses import replace as _replace
                extended = _replace(inner_case, system_policy=inner_case.system_policy + outer.kb_normative)
                return super()._policy_readings(extended, state_contract, catalog)

        self.guardian = _Guardian(backend, **kwargs)

    def analyze_e2e_v1(self, case):
        return self.guardian.analyze_e2e_v1(case)


def _retrieval_kb_suffix(record: dict) -> str:
    """KB/document-like retrieved fragments for the case (channel D), rendered
    as a machine-suffix block (same mechanism class as the incumbent's)."""
    from source_segments import build_timeline
    from retrieval import kb_channel
    timeline = build_timeline(record["id"], record["prompt"], record["response"])
    kb = kb_channel(timeline)
    if not kb:
        return ""
    by_id = {f.fragment_id: f for f in timeline.fragments}
    quotes = [by_id[fid].text[:600] for fid in sorted(kb)[:12]]
    return "\nKB_DOCUMENTS=" + " \n".join(quotes)


def _admit_candidates(candidates: list[dict], tool_names: frozenset) -> list[dict]:
    """Admission filter over Phi candidates for lowering (see class docstring).
    The final gate mirrors the incumbent H0 convention: the action key must
    be a declared tool name, otherwise the V1 lowering cannot bind it."""
    admitted = []
    for candidate in candidates:
        flags = candidate.get("flags", {})
        if flags.get("contradicted_by_nli"):
            continue
        rule = candidate.get("rule", {})
        if rule.get("modality") == "UNKNOWN":
            continue
        target = rule.get("target", {})
        if target.get("kind") == "UNKNOWN" and target.get("ref") == "UNKNOWN":
            continue
        if target.get("ref") not in tool_names:
            continue   # cannot become a call obligation in the V1 lowering
        binding = candidate.get("binding") or {}
        status = binding.get("status")
        names = {entry.get("name") for entry in binding.get("candidates", [])}
        target_ref = target.get("ref")
        if status == "UNKNOWN":
            continue
        if status == "AMBIGUOUS" and target_ref not in names:
            continue
        admitted.append(candidate)
    return admitted


def load_phi() -> dict[str, list[dict]]:
    phi = {}
    for line in PHI_RESULTS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        phi[row["case_id"]] = row["candidates"]
    return phi


def phi_to_oracle_rows(candidates: list[dict], policy_text: str) -> tuple[list[dict], dict]:
    """Deterministic: Phi candidates -> authoritative_policy_reading rows via
    the incumbent compiler (compile_h0).  NLI-contradicted candidates are
    excluded (they cannot be the only accepted interpretation); UNKNOWN
    modality rules are abstained by the adapter."""
    rules = []
    for candidate in candidates:
        if candidate.get("flags", {}).get("contradicted_by_nli"):
            continue
        rules.append(RuleIR.model_validate(candidate["rule"]))
    reading, notes = compile_rule_ir_reading(rules, policy_text, None, frozenset())
    if reading is None:
        return [], notes
    rows = []
    for rule in reading.rules:
        rows.append({
            "kind": rule.kind, "modality": rule.modality, "action_key": rule.action_key,
            "actor": rule.actor, "relation": rule.relation,
            "conditions": [[condition.key, condition.negated] for condition in rule.conditions],
            "exceptions": [[exception.key, exception.negated] for exception in rule.exceptions],
            "scope": [[field, list(values)] for field, values in rule.scope],
            "quotes": list(rule.source_quotes),
            "unresolved_terms": list(rule.unresolved_terms),
        })
    return [{"rules": rows, "unresolved": list(reading.unresolved_terms)}], notes


def _kb_normative_suffix(case_id: str, phi_candidates: list[dict]) -> str:
    """KB-document normative text for grounding: quotes of NON-contradicted
    Phi candidates whose extraction unit was a KB document.  The incumbent's
    own machine-suffix mechanism class (POLICY_STATE_CONSTRAINTS etc.); no
    source text is rewritten."""
    from run_pipeline import _load_extraction
    extraction = _load_extraction()
    kept_rule_ids = {candidate["rule_id"] for candidate in phi_candidates
                     if not candidate.get("flags", {}).get("contradicted_by_nli")}
    quotes = []
    for row in extraction:
        if row.get("case_id") == case_id and row.get("unit_kind") == "kb_doc" \
                and row.get("rule_id") in kept_rule_ids:
            for span in row.get("rule", {}).get("source_spans", ()):
                quote = span.get("quote", "")
                if quote and len(quote) > 40:
                    quotes.append(quote[:600])
    if not quotes:
        return ""
    return "\nKB_DOCUMENTS=" + " \n".join(list(dict.fromkeys(quotes))[:12])


def run_arm(case_rows: list[dict], gold: dict[str, int], progress_path: Path,
            *, oracle: bool, phi: dict, retrieval_augmented: bool = False,
            max_worlds: int = 4096) -> list[dict]:
    from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
    from guardian_truth.vnext.tools import ContractRegistry

    backend = build_backend()
    existing = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else []
    done = {row["id"] for row in existing}
    for record in case_rows:
        case_id = record["id"]
        if case_id in done or case_id not in gold:
            continue
        adapted = adapt_competition_input({"id": case_id, "prompt": record["prompt"],
                                           "response": record["response"]})
        case = adapted.case
        arm_kwargs = dict(
            registry=ContractRegistry(()),
            arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
            max_worlds=max_worlds, adapter_mode=AdapterMode.COMPETITION,
            enable_t2=True, semantics=SEMANTICS_ARMS["B3"])
        if oracle:
            candidates = phi.get(case_id, [])
            from source_segments import build_timeline
            timeline = build_timeline(case_id, record["prompt"], record["response"])
            tools = frozenset(timeline.notes.get("catalog_tools", []))
            guardian = SemanticPipelineGuardian(
                backend, candidates, _kb_normative_suffix(case_id, candidates), tools, **arm_kwargs)
        elif retrieval_augmented:
            guardian = RetrievalAugmentedGuardian(
                backend, _retrieval_kb_suffix(record), **arm_kwargs)
        else:
            guardian = GuardianE2EV1(backend, **arm_kwargs)
        started = time.monotonic()
        try:
            analysis = guardian.analyze_e2e_v1(case)
            certificate_valid = (bool(analysis.result.certificate_check.valid)
                                 if analysis.result.certificate_check is not None else None)
            row = {
                "id": case_id, "core_status": analysis.result.status.value,
                "label": analysis.product_decision.binary_label,
                "certificate_valid": certificate_valid,
                "worlds": analysis.world_count,
                "frontend_failures": [{"component": name, "kind": kind}
                                      for name, kind, _ in analysis.frontend_statuses],
                "false_witnesses": [{"world_id": proof.world_id, "obligation_id": obligation_id}
                                    for proof in analysis.result.world_proofs
                                    for obligation_id, truth in proof.obligation_safety
                                    if (truth.value if hasattr(truth, "value") else str(truth)) == "FALSE"],
                "elapsed_s": round(time.monotonic() - started, 2),
            }
        except Exception as error:
            row = {"id": case_id, "core_status": "UNRESOLVED", "label": 0,
                   "certificate_valid": False, "worlds": 0, "frontend_failures": [],
                   "false_witnesses": [], "elapsed_s": round(time.monotonic() - started, 2),
                   "error": f"{type(error).__name__}:{str(error)[:300]}"}
        existing.append(row)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{'A8' if oracle else 'A0'} {case_id} {row['core_status']} "
              f"cert={row['certificate_valid']} {row['elapsed_s']}s live={backend.live_calls}",
              flush=True)
    return existing


def score(rows: list[dict], gold: dict[str, int]) -> dict:
    tp = sum(row["label"] == 1 and gold.get(row["id"]) == 1 for row in rows)
    fp = sum(row["label"] == 1 and gold.get(row["id"]) == 0 for row in rows)
    fn = sum(row["label"] == 0 and gold.get(row["id"]) == 1 for row in rows)
    tn = sum(row["label"] == 0 and gold.get(row["id"]) == 0 for row in rows)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    false_cert = sum(row["core_status"] == "PROVED_ERROR" and row["certificate_valid"]
                     and gold.get(row["id"]) == 0 for row in rows)
    return {"rows": len(rows), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": round(precision, 4), "recall": round(recall, 4), "F1": round(f1, 4),
            "false_certified_ERROR": false_cert}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("arm", choices=["A0", "A1", "A8", "A8_synthetic"])
    args = parser.parse_args()
    if args.arm == "A0":
        rows = load_development_rows(str(REPO / "valid.parquet"))
        gold = {row["id"]: int(row["label"]) for row in rows}
        results = run_arm(rows, gold, PROGRESS_A0, oracle=False, phi={})
        print(json.dumps(score(results, gold), indent=1))
    elif args.arm == "A1":
        rows = load_development_rows(str(REPO / "valid.parquet"))
        gold = {row["id"]: int(row["label"]) for row in rows}
        results = run_arm(rows, gold, OUT / "final_guardian_A1_progress.json",
                          oracle=False, phi={}, retrieval_augmented=True)
        print(json.dumps(score(results, gold), indent=1))
    elif args.arm == "A8":
        rows = load_development_rows(str(REPO / "valid.parquet"))
        gold = {row["id"]: int(row["label"]) for row in rows}
        results = run_arm(rows, gold, PROGRESS_A8, oracle=True, phi=load_phi())
        print(json.dumps(score(results, gold), indent=1))
    else:
        rows = load_synthetic_cases()
        gold = {row["id"]: int(row["label"]) for row in rows}
        results = run_arm(rows, gold, PROGRESS_A8_SYN, oracle=True, phi=load_phi())
        print(json.dumps(score(results, gold), indent=1))


if __name__ == "__main__":
    main()
