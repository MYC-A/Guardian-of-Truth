"""E2E V1 entry point: GuardianE2EV1.analyze_e2e_v1 (spec 109, 110).

Explicit dependency injection: semantic backend, T1 registry, arm
configuration (which policy/goal frontends populate the interpretation axes),
world budget, adapter mode, and optional oracle substitutions. No hidden API
client, no hidden global semantic state. The baseline entry point
(`vnext.core.analyze`) remains untouched and runnable (B0).

Pipeline:
  source adapter (TEXT_VIEW/ACTION_VIEW, firewall goal source)
  -> ledger -> T1/T2 effects
  -> claim graph (TEXT_VIEW only)
  -> policy frontends (H0 / GRS per arm) -> readings -> dedupe
  -> goal frontends (Conservative / RuleFrames+E5 per arm) -> contracts -> dedupe
  -> PASS 2 lowering (operational grounding, prerequisites, preservation)
  -> axes (policy, goal, claims, T2 effects) -> exact Cartesian worlds
  -> per-world local verdicts -> all-world aggregation
  -> certificate -> independent checker -> adapter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

from ..adapters import AdapterMode, ProductDecision, adapt
from ..binder import bind_claim
from ..certificates import AuthoritativeAxis, CertificateContext
from ..claims import build_claim_graph
from ..decision import CertifiedCoreResult
from ..integrity import canonical, digest
from ..ledger import EvidenceLedger, LedgerIndex
from ..proof_records import AtomKind, InterpretationAxis, Reason
from ..semantic import SemanticBackend
from ..tools import ContractRegistry, ToolSemantics, evaluate_t1, propose_t2
from ..types import CoreStatus, Disposition, EffectStatus
from .certificate_context_v1 import E2EBundle, check_e2e_certificate, e2e_completeness_assumptions, make_e2e_certificate
from .claim_adapter_v1 import build_claims, claim_obligation_ids
from .e2e_types_v1 import E2EArmConfig, E2ECaseInput, E2ESemantics, FULL_SEMANTICS, PolicyReading, ReadingOption, UnresolvedMarker
from .goal_composition_v1 import compile_goal_contract, conservative_frames_to_contract
from .goal_conservative_v1 import parse_conservative
from .goal_lowering_v1 import goal_normative_text, lower_goal_contract, merged_scope
from .goal_rule_frames_v1 import (contract_canonical_key, contract_from_rows, dedupe_contracts,
                                  make_contract, parse_rule_frames)
from .policy_composition_v1 import (compile_grs, compile_h0, dedupe_readings, reading_canonical_key,
                                     reading_from_rows)
from .policy_grs_grounder_v1 import ground_inventory
from .policy_grs_synth_v1 import synthesize
from .policy_h0_v1 import parse_h0
from .policy_historical_v1 import historical_readings
from .policy_lowering_v1 import lower_reading
from .source_adapter_v1 import build_source, target_calls, tool_catalog
from .world_integration_v1 import Component, E2EProblem, build_worlds, make_problem, solve_e2e

CORE_V1_VERSION = "guardian_e2e_v1"


@dataclass
class E2EAnalysis:
    case_id: str
    arm_id: str
    result: CertifiedCoreResult
    product_decision: ProductDecision
    ledger: EvidenceLedger
    problem: E2EProblem
    bundle: E2EBundle
    policy_readings: tuple
    goal_contracts: tuple
    frontend_statuses: tuple                      # (component, kind, detail)
    required_worlds: int
    world_count: int
    component_summary: dict = field(default_factory=dict)
    policy_lowered: tuple = ()                    # LoweredReading records (debug/audit)
    goal_lowered: tuple = ()


class GuardianE2EV1:
    """Explicit-dependency E2E V1 guardian. Arms E0-E4 select frontends."""

    def __init__(self, backend: SemanticBackend, *, registry: ContractRegistry | None = None,
                 arm: E2EArmConfig | None = None, max_worlds: int = 4096,
                 adapter_mode: AdapterMode = AdapterMode.AUDIT, enable_t2: bool = True,
                 oracle_policy: bool = False, oracle_goal: bool = False,
                 semantics: E2ESemantics | None = None):
        if type(max_worlds) is not int or max_worlds < 1:
            raise ValueError("positive material-world computation budget required")
        self.backend = backend
        self.registry = registry if registry is not None else ContractRegistry(())
        self.arm = arm if arm is not None else E2EArmConfig("E0", ("h0",), ("conservative",))
        self.max_worlds = max_worlds
        self.adapter_mode = adapter_mode
        self.enable_t2 = enable_t2
        self.oracle_policy = oracle_policy
        self.oracle_goal = oracle_goal
        # None = latest full cycle-3 semantics; the ablation arms inject the
        # frozen B0..B4 gates explicitly (SEMANTICS_ARMS).
        self.semantics = semantics if semantics is not None else FULL_SEMANTICS

    # ------------------------------------------------------------- analysis

    def analyze_e2e_v1(self, case: E2ECaseInput) -> E2EAnalysis:
        source = build_source(case)
        ledger = EvidenceLedger.from_events(source.events,
                                            history_complete=bool(case.history_complete),
                                            completeness_basis=case.completeness_basis)
        registry, catalog = self.registry, tool_catalog(source)
        calls = target_calls(source)
        semantics, effects = [], []
        schemas = {schema["name"]: schema for schema in source.tool_schemas
                   if isinstance(schema.get("name"), str)}
        index = LedgerIndex(ledger)
        for result_event in ledger.events:
            if result_event.kind != "result" or not result_event.call_id:
                continue
            matching = [event for event in index.events_by_call.get(result_event.call_id, ())
                        if event.kind == "call"]
            if len(matching) != 1:
                continue
            call_event = matching[0]
            value = evaluate_t1(registry, call_event, result_event)
            if self.enable_t2 and call_event.tool and registry.lookup(call_event.tool) is None:
                value = propose_t2(call_event, result_event, self.backend,
                                   schema=schemas.get(call_event.tool.name, {}))
            effects.extend(value.effects)
            semantics.append((result_event.event_id, value))
        ledger = replace(ledger, effects=tuple(effects))
        index = LedgerIndex(ledger)

        claims = build_claims(source.response, self.backend, ledger, self.semantics)
        state_contract = case.state_contract or {}

        # ---- PASS 1: frontends (trajectory-free) ----
        readings, policy_failures, effective_policy_text = self._policy_readings(case, state_contract, catalog)
        contracts, goal_failures = self._goal_contracts(case)
        frontend_statuses = tuple(policy_failures) + tuple(goal_failures)

        # ---- PASS 2: lowering with trajectory binding ----
        policy_lowered = tuple(lower_reading(reading, frontend="policy",
                                             normative_text=effective_policy_text,
                                             backend=self.backend, ledger=ledger,
                                             tool_catalog=catalog, target_calls=calls)
                               for reading in readings)
        union_goal_scope = {}
        for contract in contracts:
            contract_rules, _ = compile_goal_contract(contract, state_contract)
            for rule_field, values in merged_scope(contract_rules).items():
                union_goal_scope.setdefault(rule_field, [])
                for value in values:
                    if value not in union_goal_scope[rule_field]:
                        union_goal_scope[rule_field].append(value)
        goal_text = case.user_request
        if union_goal_scope:
            goal_text = goal_text + "\nEXPLICIT_ALLOWED_SCOPE=" + canonical(dict(sorted(union_goal_scope.items()))).decode("utf-8")
        lowered_goal_contracts = []
        for contract in contracts:
            lowered = lower_goal_contract(contract, user_request=case.user_request,
                                          state_contract=state_contract, backend=self.backend,
                                          ledger=ledger, tool_catalog=catalog, target_calls=calls,
                                          normative_text=goal_text, semantics=self.semantics)
            lowered_goal_contracts.append(lowered)

        # ---- axes ----
        components, option_contracts, choice_rules, direct_rules = [], {}, {}, {}
        authorities = []
        policy_axis_present = bool(case.system_policy.strip())
        goal_axis_present = bool(case.user_request.strip())
        if policy_axis_present:
            options = {}
            for lowered in policy_lowered:
                for option in lowered.options:
                    options[option.option_id] = option
                    option_contracts[option.option_id] = lowered.option_contracts.get(option.option_id, {"rules": {}})
                    choice_rules.update(lowered.choice_rules)
                    direct_rules.update(lowered.direct_rules)
            if not options:
                options["policy:unresolved"] = ReadingOption(
                    "policy:unresolved", (), (),
                    (UnresolvedMarker("policy:unresolved", "no policy reading available"),))
                option_contracts["policy:unresolved"] = {"rules": {}}
            complete = bool(readings) and not policy_failures
            closure = _behavioral_closure(case.authoritative_policy_behaviors, policy_lowered)
            if complete and closure["closed"]:
                universe_source = "authoritative semantic closure:" + digest(closure.get("auth_sample", ()))
                basis = "AUTHORITATIVE_CLOSED_UNIVERSE"
            elif complete:
                universe_source = "grounded finite semantic candidates:" + digest(
                    {"options": sorted(options)})
                basis = "EMPIRICAL_CANDIDATE_SET"
            else:
                universe_source, basis = None, "EMPIRICAL_CANDIDATE_SET"
            components.append(Component(InterpretationAxis("policy", tuple(options), universe_source, complete), options))
            authorities.append(AuthoritativeAxis("policy", tuple(options),
                                                universe_source or "unresolved", basis))
        else:
            components.append(_absence_component("policy"))
            authorities.append(_absence_authority("policy"))
        if goal_axis_present:
            options = {}
            for lowered in lowered_goal_contracts:
                for option in lowered.options:
                    options[option.option_id] = option
                    option_contracts[option.option_id] = lowered.option_contracts.get(option.option_id, {"rules": {}})
                    choice_rules.update(lowered.choice_rules)
                    direct_rules.update(lowered.direct_rules)
            if not options:
                options["goal:unresolved"] = ReadingOption(
                    "goal:unresolved", (), (),
                    (UnresolvedMarker("goal:unresolved", "no goal contract available"),))
                option_contracts["goal:unresolved"] = {"rules": {}}
            complete = bool(contracts) and not goal_failures
            closure = _behavioral_closure(case.authoritative_goal_behaviors, lowered_goal_contracts)
            if complete and closure["closed"]:
                universe_source = "authoritative semantic closure:" + digest(closure.get("auth_sample", ()))
                basis = "AUTHORITATIVE_CLOSED_UNIVERSE"
            elif complete:
                universe_source = "grounded finite semantic candidates:" + digest(
                    {"options": sorted(options)})
                basis = "EMPIRICAL_CANDIDATE_SET"
            else:
                universe_source, basis = None, "EMPIRICAL_CANDIDATE_SET"
            components.append(Component(InterpretationAxis("goal", tuple(options), universe_source, complete), options))
            authorities.append(AuthoritativeAxis("goal", tuple(options),
                                                universe_source or "unresolved", basis))
        else:
            components.append(_absence_component("goal"))
            authorities.append(_absence_authority("goal"))
        for component in claims.components:
            components.append(component)
            authorities.append(AuthoritativeAxis(component.axis.name, component.axis.choice_ids,
                                                 component.axis.universe_source or "unresolved",
                                                 "EXPLICIT_SOURCE_IDENTITY"))
            for choice_id, option in component.options.items():
                option_contracts[choice_id] = {"rules": {},
                                               "claim_obligations": [ob.obligation_id for ob in option.obligations]}
        for event_id, value in semantics:
            if not value.effects:
                continue
            alternatives = tuple(effect.effect_id for effect in value.effects if not effect.contract_sha256)
            if alternatives:
                name = "effect:" + event_id
                options = {cid: ReadingOption(cid, (), (), ()) for cid in alternatives}
                components.append(Component(InterpretationAxis(name, alternatives,
                                                                "nontrusted grounded T2 candidates:" + event_id, True),
                                            options))
                authorities.append(AuthoritativeAxis(name, alternatives,
                                                     "nontrusted grounded T2 candidates:" + event_id,
                                                     "EMPIRICAL_CANDIDATE_SET"))
                for cid in alternatives:
                    option_contracts[cid] = {"rules": {}}

        # ---- claim option contracts (per option) ----

        worlds, required, budget_exceeded = build_worlds(tuple(components), max_worlds=self.max_worlds)
        problem = make_problem(tuple(components), worlds)

        hypotheses = tuple(hyp for lowered in (*policy_lowered, *lowered_goal_contracts) for hyp in lowered.hypotheses)
        choices = tuple(choice for lowered in (*policy_lowered, *lowered_goal_contracts) for choice in lowered.choices)
        scopes_json = []
        for lowered in (*policy_lowered, *lowered_goal_contracts):
            for hypothesis_id, scope in lowered.hypothesis_scopes.items():
                scopes_json.append((hypothesis_id, canonical(scope).decode("utf-8")))
        context = CertificateContext(source.prompt, source.response, source.tool_metadata,
                                     claims.graph.claims, tuple(authorities), hypotheses,
                                     effective_policy_text, goal_text, choices, catalog,
                                     tuple(dict.fromkeys(scopes_json)))
        bundle = E2EBundle(context, problem, option_contracts, choice_rules, direct_rules,
                           _behavioral_closure(case.authoritative_policy_behaviors, policy_lowered),
                           _behavioral_closure(case.authoritative_goal_behaviors, lowered_goal_contracts),
                           tuple(frontend_statuses), semantics=self.semantics)
        solver_result = solve_e2e(problem, ledger, registry, self.semantics)
        status = solver_result.status
        missing_evidence = []
        if budget_exceeded:
            missing_evidence.append(f"WORLD_BUDGET_EXCEEDED:{required}>{self.max_worlds}")
        certificate = make_e2e_certificate(status, bundle, ledger, registry, self.semantics)
        checked = check_e2e_certificate(certificate, bundle, ledger, registry) if certificate else None
        reasons = list(solver_result.reasons)
        for component_name, kind, _detail in frontend_statuses:
            if kind == "TRANSPORT":
                reasons.append(Reason.TRANSPORT_ERROR)
            elif kind == "SCHEMA":
                reasons.append(Reason.SCHEMA_ERROR)
        if checked is not None and not checked.valid:
            status = CoreStatus.UNRESOLVED
            reasons.append(Reason.EVIDENCE_INCOMPLETE)
            missing_evidence.extend(checked.errors)
            certificate = None
        if status is CoreStatus.UNRESOLVED and not reasons:
            reasons.append(Reason.POLICY_AMBIGUOUS)
        if not case.system_policy.strip() and not case.user_request.strip():
            reasons.append(Reason.POLICY_NO_INTERPRETATION)
        primary = _primary_reason(reasons)
        diagnostics = _diagnostics(primary, reasons, missing_evidence, worlds)
        certified = CertifiedCoreResult(status, solver_result.world_proofs, certificate, checked, diagnostics)
        decision = adapt(certified, mode=self.adapter_mode)
        return E2EAnalysis(case.case_id, self.arm.arm_id, certified, decision, ledger, problem, bundle,
                           readings, contracts, frontend_statuses, required, len(worlds),
                           _component_summary(policy_lowered, lowered_goal_contracts, claims,
                                              semantics, frontend_statuses, status),
                           tuple(policy_lowered), tuple(lowered_goal_contracts))

    # ------------------------------------------------------------- frontends

    def _policy_readings(self, case, state_contract, catalog):
        failures, readings = [], []
        policy_text = case.system_policy
        if not policy_text.strip():
            return (), (), policy_text
        if self.oracle_policy and case.authoritative_policy_behaviors:
            return readings_from_behaviors(case.authoritative_policy_behaviors, policy_text), (), policy_text
        if self.oracle_policy and case.authoritative_policy_readings:
            return reading_from_rows(case.authoritative_policy_readings, policy_text), (), policy_text
        # B0 fidelity: the incumbent H0/GRS frontends see the RAW policy text
        # exactly as in the frozen E2E V1 run; the state-contract suffix only
        # extends the NORMATIVE text used for operational grounding.
        effective_text = policy_text
        if case.state_contract:
            from .source_adapter_v1 import POLICY_SCOPE_SUFFIX
            effective_text = policy_text + POLICY_SCOPE_SUFFIX + canonical(
                dict(sorted((case.state_contract or {}).items()))).decode("utf-8")
        if "h0_hist" in self.arm.policy_frontends or "grs_hist" in self.arm.policy_frontends:
            hist_readings, hist_failures, effective_text = historical_readings(
                case, state_contract, catalog, policy_text, self.backend,
                tuple(frontend for frontend in ("h0_hist", "grs_hist")
                      if frontend in self.arm.policy_frontends))
            readings.extend(hist_readings)
            failures.extend(hist_failures)
            return dedupe_readings(tuple(readings)), tuple(failures), effective_text
        if "h0" in self.arm.policy_frontends:
            h0 = parse_h0(policy_text, self.backend)
            if h0.candidate.available and h0.structure is not None:
                readings.append(compile_h0(h0.structure, state_contract, catalog))
            elif not h0.candidate.available:
                failures.append(("policy_h0", h0.candidate.failure, h0.candidate.detail))
        if "grs" in self.arm.policy_frontends:
            grounder = ground_inventory(policy_text, self.backend)
            if grounder.candidate.available and grounder.inventory is not None:
                synth = synthesize(policy_text, grounder.inventory, self.backend)
                if synth.candidate.available and synth.ruleset is not None:
                    readings.append(compile_grs(synth.ruleset, grounder.inventory, state_contract))
                elif not synth.candidate.available:
                    failures.append(("policy_grs_synth", synth.candidate.failure, synth.candidate.detail))
            elif not grounder.candidate.available:
                failures.append(("policy_grs_grounder", grounder.candidate.failure, grounder.candidate.detail))
        return dedupe_readings(tuple(readings)), tuple(failures), effective_text

    def _goal_contracts(self, case):
        failures, contracts = [], []
        request = case.user_request
        if not request.strip():
            return (), ()
        if self.oracle_goal and case.authoritative_goal_behaviors:
            return (contract_from_behaviors(case.authoritative_goal_behaviors, request),), ()
        if self.oracle_goal and case.authoritative_goal_readings:
            return (contract_from_rows(case.authoritative_goal_readings, request),), ()
        if "conservative" in self.arm.goal_frontends:
            conservative = parse_conservative(request, self.backend)
            if conservative.candidate.available:
                contracts.append(conservative_frames_to_contract(conservative.frames, ()))
            else:
                failures.append(("goal_conservative", conservative.candidate.failure, conservative.candidate.detail))
        if "rule_frames" in self.arm.goal_frontends:
            rf = parse_rule_frames(request, self.backend)
            if rf.candidate.available:
                contracts.append(make_contract("rule_frames", rf.frames,
                                               tuple(f"rejected_frame:{reason}" for reason in rf.rejected)))
            else:
                failures.append(("goal_rule_frames", rf.candidate.failure, rf.candidate.detail))
        return dedupe_contracts(tuple(contracts)), tuple(failures)


def _raw_scope_of(choice, lowered):
    return lowered.hypothesis_scopes.get(choice.parent_hypothesis_id, {})


def _absence_component(name: str) -> Component:
    option = ReadingOption(name + ":not_present", (), (), ())
    return Component(InterpretationAxis(name, (option.option_id,),
                                        "explicit input: " + name + ":not_present", True),
                     {option.option_id: option})


def _absence_authority(name: str) -> AuthoritativeAxis:
    return AuthoritativeAxis(name, (name + ":not_present",),
                             "explicit input: " + name + ":not_present", "EXPLICIT_STRUCTURED_ABSENCE")


def _behavior_rows(option) -> list:
    """Behavioral signature row ALTERNATIVES of one reading option: bound tool
    predicates, argument constraints, polarity, condition predicates and group
    alternatives. Representation variance (semantic action keys) collapses:
    what matters is the bound behavior, not the naming.

    A satisfaction group (B2: alternative ways to satisfy ONE goal) expands
    the option into one row-set PER satisfaction choice: the option's
    behavioral space is the SET of alternative bundles, so closure compares
    exactly the same set the authoritative behaviors enumerate."""
    base = []
    for obligation in option.obligations:
        constraints = sorted([list(constraint.path) + sorted(constraint.allowed_json)
                              for constraint in obligation.atom.argument_constraints])
        conditions = sorted([[atom.predicate, atom.expected_json] for atom in obligation.conditions
                             if atom.kind is not AtomKind.TARGET_CALL_MATCH])
        base.append({"pred": obligation.atom.predicate, "constraints": constraints,
                     "must": obligation.must_be_true, "conds": conditions})
    for group in option.disjunctive_groups:
        if group.per_call_atoms:
            alternatives = sorted({atom.predicate for _, atoms in group.per_call_atoms for atom in atoms})
            base.append({"group_alts": alternatives, "must": group.must_be_true})
    if option.unresolved_markers:
        base.append({"markers": sorted({marker.reason for marker in option.unresolved_markers})})
    satisfaction = [group for group in option.disjunctive_groups if group.satisfaction_choices]
    if not satisfaction:
        return [_sort_rows(base)]
    bundles = [[]]
    for group in satisfaction:
        expanded = []
        for atoms in group.satisfaction_choices:
            choice_rows = [{"pred": atom.predicate,
                            "constraints": sorted([list(constraint.path) + sorted(constraint.allowed_json)
                                                    for constraint in atom.argument_constraints]),
                            "must": group.must_be_true, "conds": []}
                           for atom in atoms]
            for rows in bundles:
                expanded.append(rows + choice_rows)
        bundles = expanded
    return [_sort_rows(base + rows) for rows in bundles]


def _sort_rows(rows: list) -> list:
    """Canonical row order: signatures compare as SETS of rows, never as
    ordered sequences (row order carries no semantics)."""
    return sorted(rows, key=lambda row: canonical(row).decode("utf-8"))


def _behavior_signature(options) -> list:
    """One signature per OPTION BUNDLE (world choice / satisfaction
    alternative): the admissible space is the SET of bundles, so binding
    alternatives and satisfaction choices create distinct signatures;
    duplicate bundles collapse (the space is a set)."""
    signatures = set()
    for option in options:
        signatures.update(canonical(rows).decode("utf-8") for rows in _behavior_rows(option))
    return sorted(signatures)


def _auth_behavior_rows(supplied) -> list:
    """Authoritative behavioral rows (corpus format): each reading is
    {"behavior": [{"pred": tool, "constraints": [[path, values]...], "must": bool,
    "conds": [[predicate, expected]...]}, ...], "groups": [{"alts": [...], "must": bool}]};
    constraint values are canonicalized to JSON literals deterministically."""
    rows = []
    for reading in supplied:
        entries = []
        # every supplied reading is ONE option bundle
        for entry in reading.get("behavior", ()):
            constraints = []
            for constraint in entry.get("constraints", ()):
                if isinstance(constraint, (list, tuple)) and len(constraint) > 1:
                    path = list(constraint[:-1])
                    values = constraint[-1]
                else:
                    path = [constraint]
                    values = []
                values = values if isinstance(values, list) else [values]
                encoded = []
                for value in values:
                    try:
                        parsed = json.loads(value) if isinstance(value, str) else None
                        if isinstance(value, str) and canonical(parsed).decode("utf-8") == value:
                            encoded.append(value)   # already a canonical JSON literal
                            continue
                    except (ValueError, TypeError):
                        pass
                    encoded.append(canonical(value).decode("utf-8"))
                constraints.append(path + sorted(encoded))
            entries.append({"pred": entry.get("pred"), "constraints": sorted(constraints),
                            "must": bool(entry.get("must", True)),
                            "conds": sorted([[c[0], c[1]] for c in entry.get("conds", ())])})
        for entry in reading.get("groups", ()):
            entries.append({"group_alts": sorted(entry.get("alts", ())), "must": bool(entry.get("must", True))})
        rows.append(canonical(_sort_rows(entries)).decode("utf-8"))
    return sorted(set(rows))


def extract_behavior_rows(lowered_readings) -> tuple:
    """Corpus-format behavioral rows extracted from lowered readings (used by
    tests to author authoritative closure from known-correct runs)."""
    readings = []
    for lowered in lowered_readings:
        for option in lowered.options:
            for entries in _behavior_rows(option):
                behavior = [entry for entry in entries if "pred" in entry]
                groups = [{"alts": entry["group_alts"], "must": entry["must"]}
                          for entry in entries if "group_alts" in entry]
                readings.append({"behavior": behavior, "groups": groups})
    return tuple(readings)


def readings_from_behaviors(behaviors, policy_text: str):
    """Oracle substitution: authoritative behavioral rows -> policy readings
    (rule form) that lower to exactly those behaviors."""
    from .e2e_types_v1 import CompiledCondition, CompiledRule, PolicyReading
    readings = []
    for index, supplied in enumerate(behaviors or ()):
        rules = []
        for i, entry in enumerate(supplied.get("behavior", ())):
            scope = tuple((constraint[0], tuple(
                _canonical_value(value) for value in (constraint[1] if len(constraint) > 1 else [])))
                for constraint in entry.get("constraints", ()))
            conditions = tuple(
                CompiledCondition(cond[0], cond[1] == "false", policy_text,
                                  literal_kind=cond[2] if len(cond) > 2 else "ACTION")
                for cond in entry.get("conds", ()))
            kind = "FORBID_CALL" if not entry.get("must", True) else (
                "REQUIRE_PRESERVE" if scope else "REQUIRE_CALL")
            rules.append(CompiledRule(f"policy:oracle:r{index}:rule{i}", kind, kind.replace("_CALL", "").replace("PRESERVE", ""),
                                      entry.get("pred"), "assistant", "NONE", conditions, (), scope,
                                      (policy_text,), (), "oracle"))
        readings.append(PolicyReading(f"policy:oracle:r{index}", "oracle", tuple(rules), ()))
    return tuple(readings)


def contract_from_behaviors(behaviors, user_request: str):
    """Oracle substitution: authoritative behavioral rows -> goal contract."""
    from .e2e_types_v1 import ExtractiveRef, GoalContract, GoalFrame, ScopeEntry
    frames = []
    for supplied in behaviors or ():
        for i, entry in enumerate(supplied.get("behavior", ())):
            scope = tuple(ScopeEntry(constraint[0], tuple(
                str(value) for value in (constraint[1] if len(constraint) > 1 else [])), None)
                for constraint in entry.get("constraints", ()))
            frames.append(GoalFrame(
                frame_kind="PROHIBITION" if not entry.get("must", True) else "DESIRED_OUTCOME",
                target_level="ACTION", actor=None, content_key=entry.get("pred"), entity_key=None,
                scope=scope, conditions=(), exceptions=(), temporal="NONE", coordination="NONE",
                choice="NONE", support=(ExtractiveRef("user_request", 0, len(user_request), user_request),),
                unresolved_fields=(), alternatives=()))
        for i, entry in enumerate(supplied.get("groups", ())):
            frames.append(GoalFrame(
                frame_kind="AUTHORIZATION", target_level="ACTION", actor=None, content_key="allowed_alternatives",
                entity_key=None, scope=(), conditions=(), exceptions=(), temporal="NONE", coordination="NONE",
                choice="ANY_OF", support=(ExtractiveRef("user_request", 0, len(user_request), user_request),),
                unresolved_fields=(), alternatives=tuple(entry.get("alts", ()))))
    return GoalContract("goal:oracle:r0", "oracle", tuple(frames), ())


def _canonical_value(value):
    return canonical(value).decode("utf-8")


def _behavioral_closure(supplied, lowered_readings) -> dict:
    """Closure premise: the set of bound BEHAVIORS equals the authoritative
    behavioral set (spec 102: an explicit closure premise, never inferred from
    frontend agreement)."""
    auth = _auth_behavior_rows(tuple(supplied or ()))
    actual = _behavior_signature([option for lowered in lowered_readings for option in lowered.options])
    return {"supplied": bool(supplied), "actual_count": len(actual), "auth_count": len(auth),
            "closed": bool(supplied) and actual == auth,
            "actual_sample": actual[:2], "auth_sample": auth[:2]}


def _absence_component(name: str) -> Component:
    option = ReadingOption(name + ":not_present", (), (), ())
    return Component(InterpretationAxis(name, (option.option_id,),
                                        "explicit input: " + name + ":not_present", True),
                     {option.option_id: option})


def _absence_authority(name: str) -> AuthoritativeAxis:
    return AuthoritativeAxis(name, (name + ":not_present",),
                             "explicit input: " + name + ":not_present", "EXPLICIT_STRUCTURED_ABSENCE")


def _policy_closure(case, readings) -> dict:
    supplied = tuple(case.authoritative_policy_readings or ())
    actual = sorted(reading_canonical_key(reading) for reading in readings)
    authoritative = sorted(_authoritative_policy_key(rows) for rows in supplied)
    return {"supplied": bool(supplied), "actual_keys": actual, "authoritative_keys": authoritative,
            "closed": bool(supplied) and bool(actual) and actual == authoritative}


def _goal_closure(case, contracts, state_contract=None) -> dict:
    from .goal_composition_v1 import compiled_goal_closure_key, compile_goal_contract
    from .goal_rule_frames_v1 import contract_from_rows
    supplied = tuple(case.authoritative_goal_readings or ())
    state = state_contract if state_contract is not None else (case.state_contract or {})
    actual = sorted(compiled_goal_closure_key(*compile_goal_contract(contract, state)) for contract in contracts)
    authoritative = sorted(compiled_goal_closure_key(*compile_goal_contract(contract_from_rows(rows, case.user_request), state))
                           for rows in supplied)
    return {"supplied": bool(supplied), "actual_keys": actual, "authoritative_keys": authoritative,
            "closed": bool(supplied) and bool(actual) and actual == authoritative}


def _authoritative_policy_key(rows) -> str:
    supplied = rows.get("rules", rows) if isinstance(rows, dict) else rows
    unresolved = rows.get("unresolved", []) if isinstance(rows, dict) else []
    normalized = []
    for row in supplied:
        normalized.append({"kind": row.get("kind"), "modality": row.get("modality"),
                           "action_key": row.get("action_key"), "actor": row.get("actor"),
                           "relation": row.get("relation"),
                           "conditions": sorted(map(list, row.get("conditions", []))),
                           "exceptions": sorted(map(list, row.get("exceptions", []))),
                           "scope": sorted((field, sorted(values)) for field, values in row.get("scope", []))})
    return digest({"rules": sorted(normalized, key=canonical), "unresolved": sorted(unresolved)})


def _authoritative_goal_key(rows) -> str:
    frames = rows.get("frames", rows) if isinstance(rows, dict) else rows
    unresolved = rows.get("unresolved", []) if isinstance(rows, dict) else []
    return canonical(list(frames) + sorted(unresolved)).decode("utf-8")


def _primary_reason(reasons):
    priorities = [Reason.TRANSPORT_ERROR, Reason.SCHEMA_ERROR, Reason.POLICY_NO_INTERPRETATION,
                  Reason.POLICY_OPEN_SEMANTICS, Reason.POLICY_AMBIGUOUS, Reason.GOAL_PLAN_AMBIGUOUS,
                  Reason.CLAIM_UNTYPED, Reason.ENTITY_AMBIGUOUS, Reason.ENTITY_UNBOUND,
                  Reason.TIME_UNBOUND, Reason.SOURCE_UNBOUND, Reason.TOOL_VERSION_MISMATCH,
                  Reason.TOOL_EFFECT_UNKNOWN, Reason.CAUSALITY_UNPROVED, Reason.TEMPORAL_AMBIGUITY,
                  Reason.EVIDENCE_INCOMPLETE]
    unique = tuple(dict.fromkeys(reasons))
    for reason in priorities:
        if reason in unique:
            return reason
    return unique[0] if unique else Reason.EVIDENCE_INCOMPLETE


def _diagnostics(primary, reasons, missing_evidence, worlds):
    from ..types import Diagnostics
    unique = tuple(dict.fromkeys(reasons))
    return Diagnostics(primary, tuple(reason for reason in unique if reason is not primary), (), (),
                       tuple(dict.fromkeys(missing_evidence)), ())


def _component_summary(policy_lowered, goal_lowered, claims, semantics, frontend_statuses, status):
    return {
        "policy_options": sum(len(lowered.options) for lowered in policy_lowered),
        "goal_options": sum(len(lowered.options) for lowered in goal_lowered),
        "claim_axes": len(claims.components),
        "t2_effect_candidates": sum(len(value.effects) for _, value in semantics
                                    if any(not effect.contract_sha256 for effect in value.effects)),
        "frontend_failures": [{"component": name, "kind": kind, "detail": detail}
                              for name, kind, detail in frontend_statuses],
        "claim_failures": len(claims.graph.failures),
        "status": status.value,
    }
