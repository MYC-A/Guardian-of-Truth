#!/usr/bin/env python3
"""Blast-radius experiment for the REP-11/SND-11 root-scope abstention fix.

Patches _row_binds_entity to reject ROOT-scope (flat) row binding, replays
the 144 viewed-development cases offline, and reports the verdict changes +
binary metric deltas. Diagnostic ONLY - no production code is modified.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from guardian_truth.vnext.adapters import AdapterMode  # noqa: E402
from guardian_truth.vnext.e2e.backend_v1 import build_live_backend  # noqa: E402
from guardian_truth.vnext.e2e import world_integration_v1 as wi  # noqa: E402
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1  # noqa: E402
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, E2ESemantics  # noqa: E402
from guardian_truth.vnext.e2e.experiment_v1 import load_corpus, registry_for  # noqa: E402

CORPORA = {
    "dev": ("outputs/vnext/e2e_v1_dev_corpus.json",
            "outputs/vnext/e2e_v1_dev_gold.json",
            "outputs/vnext/e2e_v1_dev_llm_cache.json"),
    "holdout": ("outputs/vnext/e2e_v1_holdout_corpus.json",
                "outputs/vnext/e2e_v1_holdout_gold.json",
                "outputs/vnext/e2e_v1_holdout_llm_cache.json"),
}
SLICES = 6
SEMANTICS = E2ESemantics(conservative_state=True, alternative_groups=True,
                         inconsistent_status=True, claim_typing=True)

_original_row_binds = wi._row_binds_entity
_original_action_atom = wi._prove_deterministic_action_atom


def _root_scope_rejecting(row_predicate, row_refs, entity):
    scope = wi._object_scope(row_predicate)
    if not scope:
        return False          # root-scope rows: envelope-ambiguous, not attributable
    return _original_row_binds(row_predicate, row_refs, entity)


def _gate_fallback_patched(atom, ledger, index=None, registry=None, semantics=None):
    """Same as the original but the observation fallback skips ROOT-scope
    observation rows (envelope-ambiguous); verified effects (declared
    field-level ownership) still resolve."""
    from guardian_truth.vnext.proof_records import PrimitiveProof, Reason
    from guardian_truth.vnext.types import Truth
    import guardian_truth.vnext.e2e.world_integration_v1 as mod
    from guardian_truth.vnext.proof_evidence import effect_is_verified
    import json as _json
    try:
        expected = _json.loads(atom.expected_json)
    except (ValueError, TypeError):
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.CLAIM_UNTYPED,))
    if type(expected) is not bool or atom.time_index < 0 or atom.time_index >= len(ledger.events):
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.TIME_UNBOUND,))
    calls = [event for event in ledger.events
             if event.kind == "call" and event.tool and event.tool.name == atom.predicate
             and event.actor == atom.actor and event.index <= atom.time_index]
    if atom.entity.value != "*":
        calls = [event for event in calls
                 if atom.entity.value in {ref.value for ref in event.entity_refs}]
    if calls:
        ids = tuple(event.event_id for event in calls)
        value = Truth.TRUE if expected else Truth.FALSE
        return PrimitiveProof(atom, value, ids if expected else (), () if expected else ids)
    key_tokens = set(atom.predicate.split("_"))
    trusted = semantics.conservative_state and index is not None and registry is not None

    def _trusted_attributable(item) -> bool:
        if not trusted:
            return True
        event = index.events_by_id.get(item.event_id)
        if event is not None and mod._pure_reader_event(event, index, registry):
            # SND-11: root-scope rows are not attributable entity state
            return mod._object_scope(item.predicate) != ()
        return any(effect.event_id == item.event_id and effect_is_verified(effect, ledger, index, registry)
                   for effect in ledger.effects)

    observations = [item for item in ledger.observations
                    if (item.predicate == atom.predicate or item.predicate in key_tokens)
                    and item.index <= atom.time_index
                    and (atom.entity.value == "*" or atom.entity.value in {ref.value for ref in item.entity_refs})
                    and _trusted_attributable(item)]
    if observations:
        latest = max(item.index for item in observations)
        support, refute = [], []
        for item in [observation for observation in observations if observation.index == latest]:
            try:
                actual = _json.loads(item.value_json)
            except (ValueError, TypeError):
                return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
            if type(actual) is type(expected):
                (support if actual == expected else refute).append(item.evidence_id)
        if support and refute:
            return PrimitiveProof(atom, Truth.BOTH, tuple(support), tuple(refute))
        if support:
            return PrimitiveProof(atom, Truth.TRUE, tuple(support), ())
        if refute:
            return PrimitiveProof(atom, Truth.FALSE, (), tuple(refute))
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
    if atom.entity.namespace != "e2e":
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
    for event in ledger.events[:atom.time_index + 1]:
        if event.actor == "unknown" or event.pairing_issue:
            return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
    if not ledger.history_complete:
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
    return PrimitiveProof(atom, Truth.FALSE if expected else Truth.TRUE, (), ("absence:complete-history:" + atom.atom_id,))


class OfflineInner:
    def propose(self, task, payload, schema):
        raise RuntimeError(f"OFFLINE CACHE MISS: task={task}")


def replay_backend() -> object:
    backend = build_live_backend(cache_path=None, env_path=ROOT / ".env")
    merged = {}
    for corpus_name in CORPORA:
        for i in range(SLICES):
            path = ROOT / f"outputs/vnext/e2e_v1_cycle3_{corpus_name}_B4h_live_cache_slice{i}.json"
            if path.exists():
                merged.update(json.loads(path.read_text(encoding="utf-8")))
        corpus_cache = ROOT / CORPORA[corpus_name][2]
        if corpus_cache.exists():
            merged.update(json.loads(corpus_cache.read_text(encoding="utf-8")))
    backend.cache.update(merged)
    backend.cache_path = None
    return backend


def run_arm(cases, backend):
    arm = E2EArmConfig("B4h", ("h0_hist",), ("conservative",))
    rows = []
    for case in cases:
        guardian = GuardianE2EV1(backend, registry=registry_for(case), arm=arm,
                                  max_worlds=4096, adapter_mode=AdapterMode.AUDIT,
                                  semantics=SEMANTICS)
        try:
            analysis = guardian.analyze_e2e_v1(case)
            rows.append({"case_id": case.case_id, "core_status": analysis.result.status.value,
                         "certificate_valid": bool(analysis.result.certificate_check
                                                   and analysis.result.certificate_check.valid)
                         if analysis.result.certificate_check else None})
        except Exception as error:
            rows.append({"case_id": case.case_id, "core_status": "UNRESOLVED",
                         "certificate_valid": False,
                         "error": f"{type(error).__name__}:{str(error)[:200]}"})
    return rows


def score(rows, gold):
    gold_error = {cid for cid, item in gold.items() if item.get("core_status") == "PROVED_ERROR"}
    gold_no_error = {cid for cid, item in gold.items() if item.get("core_status") == "PROVED_NO_ERROR"}
    tp = [r for r in rows if r["case_id"] in gold_error and r["core_status"] == "PROVED_ERROR"]
    fp = [r for r in rows if r["case_id"] not in gold_error and r["core_status"] == "PROVED_ERROR"]
    fn = [r for r in rows if r["case_id"] in gold_error and r["core_status"] != "PROVED_ERROR"]
    tn = [r for r in rows if r["case_id"] in gold_no_error and r["core_status"] == "PROVED_NO_ERROR"]
    uncertified = [r for r in rows if r["core_status"] in {"PROVED_ERROR", "PROVED_NO_ERROR"}
                   and not r.get("certificate_valid")]
    counts = {}
    for r in rows:
        counts[r["core_status"]] = counts.get(r["core_status"], 0) + 1
    return {"TP": len(tp), "FP": len(fp), "FN": len(fn), "TN": len(tn),
            "uncertified": len(uncertified), "status_counts": counts,
            "fp_ids": [r["case_id"] for r in fp]}


def main():
    backend = replay_backend()
    wi._row_binds_entity = _root_scope_rejecting   # patch 1: state channel
    wi._prove_deterministic_action_atom = _gate_fallback_patched  # patch 2: gate fallback
    try:
        report = {}
        for corpus_name, (corpus_path, gold_path, _c) in CORPORA.items():
            cases = load_corpus(ROOT / corpus_path)
            gold = json.loads((ROOT / gold_path).read_text(encoding="utf-8"))
            rows = run_arm(cases, backend)
            report[corpus_name] = score(rows, gold)
            print(corpus_name, json.dumps(report[corpus_name], indent=1))
    finally:
        wi._row_binds_entity = _original_row_binds
        wi._prove_deterministic_action_atom = _original_action_atom


if __name__ == "__main__":
    main()
