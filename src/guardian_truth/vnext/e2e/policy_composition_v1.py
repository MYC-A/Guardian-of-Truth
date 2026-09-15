"""Policy axis composition V1 (spec sections 25-53).

Frozen frontends are INJECTED (spec section 110: explicit dependencies): the
runner imports PARSE_TASK/REPAIR_TASK/STRUCTURE_SCHEMA from the frozen H0
source (scripts/evaluate_vnext_c_alr_reimpl.py) and the frozen GRS tasks from
policy_grs.py, so byte-identity holds by construction.  This module defines
the frontend protocol, the frozen one-parse-plus-one-repair protocol, and the
deterministic composition: compile both frontends into the shared v3 program
space, dedupe behaviorally equivalent readings over the combined
distinguishing-world surface, and RETAIN material disagreements as separate
policy interpretation choices (never a winner selection, spec sections 51-53).

Everything deterministic here: no LLM beyond the injected backends, no
wall-clock, no randomness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..policy_grs import (GRSInvalid, compile_dsl, hallucination_attempts,
                          validate_inventory)
from ..policy_grs_emission import EmissionInvalid, canonicalize_dsl
from ..policy_psb import composed_verdict
from ..policy_v3_benchmark import StructureInvalid, compile_v3_structure
from ..semantic import SemanticBackend, schema_valid
from .goal_types_v1 import AtomBindingCandidate


# ------------------------------------------------------------------- results

@dataclass(frozen=True)
class H0Result:
    status: str                    # VALID | INVALID | UNAVAILABLE
    program: dict | None
    payload_json: str | None
    telemetry: dict


@dataclass(frozen=True)
class GRSResult:
    status: str                    # VALID | INVALID | UNAVAILABLE
    alternatives: tuple[tuple[dict, ...], ...]   # compiled program lists
    dropped_rules: tuple[dict, ...]
    inventory: dict | None
    dsl_text: str | None
    canonicalized: bool
    hallucination: dict
    telemetry: dict


@dataclass(frozen=True)
class PolicyReading:
    reading_id: str                # policy:h0 | policy:grs:alt0 | ...
    frontend: str                  # h0 | grs
    programs: tuple[dict, ...]
    equivalent_to: tuple[str, ...] # deduped-away behaviorally equal reading ids

    @property
    def key(self) -> str:
        return "|".join(f"{p['modality']}/{p['relation']}/{'&'.join(','.join(c) for c in p['target_clauses'])}"
                        f"/{'&'.join(p['condition_literals'])}/{p['condition_mode']}"
                        f"/{'&'.join(p['exception_literals'])}/{p['exception_mode']}"
                        f"/{p['temporal']}" for p in self.programs)


@dataclass(frozen=True)
class PolicyComposition:
    readings: tuple[PolicyReading, ...]     # retained (deduped) policy choices
    h0: H0Result
    grs: GRSResult
    agreement: str                 # EQUIVALENT | DIFFERENT | ONE_INVALID | BOTH_INVALID
    equivalence_detail: dict
    unresolved_reason: str | None  # set when the policy axis cannot close


# --------------------------------------------------------------- H0 frontend

def make_h0_frontend(parse_task: str, structure_schema: dict, repair_task: str,
                     backend: SemanticBackend) -> Callable[[str, tuple[str, ...]], H0Result]:
    """The frozen H0 protocol: one primary parse over (policy_text,
    atom_catalog); exactly one machine-validation repair re-ask (transport/
    schema/compile failure only); compile via the shared v3 compiler.
    A schema-valid but semantically wrong answer is NEVER retried."""

    def frontend(policy_text: str, atom_catalog: tuple[str, ...]) -> H0Result:
        payload = {"policy_text": policy_text, "atom_catalog": list(atom_catalog)}
        proposal = backend.propose(parse_task, payload, structure_schema)
        telemetry = {"transport_status": proposal.transport_status,
                     "schema_status": proposal.schema_status, "repair_used": False}
        value = (proposal.value if proposal.transport_status == "SUCCESS"
                 and proposal.schema_status == "VALID" and schema_valid(proposal.value, structure_schema) else None)
        if value is None:
            repair_payload = dict(payload)
            repair_payload["failed_attempt"] = {
                "transport_status": proposal.transport_status,
                "schema_status": proposal.schema_status,
                "payload_json": proposal.payload_json}
            repair_payload["machine_error"] = ("transport_error" if proposal.transport_status != "SUCCESS"
                                               else "schema_invalid")
            proposal = backend.propose(repair_task, repair_payload, structure_schema)
            telemetry.update(repair_used=True,
                             repair_transport_status=proposal.transport_status,
                             repair_schema_status=proposal.schema_status)
            value = (proposal.value if proposal.transport_status == "SUCCESS"
                     and proposal.schema_status == "VALID" and schema_valid(proposal.value, structure_schema) else None)
        if value is None:
            return H0Result("UNAVAILABLE", None, proposal.payload_json, telemetry)
        try:
            program = compile_v3_structure(value)
        except StructureInvalid as error:
            telemetry["compile_error"] = str(error)
            return H0Result("INVALID", None, proposal.payload_json, telemetry)
        return H0Result("VALID", program, proposal.payload_json, telemetry)

    return frontend


# -------------------------------------------------------------- GRS frontend

def make_grs_frontend(ground_task: str, ground_schema: dict, ground_repair_task: str,
                      synth_task: str, synth_schema: dict, synth_repair_task: str,
                      backend: SemanticBackend) -> Callable[[str, tuple[str, ...]], GRSResult]:
    """The frozen GRS protocol: grounder (1+repair) -> deterministic inventory
    validation -> B1 synthesizer (1+repair) -> deterministic canonicalizer
    (structure-preserving RULE-wrapper repair only) -> frozen validator ->
    compiler into the same v3 program space."""

    def _propose(task: str, payload: dict, schema: dict, repair_task: str):
        proposal = backend.propose(task, payload, schema)
        telemetry = {"transport_status": proposal.transport_status,
                     "schema_status": proposal.schema_status, "repair_used": False}
        value = (proposal.value if proposal.transport_status == "SUCCESS"
                 and proposal.schema_status == "VALID" and schema_valid(proposal.value, schema) else None)
        if value is None:
            repair_payload = dict(payload)
            repair_payload["failed_attempt"] = {
                "transport_status": proposal.transport_status,
                "schema_status": proposal.schema_status,
                "payload_json": proposal.payload_json}
            repair_payload["machine_error"] = ("transport_error" if proposal.transport_status != "SUCCESS"
                                               else "schema_invalid")
            proposal = backend.propose(repair_task, repair_payload, schema)
            telemetry.update(repair_used=True,
                             repair_transport_status=proposal.transport_status,
                             repair_schema_status=proposal.schema_status)
            value = (proposal.value if proposal.transport_status == "SUCCESS"
                     and proposal.schema_status == "VALID" and schema_valid(proposal.value, schema) else None)
        return value, telemetry

    def frontend(policy_text: str, atom_catalog: tuple[str, ...]) -> GRSResult:
        hallucination = {"invented_ids": 0, "free_text_leaves": 0}
        ground_payload = {"policy_text": policy_text, "atom_catalog": list(atom_catalog)}
        value, telemetry = _propose(ground_task, ground_payload, ground_schema, ground_repair_task)
        if value is None:
            telemetry["stage"] = "grounder"
            return GRSResult("UNAVAILABLE", (), (), None, None, False,
                             hallucination, telemetry)
        inventory = {"facts": [
            {"id": item["id"], "kind": _fact_kind(item["atom"]), "atom": item["atom"],
             "span": item["span"]} for item in value.get("facts", ())],
            "markers": value.get("markers", ())}
        try:
            validate_inventory(inventory, policy_text)
        except GRSInvalid as error:
            telemetry["stage"] = "grounder"
            telemetry["inventory_error"] = str(error)
            return GRSResult("INVALID", (), (), None, None, False,
                             hallucination, telemetry)
        synth_payload = {"policy_text": policy_text, "inventory": inventory}
        synth_value, synth_telemetry = _propose(synth_task, synth_payload, synth_schema, synth_repair_task)
        telemetry.update({f"synth_{key}": item for key, item in synth_telemetry.items()})
        if synth_value is None:
            telemetry["stage"] = "synthesizer"
            return GRSResult("UNAVAILABLE", (), (), inventory, None, None, False,
                             hallucination, telemetry)
        dsl_text = synth_value.get("dsl", "")
        hallucination = hallucination_attempts(dsl_text, inventory)
        canonicalized = False
        try:
            alternatives, dropped = compile_dsl(dsl_text, inventory)
        except GRSInvalid:
            # One frozen structure-preserving canonicalization pass (the final-cycle
            # selected emission boundary), then the FROZEN validator again.
            try:
                repaired, _audit = canonicalize_dsl(dsl_text)
            except EmissionInvalid:
                telemetry["stage"] = "synthesizer"
                telemetry["dsl_error"] = "invalid_dsl_not_canonicalizable"
                return GRSResult("INVALID", (), (), inventory, dsl_text, False,
                             hallucination, telemetry)
            canonicalized = True
            try:
                alternatives, dropped = compile_dsl(repaired, inventory)
            except GRSInvalid as error:
                telemetry["stage"] = "synthesizer"
                telemetry["dsl_error"] = str(error)
                return GRSResult("INVALID", (), (), inventory, dsl_text, canonicalized,
                                 hallucination, telemetry)
        return GRSResult("VALID", tuple(tuple(programs) for programs in alternatives),
                         tuple(dropped), inventory, dsl_text, canonicalized,
                         hallucination, telemetry)

    def _fact_kind(atom: str) -> str:
        from ..policy_grs import KIND_OF_PREFIX
        prefix = atom.split(":", 1)[0] + ":"
        return KIND_OF_PREFIX.get(prefix, "ACTION")

    return frontend


# ------------------------------------------------------------- composition

def _reading_verdicts(programs: tuple[dict, ...], surface: list[frozenset]) -> tuple[str, ...]:
    return tuple(composed_verdict(list(programs), facts) for facts in surface)


def _equivalence_surface(readings: list[PolicyReading], atom_catalog: tuple[str, ...]) -> list[frozenset]:
    from ..policy_v3_benchmark import (_clause_fact_patterns, _literal_fact_patterns,
                                        _pattern_facts)
    programs = [program for reading in readings for program in reading.programs]
    if not programs:
        return [frozenset()] + [frozenset({atom}) for atom in sorted(set(atom_catalog))]
    combined = {
        "target_clauses": [list(clause) for program in programs for clause in program["target_clauses"]],
        "condition_literals": sorted({lit for program in programs for lit in program["condition_literals"]}),
        "exception_literals": sorted({lit for program in programs for lit in program["exception_literals"]}),
    }
    surface, seen = [], set()
    for tpat in _clause_fact_patterns(combined["target_clauses"]):
        for cpat in _literal_fact_patterns(combined["condition_literals"]):
            for epat in _literal_fact_patterns(combined["exception_literals"]):
                facts = _pattern_facts(tpat, cpat, epat)
                if facts not in seen:
                    seen.add(facts)
                    surface.append(facts)
    return surface


def compose_single_frontend(h0: H0Result | None, grs: GRSResult | None,
                            atom_catalog: tuple[str, ...]) -> PolicyComposition:
    """Single-frontend arm composition: the policy space IS the selected
    frontend's readings (spec sections 136-142); empirically complete when
    the frontend is VALID, open when it failed."""
    raw_readings: list[PolicyReading] = []
    if h0 is not None and h0.status == "VALID" and h0.program is not None:
        raw_readings.append(PolicyReading("policy:h0", "h0", (h0.program,), ()))
    if grs is not None and grs.status == "VALID":
        for index, programs in enumerate(grs.alternatives):
            raw_readings.append(PolicyReading(f"policy:grs:alt{index}", "grs", tuple(programs), ()))
    if not raw_readings:
        return PolicyComposition((), h0 or H0Result("UNAVAILABLE", None, None, {}),
                                 grs or GRSResult("UNAVAILABLE", (), (), None, None, False, {}, {}),
                                 "BOTH_INVALID", {}, "POLICY_NO_VALID_READING")
    unresolved = None
    if h0 is not None and h0.status != "VALID":
        unresolved = "POLICY_FRONTEND_UNAVAILABLE"
    if grs is not None and grs.status != "VALID":
        unresolved = unresolved or "POLICY_FRONTEND_UNAVAILABLE"
    return PolicyComposition(tuple(raw_readings),
                             h0 or H0Result("UNAVAILABLE", None, None, {}),
                             grs or GRSResult("UNAVAILABLE", (), (), None, None, False, {}, {}),
                             "SINGLE", {}, unresolved)


def compose_policy_readings(h0: H0Result, grs: GRSResult,
                            atom_catalog: tuple[str, ...]) -> PolicyComposition:
    """Deterministic composition (spec sections 51-53): dedupe behavioral
    duplicates over the combined distinguishing surface; retain material
    disagreements; one-invalid keeps the valid reading with OPEN coverage."""
    raw_readings: list[PolicyReading] = []
    if h0.status == "VALID" and h0.program is not None:
        raw_readings.append(PolicyReading("policy:h0", "h0", (h0.program,), ()))
    for index, programs in enumerate(grs.alternatives if grs.status == "VALID" else ()):
        raw_readings.append(PolicyReading(f"policy:grs:alt{index}", "grs", tuple(programs), ()))

    if not raw_readings:
        agreement = "BOTH_INVALID" if (h0.status != "VALID" and grs.status != "VALID") else "ONE_INVALID"
        return PolicyComposition((), h0, grs, agreement,
                                 {"h0_status": h0.status, "grs_status": grs.status},
                                 "POLICY_NO_VALID_READING")

    surface = _equivalence_surface(raw_readings, atom_catalog)
    kept: list[PolicyReading] = []
    for reading in raw_readings:
        verdicts = _reading_verdicts(reading.programs, surface)
        duplicate = None
        for existing in kept:
            if verdicts == _reading_verdicts(existing.programs, surface):
                duplicate = existing
                break
        if duplicate is not None:
            kept = [PolicyReading(existing.reading_id, existing.frontend, existing.programs,
                                  (*existing.equivalent_to, reading.reading_id))
                    if existing.reading_id == duplicate.reading_id else existing for existing in kept]
        else:
            kept.append(reading)

    h0_valid = h0.status == "VALID"
    grs_valid = grs.status == "VALID"
    if h0_valid and grs_valid:
        agreement = "EQUIVALENT" if len(kept) == 1 else "DIFFERENT"
    else:
        agreement = "ONE_INVALID"
    unresolved = None
    if agreement == "ONE_INVALID":
        # Section 52: keep the valid reading but semantic coverage stays OPEN.
        unresolved = "POLICY_SEMANTIC_COVERAGE_OPEN_ONE_FRONTEND_INVALID"
    return PolicyComposition(tuple(kept), h0, grs, agreement,
                             {"surface_worlds": len(surface), "raw_readings": len(raw_readings)},
                             unresolved)
