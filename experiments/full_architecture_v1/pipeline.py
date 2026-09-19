"""full_architecture_v1 — arm pipeline for real cases (directive §22/§36).

One case, one arm -> prediction + certificate + per-stage hashes.

Arms:
  N1   frozen new frontend (typing OFF: gliner-sourced candidates excluded)
       + old Core (incumbent evidence + incumbent policy evaluation)
  N2   frozen new frontend (typing ON) + old Core
  N3   N2 + Clingo POLICY engine over incumbent evidence (tval values from
       the incumbent evidence layer are injected as facts; obligations/
       worlds/consensus run natively in ASP)
  N4   N3 + Clingo EVIDENCE engine (evidence.lp derives tval itself)
  N4-I N3 + Invariant trace-matching comparator cross-check (recorded; the
       comparator is never authoritative)
  N5   N4 + source-backed certificate + independent checker; the binary
       prediction requires a CHECKED certificate

Gold firewall: the pipeline consumes (id, prompt, response) and the frozen
frontend snapshot only — labels never enter any stage.
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

_FULLARCH = Path(__file__).resolve().parent
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
_REPO = _FULLARCH.parents[1]
for p in (str(_BAKEOFF), str(_BAKEOFF / "backends"), str(_FULLARCH),
          str(_REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import clingo  # noqa: E402

from neutral_types import (  # noqa: E402
    BackendResult, NeutralAtom, NeutralCoreInput, NeutralInterpretation,
    NeutralRule, PrimitiveResult, WorldResult,
)
from rule_ir import RuleIR  # noqa: E402
from policy.compiler import (  # noqa: E402
    BindingResolution, compile_rule_set, source_refs_from_rules,
)
from evidence.facts_builder import build_facts  # noqa: E402
from evidence.clingo_backend import evaluate as clingo_evaluate  # noqa: E402
from evidence.current_backend import evaluate as current_evaluate  # noqa: E402
from evidence.current_backend import probe as current_probe  # noqa: E402
from certificate.builder import build_certificate  # noqa: E402
from certificate.checker import check_certificate  # noqa: E402

END = 10**9
ARMS = ("N1", "N2", "N3", "N4", "N4-I", "N5")
_ASP_TRUTH = {"TRUE": "true", "FALSE": "false", "BOTH": "both",
              "UNKNOWN": "unk"}
FRONTEND_VERSION = "semantic_pipeline_v1@4e6d200 frozen snapshot (phi.jsonl)"


# ------------------------------------------------------------- frontend load

def load_phi_row(phi_path: Path, case_id: str) -> dict | None:
    for line in phi_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("case_id") == case_id:
            return row
    return None


def _candidates_for_arm(phi_row: dict, arm: str) -> list[RuleIR]:
    """Frozen frontend candidates, filtered per the arm's typing setting.

    typing OFF (N1): gliner2-sourced candidates (the semantic typing layer)
    are excluded — everything else (mistral/nuextract) stays.
    typing ON (N2..N5): all source-backed candidates.
    """
    out = []
    for candidate in phi_row.get("candidates", []):
        extractor = candidate.get("extractor", "")
        if arm == "N1" and extractor == "gliner2":
            continue
        rule = candidate.get("rule")
        if not rule:
            continue
        out.append(RuleIR.model_validate(rule))
    return out


def _normalized_binding_identity(value: object) -> str:
    """Canonical comparison form for an explicitly named tool or field.

    This intentionally permits only spelling differences such as case, spaces,
    hyphens, and underscores.  It is not semantic similarity.
    """
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]+", "_", value, flags=re.UNICODE).strip("_")


def _exact_proof_binding(rule: RuleIR, binding: dict) -> tuple[bool, str]:
    """Whether frozen binding data is an admissible formal premise.

    The frontend binder's embedding and cross-encoder decisions are useful
    routing signals, but cannot turn a RuleIR reference into a proof-level
    tool identity.  A proof binding therefore needs one explicitly exact
    candidate whose normalized name is the target text (and, when present,
    the RuleIR normalized ref).
    """
    if binding.get("status") != "BOUND":
        return False, "status-not-bound"
    candidates = binding.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        return False, "not-single-exact-candidate"
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get("method") != "exact":
        return False, "method-not-exact"
    name = _normalized_binding_identity(candidate.get("name"))
    target_text = _normalized_binding_identity(rule.target.text)
    if not name or name != target_text:
        return False, "target-name-not-exact"
    if rule.target.ref != "UNKNOWN" and name != _normalized_binding_identity(rule.target.ref):
        return False, "target-ref-not-exact"
    if (binding.get("semantic_text") is not None
            and name != _normalized_binding_identity(binding["semantic_text"])):
        return False, "semantic-text-not-exact"
    return True, "exact"


def _resolutions_for(candidates: list[RuleIR], phi_row: dict,
                     binding_markers: list[str] | None = None) \
        -> dict[str, BindingResolution]:
    """Proof-safe resolutions from the frozen frontend's binding stage.

    ``binding_markers`` keeps discarded neural BOUND decisions visible in the
    arm trace.  It is optional to keep this narrow helper convenient for
    direct callers and focused regressions.
    """
    by_rule = {candidate.get("rule_id"): candidate
               for candidate in phi_row.get("candidates", [])}
    resolutions: dict[str, BindingResolution] = {}
    for rule in candidates:
        source = by_rule.get(rule.rule_id, {})
        binding = source.get("binding") or {}
        status = binding.get("status", "UNKNOWN")
        names = tuple(candidate["name"] for candidate
                      in binding.get("candidates", [])[:4]
                      if isinstance(candidate, dict) and isinstance(candidate.get("name"), str))
        if status == "BOUND":
            admissible, reason = _exact_proof_binding(rule, binding)
            if not admissible:
                status, names = "UNKNOWN", ()
                if binding_markers is not None:
                    binding_markers.append(
                        f"binding:rule:{rule.rule_id}:bound-rejected:{reason}")
        resolution = BindingResolution(
            semantic_text=binding.get("semantic_text", rule.target.text),
            kind="action" if rule.target.kind == "ACTION" else "state",
            status=status if names else "UNKNOWN", names=names)
        resolutions[rule.target.ref if rule.target.ref != "UNKNOWN"
                    else f"text:{rule.target.text}"] = resolution
        resolutions[f"text:{rule.target.text}"] = resolution
        for leaf in (rule.conditions.leaves() if rule.conditions else []):
            text = leaf.text
            key = leaf.ref if leaf.ref != "UNKNOWN" else f"text:{text}"
            if key in resolutions or text is None:
                continue
            resolutions.setdefault(
                key, BindingResolution(text, "action" if leaf.kind == "ACTION"
                                       else "state", "UNKNOWN", ()))
    return resolutions


# --------------------------------------------------------- core input build

def build_core_input(case_row: dict, phi_row: dict, arm: str) \
        -> tuple[NeutralCoreInput, dict]:
    candidates = _candidates_for_arm(phi_row, arm)
    binding_markers: list[str] = []
    resolutions = _resolutions_for(candidates, phi_row, binding_markers)
    interpretations, stats = compile_rule_set(
        candidates, resolutions, case_id=case_row["id"])
    facts, fact_stats = build_facts(
        case_row["id"], case_row["prompt"], case_row["response"])
    source_refs = source_refs_from_rules(candidates)
    ci = NeutralCoreInput(
        case_id=case_row["id"], facts=facts,
        interpretations=interpretations,
        history_complete=False,
        completeness_basis=None,
        closed_action_universe=(),
        source_refs=source_refs,
        notes=f"fullarch arm {arm}; frontend {FRONTEND_VERSION}")
    return ci, {"compile": stats, "facts": fact_stats,
                "binding_markers": binding_markers}


# ------------------------------------------------------------- N3 mode

def clingo_policy_over_incumbent_evidence(ci: NeutralCoreInput) \
        -> BackendResult:
    """Clingo POLICY engine with incumbent evidence values injected.

    The evidence layer is the incumbent's (current backend probe); its
    per-atom truth values become ground tval/2 facts; policy.lp (condition
    folds, obligations, worlds, consensus) runs natively on ASP.
    """
    from evidence.adapter import build_program
    from evidence.adapter import POLICY_LP
    from clingo_backend import _run_program, _asp_truth, _consensus
    from clingo_backend import _emit_facts, _emit_obligations, _Program, _TreeEmitter

    # build the DATA (facts + query descriptors + obligations + trees)
    program_text, prog, obligations = build_program(ci)
    atoms = list(prog.query_atoms.values())
    tvals = {}
    if atoms:
        try:
            primitives = current_probe(ci, atoms)
            keyed = {p.atom_key: p.value for p in primitives}
            for qid, atom in prog.query_atoms.items():
                value = keyed.get(atom.key(), "UNKNOWN")
                tvals[qid] = _ASP_TRUTH.get(value, "unk")
        except Exception:
            tvals = {}
    injected = "\n".join(f"tval({qid}, {value})."
                         for qid, value in tvals.items()) or "tval(none, unk)."

    # N3 program: data + injected incumbent evidence values + policy rules
    # (with the composition algebra; evidence.lp derivation REMOVED — this
    # is exactly the N3/N4 boundary: same data, different evidence source)
    data_and_policy = program_text
    from evidence.adapter import EVIDENCE_LP
    data_only = data_and_policy.replace(EVIDENCE_LP, "")
    n3_program = data_only + "\n" + injected + "\n"
    try:
        _control, models = _run_program(n3_program)
    except Exception as error:
        return BackendResult(backend="fullarch-N3", status="ERROR",
                             input_content_hash=ci.content_hash(),
                             detail=f"{type(error).__name__}: {error}")
    if not models:
        return BackendResult(backend="fullarch-N3", status="ERROR",
                             input_content_hash=ci.content_hash(),
                             detail="no stable models")
    worlds: list[WorldResult] = []
    obligation_interp = {oid: interp_id for oid, interp_id, _r, _f
                         in obligations}
    for model in models:
        werr: dict[str, str] = {}
        safs: dict[str, str] = {}
        for atom in model:
            if atom.name == "werr" and len(atom.arguments) == 2:
                werr[str(atom.arguments[0]).strip('"')] = \
                    _asp_truth(str(atom.arguments[1]))
            elif atom.name == "saf" and len(atom.arguments) == 2:
                safs[str(atom.arguments[0])] = _asp_truth(
                    str(atom.arguments[1]))
        for interp_id, value in werr.items():
            safety = tuple(sorted(
                (oid, safety_value) for oid, safety_value in safs.items()
                if obligation_interp.get(oid) == interp_id))
            worlds.append(WorldResult(interp_id, value, safety))
    status = _consensus(worlds)
    return BackendResult(
        backend="fullarch-N3(clingo-policy, incumbent-evidence)",
        status=status, worlds=tuple(worlds), runtime_ms=0.0,
        input_content_hash=ci.content_hash(),
        notes=f"models={len(models)}; injected tvals={len(tvals)}")


# ------------------------------------------------------------- arm runner

def run_arm(case_row: dict, phi_row: dict, arm: str) -> dict:
    started = time.perf_counter()
    ci, build_stats = build_core_input(case_row, phi_row, arm)
    certificate = None
    checker_verdict = None
    invariant_note = None

    if arm in ("N1", "N2"):
        result = current_evaluate(ci)
    elif arm == "N3":
        result = clingo_policy_over_incumbent_evidence(ci)
    elif arm == "N4":
        result = clingo_evaluate(ci)
    elif arm == "N4-I":
        result = clingo_policy_over_incumbent_evidence(ci)
        try:
            from evidence.invariant_backend import probe as invariant_probe
            target_actions = {rule.action for interp in ci.interpretations
                              for rule in interp.rules}
            checks = []
            for action in sorted(target_actions)[:5]:
                atom = NeutralAtom(f"inv:{action}", "attempted",
                                   action=action, entity="*", actor="assistant",
                                   time_index=END)
                value = invariant_probe(ci, [atom])[0].value
                checks.append((action, value))
            invariant_note = {"comparator_checks": checks}
        except Exception as error:
            invariant_note = {"error": f"{type(error).__name__}: {error}"[:150]}
    elif arm == "N5":
        result = clingo_evaluate(ci)
        certificate = build_certificate(ci, result, frontend={
            "frontend": FRONTEND_VERSION,
            "arm": arm,
            "config_hash": "fullarch-v1-frozen",
        })
        checker_verdict = check_certificate(certificate, ci)
    else:
        raise ValueError(f"unknown arm {arm}")

    binary = 1 if result.status == "PROVED_ERROR" else 0
    if arm == "N5" and binary == 1 and not (checker_verdict or {}).get("ok"):
        binary = 0        # PROVED_ERROR without a checked certificate
        # (soundness over recall: uncertified definitive claims are not
        # predictions in the new architecture)
    elapsed = time.perf_counter() - started
    return {
        "case_id": case_row["id"],
        "arm": arm,
        "status": result.status,
        "binary": binary,
        "frontend_hash": phi_row.get("frontend_hash", "phi.jsonl"),
        "core_input_hash": result.input_content_hash,
        "worlds": {w.interp_id: w.error_value for w in result.worlds},
        "notes": result.notes,
        "detail": result.detail,
        "invariant_note": invariant_note,
        "certificate_digest": (certificate or {}).get("certificate_digest"),
        "checker_ok": (checker_verdict or {}).get("ok"),
        "checker_failures": (checker_verdict or {}).get("failures", []),
        "interpretations": len(ci.interpretations),
        "rules_lowered": build_stats["compile"]["rules_lowered"],
        "markers": (build_stats["binding_markers"]
                    + build_stats["compile"]["markers"])[:12],
        "facts": build_stats["facts"],
        "runtime_s": round(elapsed, 2),
    }
