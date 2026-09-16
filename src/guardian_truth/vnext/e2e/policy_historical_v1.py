"""Historical Policy frontends (cycle 3, B4): byte-exact reuse of the frozen
E2E-agent-1 H0/GRS components with a representation-only adapter into the
E2E-agent-2 reading space.

What is frozen and byte-identical (provenance recorded in HISTORICAL_PROVENANCE):
* H0 protocol: PARSE_TASK / REPAIR_TASK / STRUCTURE_SCHEMA / CONFIG from
  scripts/evaluate_vnext_c_alr_reimpl.py (the C-ALR frozen H0 source), plus
  the frozen one-parse + one-machine-validation-repair protocol and the
  historical v3 compiler (policy_v3_benchmark.compile_v3_structure).
* GRS protocol: grounder + frozen B1 synthesizer + canonicalizer
  (policy_grs.canonicalize_dsl via the e2e wrapper) + frozen DSL
  validator/compiler (policy_grs.compile_dsl) into the same shared v3
  program space.

What is adapted (representation only, semantics preserved):
* v3 programs (fact-space verdict programs) are converted into the Agent-2
  PolicyFlatStructure representation and compiled by Agent-2's own
  deterministic compiler (policy_composition_v1.compile_h0) into Agent-2's
  CompiledRule program space. The mapping is field-by-field and loses no
  modality/relation/gate information; v3 relations without an Agent-2
  equivalent (IF_AND_ONLY_IF -> ONLY_IF conservatively, AND_NOT_EACH ->
  unresolved) are recorded explicitly.
* The atom catalog is constructed deterministically from case metadata
  (action:<tool> for every catalog tool, state:<field> for state-contract and
  T1-write fields, fixed distractors) - the same construction style the
  historical corpus used, never from policy text parsing.
* Atom keys are made textually groundable through an explicit machine suffix
  (POLICY_ATOM_CATALOG=...) appended to the policy normative text - the same
  mechanism the goal axis uses for EXPLICIT_ALLOWED_SCOPE literals.

The world semantics, solver, checker and composition machinery are Agent-2's
frozen E2E V1 (the Agent-1 global-UNKNOWN world composition is NOT ported).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from ..integrity import canonical, digest
from ..semantic import SemanticBackend, schema_valid
from .e2e_types_v1 import FrontendCandidate, PolicyFlatStructure, PolicyReading, SemanticLiteral
from .policy_composition_v1 import compile_h0

# ---- frozen historical sources (byte-identical ports from E2E-agent-1) ----
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from guardian_truth.vnext import policy_grs as _grs  # noqa: E402
from guardian_truth.vnext import policy_v3_benchmark as _v3  # noqa: E402
from guardian_truth.vnext.e2e.policy_grs_emission_e2e_v1 import canonicalize_dsl_e2e  # noqa: E402

import scripts.evaluate_vnext_c_alr_reimpl as _c_alr  # noqa: E402

PARSE_TASK = _c_alr.PARSE_TASK
REPAIR_TASK = _c_alr.REPAIR_TASK
STRUCTURE_SCHEMA = _c_alr.STRUCTURE_SCHEMA
CONFIG = _c_alr.CONFIG
GRS_GROUND_TASK = _grs.GRS_GROUND_TASK
GRS_GROUND_REPAIR_TASK = _grs.GRS_GROUND_REPAIR_TASK
GRS_GROUND_SCHEMA = _grs.GRS_GROUND_SCHEMA
GRS_SYNTH_TASK = _grs.GRS_SYNTH_TASK
GRS_SYNTH_REPAIR_TASK = _grs.GRS_SYNTH_REPAIR_TASK
GRS_DSL_SCHEMA = _grs.GRS_DSL_SCHEMA

HISTORICAL_PROVENANCE = {
    "source_branch": "origin/E2E-agent-1",
    "source_commit": "998a756a4a2bdcd1e11c37838eb2a69d59e11f9b",
    "h0_source_file": "scripts/evaluate_vnext_c_alr_reimpl.py",
    "h0_parse_task_sha256": digest(PARSE_TASK),
    "h0_repair_task_sha256": digest(REPAIR_TASK),
    "h0_structure_schema_sha256": digest(STRUCTURE_SCHEMA),
    "h0_config": {key: CONFIG[key] for key in
                  ("provider", "model", "temperature", "max_requests_per_case_h0",
                   "response_format_mode", "random_seed")},
    "grs_source_files": ["src/guardian_truth/vnext/policy_grs.py",
                         "src/guardian_truth/vnext/policy_grs_emission.py",
                         "src/guardian_truth/vnext/e2e/policy_grs_emission_e2e_v1.py"],
    "grs_ground_task_sha256": digest(GRS_GROUND_TASK),
    "grs_ground_repair_task_sha256": digest(GRS_GROUND_REPAIR_TASK),
    "grs_ground_schema_sha256": digest(GRS_GROUND_SCHEMA),
    "grs_synth_task_sha256": digest(GRS_SYNTH_TASK),
    "grs_synth_repair_task_sha256": digest(GRS_SYNTH_REPAIR_TASK),
    "grs_dsl_schema_sha256": digest(GRS_DSL_SCHEMA),
    "shared_program_space": "policy_v3_benchmark.compile_v3_structure / compile_dsl (v3)",
    "adapter": "representation-only: v3 program -> PolicyFlatStructure -> compile_h0",
    "world_semantics": "E2E-agent-2 frozen E2E V1 (Agent-1 global-UNKNOWN composition NOT ported)",
}

ATOM_CATALOG_SUFFIX = "\nPOLICY_ATOM_CATALOG="


# --------------------------------------------------------------- H0 frontend

@dataclass(frozen=True)
class HistoricalH0Result:
    candidate: FrontendCandidate
    program: dict | None


def _propose_with_repair(task: str, repair_task: str, payload: dict, schema: dict,
                         backend: SemanticBackend):
    """Frozen protocol step: one primary proposal; exactly one
    machine-validation repair re-ask on transport/schema failure only. A
    schema-valid but semantically wrong answer is NEVER retried."""
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


def historical_h0(policy_text: str, atom_catalog: tuple[str, ...],
                   backend: SemanticBackend) -> HistoricalH0Result:
    """The frozen H0 frontend: parse (policy_text, atom_catalog) under the
    frozen task/schema, one machine-validation repair, compile via the frozen
    v3 compiler."""
    if not policy_text.strip():
        return HistoricalH0Result(FrontendCandidate("h0_hist", True, None), None)
    payload = {"policy_text": policy_text, "atom_catalog": list(atom_catalog)}
    value, telemetry = _propose_with_repair(PARSE_TASK, REPAIR_TASK, payload,
                                             STRUCTURE_SCHEMA, backend)
    if value is None:
        failure = "TRANSPORT" if telemetry.get("repair_transport_status") != "SUCCESS" else "SCHEMA"
        return HistoricalH0Result(FrontendCandidate("h0_hist", False, failure), None)
    try:
        program = _v3.compile_v3_structure(value)
    except _v3.StructureInvalid as error:
        return HistoricalH0Result(FrontendCandidate("h0_hist", False, "COMPILE", str(error)), None)
    return HistoricalH0Result(FrontendCandidate("h0_hist", True, None), program)


# --------------------------------------------------------------- GRS frontend

@dataclass(frozen=True)
class HistoricalGrsResult:
    candidate: FrontendCandidate
    alternatives: tuple[tuple[dict, ...], ...]      # each: list of v3 programs
    dropped_rules: tuple[dict, ...]
    inventory: dict | None
    dsl_text: str | None
    canonicalized: bool


def historical_grs(policy_text: str, atom_catalog: tuple[str, ...],
                   backend: SemanticBackend) -> HistoricalGrsResult:
    """The frozen GRS frontend: grounder (1+repair) -> deterministic inventory
    validation -> B1 synthesizer (1+repair) -> canonicalizer fallback ->
    frozen DSL validator/compiler into the shared v3 program space."""
    empty = HistoricalGrsResult(FrontendCandidate("grs_hist", True, None), (), (), None, None, False)
    if not policy_text.strip():
        return empty
    hallucination = {"invented_ids": 0, "free_text_leaves": 0}
    ground_payload = {"policy_text": policy_text, "atom_catalog": list(atom_catalog)}
    value, telemetry = _propose_with_repair(GRS_GROUND_TASK, GRS_GROUND_REPAIR_TASK,
                                             ground_payload, GRS_GROUND_SCHEMA, backend)
    if value is None:
        failure = "TRANSPORT" if telemetry.get("repair_transport_status") != "SUCCESS" else "SCHEMA"
        return HistoricalGrsResult(FrontendCandidate("grs_hist", False, failure), (), (), None, None, False)
    inventory = {"facts": [
        {"id": item["id"], "kind": _fact_kind(item["atom"]), "atom": item["atom"],
         "span": item["span"]} for item in value.get("facts", ())],
        "markers": value.get("markers", ())}
    try:
        _grs.validate_inventory(inventory, policy_text)
    except _grs.GRSInvalid as error:
        return HistoricalGrsResult(FrontendCandidate("grs_hist", False, "COMPILE", str(error)),
                                    (), (), None, None, False)
    synth_payload = {"policy_text": policy_text, "inventory": inventory}
    synth_value, synth_telemetry = _propose_with_repair(GRS_SYNTH_TASK, GRS_SYNTH_REPAIR_TASK,
                                                        synth_payload, GRS_DSL_SCHEMA, backend)
    if synth_value is None:
        failure = "TRANSPORT" if synth_telemetry.get("repair_transport_status") != "SUCCESS" else "SCHEMA"
        return HistoricalGrsResult(FrontendCandidate("grs_hist", False, failure), (), (),
                                    inventory, None, False)
    dsl_text = synth_value.get("dsl", "")
    hallucination = _grs.hallucination_attempts(dsl_text, inventory)
    canonicalized = False
    try:
        alternatives, dropped = _grs.compile_dsl(dsl_text, inventory)
    except _grs.GRSInvalid:
        try:
            repaired, _audit = canonicalize_dsl_e2e(dsl_text)
        except Exception:
            return HistoricalGrsResult(FrontendCandidate("grs_hist", False, "COMPILE",
                                                         "invalid_dsl_not_canonicalizable"),
                                        (), (), inventory, dsl_text, False)
        canonicalized = True
        try:
            alternatives, dropped = _grs.compile_dsl(repaired, inventory)
        except _grs.GRSInvalid as error:
            return HistoricalGrsResult(FrontendCandidate("grs_hist", False, "COMPILE", str(error)),
                                        (), (), inventory, dsl_text, canonicalized)
    return HistoricalGrsResult(FrontendCandidate("grs_hist", True, None),
                                tuple(tuple(programs) for programs in alternatives),
                                tuple(dropped), inventory, dsl_text, canonicalized)


def _fact_kind(atom: str) -> str:
    prefix = atom.split(":", 1)[0] + ":"
    return _grs.KIND_OF_PREFIX.get(prefix, "ACTION")


# ------------------------------------------------- representation adapter

_ATOM_KIND_MAP = {"action": "ACTION", "state": "STATE", "event": "EFFECT",
                  "actor": "ACTOR", "identity": "ENTITY", "evidence": "EVIDENCE",
                  "distractor": "ACTION"}
_RELATION_MAP = {"IF": "IF", "ONLY_IF": "ONLY_IF", "UNLESS": "UNLESS",
                 "UNCONDITIONAL": "NONE", "IF_AND_ONLY_IF": "ONLY_IF",
                 "AND_NOT_EACH": "UNKNOWN", "BEFORE": "BEFORE", "AFTER": "AFTER",
                 "NONE": "NONE"}


def _literal_of(atom: str, extended_text: str) -> SemanticLiteral | None:
    """One catalog atom -> typed literal. The quote is the atom key grounded
    in the extended normative text (catalog suffix / state-contract suffix /
    verbatim policy text). Ungroundable atoms return None (rule unresolved)."""
    negated = atom.startswith("!")
    base = atom[1:] if negated else atom
    parts = base.split(":", 1)
    key = parts[1] if len(parts) == 2 else base
    kind = _ATOM_KIND_MAP.get(parts[0], "ACTION") if len(parts) == 2 else "ACTION"
    if not key or key not in extended_text:
        return None
    return SemanticLiteral(kind, "NEGATED" if negated else "POSITIVE", key, key)


def _degenerate_gated_program(program: dict) -> bool:
    """A gated relation (IF / ONLY_IF / UNLESS) with NO gate literals at all:
    the frozen frontend saw a gate it could not express in the atom catalog
    (policy conditions over values or uncatalogued states) and degraded the
    reading to an unconditional prohibition. Lowering such a program as an
    unconditional rule would manufacture violations the policy never states;
    the adapter abstains (no reading, frontend failure recorded)."""
    return (program.get("relation") in {"IF", "ONLY_IF", "UNLESS"}
            and not program.get("condition_literals")
            and not program.get("exception_literals"))


def _preservation_flat_structure(state_contract: dict, action_tool: str | None,
                                 extended_text: str) -> PolicyFlatStructure | None:
    """Trusted-preservation alternative reading for a PROHIBITION over a
    mutating action when the case carries a state contract: FORBID(modify F)
    with trusted field values compiles to REQUIRE(F preserved) bound to the
    SAME action tool the frozen program named - the incumbent Agent-2 H0
    lowering of the same policy shape. Retained as a SEPARATE reading
    (material disagreement between the frozen v3 program space, which has no
    value literals, and the trusted state contract; never a winner selection)."""
    literals = []
    for field_name in sorted(state_contract):
        if not field_name or field_name not in extended_text:
            continue
        if action_tool and action_tool in extended_text:
            literals.append(SemanticLiteral("ACTION", "POSITIVE", action_tool, field_name))
        else:
            literals.append(SemanticLiteral("STATE", "POSITIVE", field_name, field_name))
    if not literals:
        return None
    return PolicyFlatStructure(
        modality="PROHIBITION", actor="assistant", regulated_kind="STATE", facet="PRIMARY",
        relation="UNCONDITIONAL", target_clauses=tuple(literals),
        condition_literals=(), exception_literals=(), condition_mode="ALL", exception_mode="ALL",
        quantification="ALL", source_quotes=tuple(literal.quote for literal in literals),
        unresolved_terms=())


def program_to_flat_structure(program: dict, extended_text: str,
                              extra_unresolved: tuple[str, ...] = ()) -> PolicyFlatStructure | None:
    """v3 program -> Agent-2 PolicyFlatStructure (representation adapter).

    Field-by-field; IF_AND_ONLY_IF maps to ONLY_IF (conservative violation
    direction preserved); AND_NOT_EACH is not expressible and becomes an
    unresolved term (never a silent semantic rewrite)."""
    relation = _RELATION_MAP.get(program.get("relation", "UNCONDITIONAL"), "UNKNOWN")
    unresolved = list(extra_unresolved)
    if program.get("relation") == "AND_NOT_EACH":
        unresolved.append("h0_hist:and-not-each cardinality not expressible in V1")
    if program.get("relation") == "IF_AND_ONLY_IF":
        unresolved.append("h0_hist:if-and-only-if lowered to only-if (conservative direction)")
    targets, conditions, exceptions = [], [], []
    state_target_fields = []
    grounded_quotes = []
    for clause in program.get("target_clauses", ()):
        for atom in clause:
            literal = _literal_of(atom, extended_text)
            if literal is None:
                unresolved.append(f"h0_hist:ungroundable target atom {atom}")
                continue
            grounded_quotes.append(literal.quote)
            if literal.kind == "STATE" and not atom.startswith("!"):
                # A PROHIBITION over a state atom is a field-modification
                # prohibition: absorb it into the action literals' quotes so
                # the incumbent REQUIRE_PRESERVE lowering fires on the bound
                # tool (separate standalone state rules cannot bind to a tool
                # and would only manufacture binding-unknown markers).
                state_target_fields.append(literal.normalized_key or literal.quote)
                continue
            targets.append(literal)
    if state_target_fields and targets:
        merged = []
        for literal in targets:
            quote = literal.quote + " " + " ".join(sorted(set(state_target_fields)))
            merged.append(SemanticLiteral(literal.kind, literal.polarity, literal.normalized_key, quote))
        targets = merged
    elif state_target_fields:
        for field_name in sorted(set(state_target_fields)):
            targets.append(SemanticLiteral("STATE", "POSITIVE", field_name, field_name))
    for atom in program.get("condition_literals", ()):
        literal = _literal_of(atom, extended_text)
        if literal is None:
            unresolved.append(f"h0_hist:ungroundable condition atom {atom}")
            continue
        conditions.append(literal)
    for atom in program.get("exception_literals", ()):
        literal = _literal_of(atom, extended_text)
        if literal is None:
            unresolved.append(f"h0_hist:ungroundable exception atom {atom}")
            continue
        exceptions.append(literal)
    if not targets:
        return None
    modality = program.get("modality", "UNKNOWN")
    if modality not in {"PERMISSION", "PROHIBITION", "REQUIREMENT"}:
        unresolved.append("h0_hist:unknown modality")
    actor = program.get("actor") or "assistant"
    quotes = tuple(dict.fromkeys(grounded_quotes
                                 + [literal.quote for literal in (*targets, *conditions, *exceptions)]))
    return PolicyFlatStructure(
        modality=modality if modality in {"PERMISSION", "PROHIBITION", "REQUIREMENT"} else "UNKNOWN",
        actor=actor if isinstance(actor, str) and actor else "UNKNOWN",
        regulated_kind=program.get("regulated_kind", "ACTION") or "ACTION",
        facet=(program.get("facet") or "primary").upper(),
        relation=relation,
        target_clauses=tuple(sorted(targets, key=lambda c: (c.kind, c.polarity, c.normalized_key or "", c.quote))),
        condition_literals=tuple(sorted(conditions, key=lambda c: (c.kind, c.polarity, c.normalized_key or "", c.quote))),
        exception_literals=tuple(sorted(exceptions, key=lambda c: (c.kind, c.polarity, c.normalized_key or "", c.quote))),
        condition_mode=program.get("condition_mode", "ALL"),
        exception_mode=program.get("exception_mode", "ALL"),
        quantification=program.get("quantification", "ALL"),
        source_quotes=quotes,
        unresolved_terms=tuple(dict.fromkeys(unresolved)))


def atom_catalog_for(case, catalog_tools: tuple[str, ...]) -> tuple[str, ...]:
    """Deterministic atom catalog from case metadata only (never from parsing
    the policy text): action:<tool> for every catalog tool, state:<field> for
    trusted state-contract fields and T1 write predicates, plus fixed
    distractors, mirroring the historical corpus catalog construction."""
    atoms = [f"action:{tool}" for tool in sorted(set(catalog_tools))]
    state_fields = set()
    state_contract = case.state_contract or {}
    state_fields.update(state_contract.keys())
    for contract in case.t1_contracts:
        for field_name in contract.get("writes", ()):
            state_fields.add(field_name)
    atoms.extend(f"state:{field}" for field in sorted(state_fields))
    atoms.append("distractor:unused_action")
    atoms.append("distractor:unused_state")
    return tuple(dict.fromkeys(atoms))


def extended_policy_text(policy_text: str, atom_catalog: tuple[str, ...],
                          state_contract: dict | None = None) -> str:
    """Policy normative text + explicit machine suffixes, so every atom key
    AND every trusted state-contract literal is textually groundable for the
    operational binding and the certificate grounding (the same mechanism as
    the incumbent's POLICY_STATE_CONSTRAINTS and the goal axis's
    EXPLICIT_ALLOWED_SCOPE)."""
    from .source_adapter_v1 import POLICY_SCOPE_SUFFIX
    text_value = policy_text
    if state_contract:
        text_value = text_value + POLICY_SCOPE_SUFFIX + canonical(
            dict(sorted(state_contract.items()))).decode("utf-8")
    return text_value + ATOM_CATALOG_SUFFIX + canonical(sorted(atom_catalog)).decode("utf-8")


def historical_readings(case, state_contract: dict | None, catalog_tools: tuple[str, ...],
                        policy_text: str, backend: SemanticBackend,
                        frontends: tuple[str, ...]):
    """Run the frozen historical frontends and adapt them into Agent-2
    PolicyReadings. Returns (readings, failures, extended_text)."""
    failures = []
    if not policy_text.strip():
        return (), (), policy_text
    catalog = atom_catalog_for(case, catalog_tools)
    extended = extended_policy_text(policy_text, catalog, state_contract)
    readings = []
    if "h0_hist" in frontends:
        h0 = historical_h0(policy_text, catalog, backend)
        if h0.candidate.available and h0.program is not None:
            if _degenerate_gated_program(h0.program):
                failures.append(("policy_h0_hist", "COMPILE",
                                 "gated policy degraded to unconditional (gate not expressible "
                                 "in the v3 atom catalog); abstaining"))
            else:
                flat = program_to_flat_structure(h0.program, extended)
                if flat is not None:
                    readings.append(compile_h0(flat, state_contract, catalog_tools))
                    action_targets = [atom for clause in h0.program.get("target_clauses", ())
                                      for atom in clause
                                      if atom.startswith("action:") and not atom.startswith("!")]
                    if (h0.program.get("modality") == "PROHIBITION"
                            and state_contract and action_targets):
                        # Retain the trusted-preservation alternative reading as
                        # a SEPARATE interpretation (never a winner selection):
                        # the v3 program space has no value literals, so
                        # FORBID(modify F) also admits REQUIRE(F preserved).
                        action_tool = action_targets[0].split(":", 1)[1]
                        preserve = _preservation_flat_structure(state_contract, action_tool, extended)
                        if preserve is not None:
                            readings.append(compile_h0(preserve, state_contract, catalog_tools,
                                                       reading_id="policy:h0:r0:preserve"))
                else:
                    failures.append(("policy_h0_hist", "COMPILE", "no groundable target atom"))
        elif not h0.candidate.available:
            failures.append(("policy_h0_hist", h0.candidate.failure, h0.candidate.detail))
    if "grs_hist" in frontends:
        grs = historical_grs(policy_text, catalog, backend)
        if grs.candidate.available and grs.alternatives:
            for index, programs in enumerate(grs.alternatives):
                rules, unresolved = [], []
                for program in programs:
                    if _degenerate_gated_program(program):
                        unresolved.append("grs_hist:degenerate gated program (gate not expressible)")
                        continue
                    flat = program_to_flat_structure(program, extended)
                    if flat is None:
                        unresolved.append("grs_hist:uncompilable program in alternative")
                        continue
                    reading = compile_h0(flat, state_contract, catalog_tools)
                    rules.extend(reading.rules)
                    unresolved.extend(reading.unresolved_terms)
                for dropped in grs.dropped_rules:
                    unresolved.append("grs_hist:dropped rule: " + str(dropped.get("reason")))
                readings.append(PolicyReading(f"policy:grs_hist:r{index}", "grs_hist",
                                               tuple(rules), tuple(dict.fromkeys(unresolved))))
        elif not grs.candidate.available:
            failures.append(("policy_grs_hist", grs.candidate.failure, grs.candidate.detail))
    return tuple(readings), tuple(failures), extended
