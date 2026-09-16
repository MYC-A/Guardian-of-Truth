"""E2E-agent-1 causal repair A2: deterministic claim value anchoring.

Two STRICT anchors, both pure functions of (claim, T1 registry) — the same
function is used by the pipeline and by the certificate checker:

1. LITERAL-VALUE anchor (user spec section 5.1, the 'status = cancelled'
   form): a typed STATE / RESULT_FIELD / ATTRIBUTION claim whose `object`
   is an unambiguous scalar literal (and NOT an entity reference of the
   claim) is checked against that literal value instead of being reduced to
   boolean true:

       atom.expected_json := canonical(object)     (e.g. '"cancelled"')

   Multi-word or ambiguous values, entity-referential objects, negative
   polarity and type mismatches never anchor — the claim keeps the boolean
   surface, which the prover resolves to UNKNOWN when the evidence types do
   not match (no semantic guessing anywhere).

2. COMPLETION anchor (the surface that actually exists on the E2E V1 dev
   corpus): a typed ACTION_COMPLETED claim whose predicate TEXT contains
   exactly one registry tool name as a whole token (e.g. the free-text
   predicate 'ran cancel_shipment') and whose tool has exactly ONE distinct
   causal-confirmed effect predicate P is anchored to that canonical effect
   surface:

       atom.predicate := P        (expected stays boolean true)

   The claim 'I ran cancel_shipment' is then checked as the registry's
   canonical completion predicate (e.g. 'cancelled' = true), which the
   existing trusted-effect support/refutation channels prove or refute with
   T1 contracts — the same solver and the same certificate checker.  Two
   tool names in the text, a tool without a unique causal effect predicate,
   or no token match at all -> no anchor (UNKNOWN, honest).

Both anchors are logged per claim and hashed into the certificate context;
the checker re-derives them and compares byte-exactly.
"""
from __future__ import annotations

import re

from ..integrity import canonical
from ..types import ClaimKind, TypedClaim
from ..tools import ContractRegistry

ANCHOR_KINDS_LITERAL = {ClaimKind.STATE, ClaimKind.ATTRIBUTION}
ANCHOR_KINDS_COMPLETION = {ClaimKind.ACTION_COMPLETED}


def _scalar_literal(token: str):
    """Parse a scalar literal (never objects/arrays).  A bare single word is
    deterministically coerced to its canonical JSON string (the same format
    normalization the semantic-binding validator uses); a bare number stays
    a number.  Multi-word/ambiguous tokens never parse."""
    import json
    token = token.strip()
    try:
        value = json.loads(token)
    except (ValueError, TypeError):
        if not token or any(character.isspace() for character in token):
            return None
        value = token
    if isinstance(value, (dict, list)) or value is None:
        return None
    return value


def _tool_tokens(text: str, tools: tuple[str, ...]) -> tuple[str, ...]:
    """Tool names appearing in the text as whole, non-overlapping tokens."""
    found = []
    for tool in tools:
        if re.search(r"(?<![\w./:@-])" + re.escape(tool) + r"(?![\w./:@-])", text):
            found.append(tool)
    return tuple(found)


def _causal_effect_predicates(registry: ContractRegistry, tool: str) -> tuple[str, ...]:
    """Distinct causal-confirmed effect predicates a tool's contracts guarantee."""
    predicates = []
    for contract in registry.contracts:
        if contract.identity.name != tool:
            continue
        for rule in contract.guarantees:
            for spec in rule.effects:
                if spec.causal_action_confirmed and spec.predicate not in predicates:
                    predicates.append(spec.predicate)
    return tuple(predicates)


def anchored_claim_surface(claim: TypedClaim, registry: ContractRegistry):
    """Deterministic anchored (predicate, expected_json) for one claim.

    Returns None when no anchor applies (the boolean surface stands)."""
    if claim.kind is None:
        return None
    tools = tuple(contract.identity.name for contract in registry.contracts)

    # --- literal-value anchor: 'status = cancelled' claims ---------------
    if claim.kind in ANCHOR_KINDS_LITERAL and claim.polarity == "POSITIVE" \
            and claim.object is not None:
        object_text = claim.object.strip()
        entity_refs = set(claim.entity_refs or ())
        if object_text and object_text not in entity_refs:
            value = _scalar_literal(object_text)
            if value is not None and not isinstance(value, bool) \
                    and canonical(value).decode("utf-8"):
                # a non-boolean scalar literal that is not an entity ref:
                # anchor the expected value to the literal itself
                return {"anchor": "LITERAL_VALUE",
                        "predicate": claim.predicate,
                        "expected_json": canonical(value).decode("utf-8")}

    # --- completion anchor: free-text completion claims ------------------
    if claim.kind in ANCHOR_KINDS_COMPLETION and claim.polarity == "POSITIVE" \
            and claim.predicate:
        mentioned = _tool_tokens(claim.predicate, tools)
        if len(mentioned) == 1:
            predicates = _causal_effect_predicates(registry, mentioned[0])
            if len(predicates) == 1:
                return {"anchor": "COMPLETION_EFFECT",
                        "predicate": predicates[0],
                        "expected_json": "true" if claim.polarity == "POSITIVE" else "false"}
    return None


def anchor_claims(claims, registry: ContractRegistry) -> dict:
    """Anchor decisions for every claim (claim_id -> anchor record or absent)."""
    anchors = {}
    for claim in claims:
        surface = anchored_claim_surface(claim, registry)
        if surface is not None:
            anchors[claim.claim_id] = surface
    return anchors
