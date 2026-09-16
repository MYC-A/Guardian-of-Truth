"""Claim adapter: TEXT_VIEW / ACTION_VIEW invariant around the baseline claim
machinery. The claim graph is built ONLY over assistant text spans of the
target response (response_spans skips call markers), and attempted-call
arguments never enter claim extraction. The reverse direction also holds: text
projections never prove an action (spec 11). Claim hard failures become
per-world UNKNOWN markers: they block PROVED_NO_ERROR but never mask an
independent certified violation.

Value anchoring (E2E V1, deterministic): a POSITIVE STATE/ATTRIBUTION claim
whose object is a single literal token anchors the atom expectation to that
exact observed value, so contradicted field claims prove FALSE and matching
field claims prove TRUE. Multi-word or absent objects fall back to the
baseline boolean polarity mapping, which stays UNKNOWN for non-boolean
observations (never a false witness). The SAME function is used by the
solver-side adapter and the independent certificate checker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..binder import ClaimBinding, bind_claim
from ..claims import ClaimGraph, build_claim_graph
from ..integrity import canonical
from ..ledger import EvidenceLedger, LedgerIndex
from ..proof_records import AtomKind, Obligation, ProofAtom, TimeMode
from ..types import ClaimKind, Disposition, Reason, TypedClaim
from .e2e_types_v1 import E2ESemantics, FULL_SEMANTICS, ReadingOption, UnresolvedMarker
from .world_integration_v1 import Component

CLAIM_ADAPTER_VERSION = "claim_adapter_e2e_v1"
CLAIM_OBLIGATION_HYPOTHESIS = "GUARDIAN_FACTUAL_CONSISTENCY_V1"

_KIND_MAP = {ClaimKind.STATE: AtomKind.OBSERVED_STATE, ClaimKind.ATTRIBUTION: AtomKind.RESULT_FIELD,
             ClaimKind.ACTION_COMPLETED: AtomKind.ACTION_COMPLETED, ClaimKind.ABSENCE: AtomKind.HISTORICAL_ACTION}
_SINGLE_TOKEN = re.compile(r"[A-Za-z0-9_-]+")


def claim_expected_json(claim: TypedClaim, *, typing_v2: bool = False) -> str:
    """Deterministic expectation for a factual claim atom. Shared by the
    adapter and the independent checker so they can never disagree.

    typing_v2 (cycle 3): the anchored literal must additionally NOT be an
    entity reference token (an entity id echoing into the object slot is an
    identity mention, not a value assertion - anchoring it fabricated
    refutable expectations like status == "CRS-2218")."""
    if (claim.polarity != "NEGATIVE" and claim.object
            and claim.object != claim.predicate
            and _SINGLE_TOKEN.fullmatch(claim.object)
            and claim.kind in {ClaimKind.STATE, ClaimKind.ATTRIBUTION}
            and not (typing_v2 and claim.object in claim.entity_refs)):
        return canonical(claim.object).decode("utf-8")
    # An object that merely echoes the predicate carries no value information:
    # fall back to the boolean polarity mapping (never a fabricated value).
    return "false" if claim.polarity == "NEGATIVE" else "true"


@dataclass(frozen=True)
class ClaimComponents:
    graph: ClaimGraph
    components: tuple[Component, ...]
    bindings: tuple[ClaimBinding, ...]


def build_claims(response: str, backend, ledger: EvidenceLedger,
                 semantics: E2ESemantics = FULL_SEMANTICS) -> ClaimComponents:
    index = LedgerIndex(ledger)
    graph = build_claim_graph(response, backend)
    components, bindings = [], []
    for claim in graph.claims:
        if claim.disposition is Disposition.NON_VERIFIABLE:
            continue
        if (claim.disposition is Disposition.UNKNOWN_SEMANTICS or claim.kind not in _KIND_MAP
                or claim.modality not in {"ASSERTED", "REPORTED"}):
            marker = UnresolvedMarker(claim.claim_id + ":untyped", "claim semantics untyped or causal")
            components.append(_single_option_component(claim.claim_id, marker))
            continue
        binding = bind_claim(claim, ledger, index)
        bindings.append(binding)
        markers = []
        if not binding.alternatives:
            markers.append(UnresolvedMarker(claim.claim_id + ":unbound", "entity unbound"))
        if Reason.SOURCE_UNBOUND in binding.reasons:
            markers.append(UnresolvedMarker(claim.claim_id + ":source", "claim source unbound"))
        action = claim.kind in {ClaimKind.ACTION_COMPLETED, ClaimKind.ABSENCE}
        anchor = claim.time_anchor
        historical = (semantics.claim_typing and claim.kind is ClaimKind.STATE
                      and anchor in {"PAST", "ALL_HISTORY", "YESTERDAY"})
        unverifiable_time = (semantics.claim_typing and claim.kind is ClaimKind.STATE
                             and anchor in {"FUTURE", "UNSPECIFIED", "UNKNOWN"})
        if ((not action and binding.time_index is None and not historical)
                or (action and anchor not in {"PAST", "ALL_HISTORY", "NOW"} and binding.time_index is None)):
            markers.append(UnresolvedMarker(claim.claim_id + ":time", "claim time unbound"))
        if unverifiable_time:
            # A FUTURE or time-unspecified state claim can never be verified
            # against supplied evidence; an unbound-time atom fabricated a
            # refutable CURRENT-state expectation (never again, cycle 3).
            markers.append(UnresolvedMarker(claim.claim_id + ":time", "claim time not verifiable"))
            components.append(_single_option_component(claim.claim_id, markers[-1]))
            continue
        options = {}
        for i, alternative in enumerate(binding.alternatives):
            choice_id = claim.claim_id + f":binding:{i}"
            time = binding.time_index if binding.time_index is not None else len(ledger.events) - 1
            # STATE/ATTRIBUTION claims are checked against the LATEST matching
            # observation (result-field claims describe tool output; state
            # claims describe the newest observed state). NO_ERROR additionally
            # requires the FRESH_STATE_EVIDENCE closure premise: no attempted
            # call may follow the supporting observation (an attempted mutation
            # can invalidate a stale state claim, spec 2.12/20).
            # claim_typing: PAST/ALL_HISTORY/YESTERDAY state claims are HISTORICAL
            # existentials (through-mode), never current-snapshot refutations.
            latest = claim.kind in {ClaimKind.STATE, ClaimKind.ATTRIBUTION} and not historical
            atom = ProofAtom(claim.claim_id + f":atom:{i}", _KIND_MAP[claim.kind], alternative.entity,
                             claim.predicate, claim_expected_json(claim, typing_v2=semantics.claim_typing), claim.actor,
                             TimeMode.LATEST_OBSERVATION if latest else (
                                 TimeMode.THROUGH if (action and binding.time_index is None) or historical else TimeMode.AT), time)
            obligation = Obligation(claim.claim_id + f":factual:{i}", CLAIM_OBLIGATION_HYPOTHESIS,
                                    claim.claim_id, atom, True)
            options[choice_id] = ReadingOption(choice_id, (obligation,), (), ())
        if not options:
            choice_id = claim.claim_id + ":unbound"
            options[choice_id] = ReadingOption(choice_id, (), (), tuple(markers) or
                                               (UnresolvedMarker(claim.claim_id + ":unbound", "entity unbound"),))
            components.append(_component(claim.claim_id, options, "claim binding unresolved"))
            continue
        # Marker applies to every alternative option (unknowns ride along).
        options = {cid: (option if not markers else ReadingOption(cid, option.obligations,
                                                                  option.disjunctive_groups,
                                                                  option.unresolved_markers + tuple(markers)))
                   for cid, option in options.items()}
        components.append(_component(claim.claim_id, options,
                                     "enumerated exact supplied-source identities:" + claim.claim_id))
    return ClaimComponents(graph, tuple(components), tuple(bindings))


def _single_option_component(name: str, marker: UnresolvedMarker) -> Component:
    options = {name + ":untyped": ReadingOption(name + ":untyped", (), (), (marker,))}
    return _component(name, options, "untyped claim semantics")


def _component(name: str, options: dict, source: str) -> Component:
    from ..proof_records import InterpretationAxis
    axis = InterpretationAxis(name, tuple(options), source, True)
    return Component(axis, options)


def claim_obligation_ids(component: Component) -> tuple[str, ...]:
    ids = []
    for option in component.options.values():
        ids.extend(obligation.obligation_id for obligation in option.obligations)
    return tuple(ids)
