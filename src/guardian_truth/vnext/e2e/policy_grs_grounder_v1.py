"""GRS grounded inventory: the Grounder (spec 38, 39, 41).

The grounder only detects source-supported semantic atoms with exact quotes,
basic atom kinds and surface modality/relation markers. It never decides the
final rule structure (spec 42). Every accepted atom is source-grounded: the
quote must appear verbatim in the policy text.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..integrity import canonical
from ..semantic import SemanticBackend, schema_valid
from .e2e_types_v1 import FrontendCandidate, GroundedInventory, InventoryAtom, SurfaceMarker

GROUNDER_VERSION = "policy_grs_grounder_e2e_v1"

GROUNDER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["facts", "modality_markers", "relation_markers"],
    "properties": {
        "facts": {"type": "array", "maxItems": 16, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "kind", "meaning", "quote"],
            "properties": {"id": {"type": "string", "pattern": "^F[0-9]+$"},
                "kind": {"type": "string", "enum": ["ACTION", "STATE", "ACTOR", "ENTITY", "CLAIM", "EVIDENCE", "VALUE", "EFFECT"]},
                "meaning": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "quote": {"type": "string"}}}},
        "modality_markers": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "surface", "quote"],
            "properties": {"id": {"type": "string", "pattern": "^M[0-9]+$"},
                "surface": {"type": "string"}, "quote": {"type": "string"}}}},
        "relation_markers": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "surface", "quote"],
            "properties": {"id": {"type": "string", "pattern": "^R[0-9]+$"},
                "surface": {"type": "string"}, "quote": {"type": "string"}}}},
    },
}

INSTRUCTIONS = (
    "Extract the grounded semantic inventory of the POLICY text: semantic atoms (facts), "
    "surface modality markers and surface relation markers. You only detect what is "
    "source-supported: every fact needs an exact verbatim quote from the policy text and a "
    "normalized snake_case meaning key when the text supports one; when the text names a tool, "
    "use the exact tool name verbatim as the meaning key. Do NOT decide how atoms "
    "combine into rules, do NOT attach conditions to targets, do NOT split obligations. "
    "IDs must be F1..Fn, M1..Mn, R1..Rn. This is an inventory, NOT an interpretation. "
    "Return exactly one JSON object, no markdown.")


@dataclass(frozen=True)
class GrounderResult:
    candidate: FrontendCandidate
    inventory: GroundedInventory | None


def ground_inventory(policy_text: str, backend: SemanticBackend) -> GrounderResult:
    if not policy_text.strip():
        return GrounderResult(FrontendCandidate("grs_grounder", True, None),
                               GroundedInventory((), (), ()))
    payload = {"policy": policy_text, "instructions": INSTRUCTIONS}
    proposal = backend.propose("policy_grs_grounder", payload, GROUNDER_SCHEMA)
    if proposal.transport_status != "SUCCESS":
        return GrounderResult(FrontendCandidate("grs_grounder", False, "TRANSPORT", proposal.error_category), None)
    if proposal.schema_status != "VALID" or not schema_valid(proposal.value, GROUNDER_SCHEMA):
        return GrounderResult(FrontendCandidate("grs_grounder", False, "SCHEMA"), None)
    value = proposal.value
    facts, seen_ids = [], set()
    for item in value["facts"]:
        quote = item["quote"]
        # Source-grounded acceptance: quote exists verbatim, unique ID, allowed kind.
        if not quote or quote not in policy_text or item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        facts.append(InventoryAtom(item["id"], item["kind"], item["meaning"], quote))
    modality, relation = [], []
    for item in value["modality_markers"]:
        if item["quote"] and item["quote"] in policy_text:
            modality.append(SurfaceMarker(item["id"], item["surface"], item["quote"]))
    for item in value["relation_markers"]:
        if item["quote"] and item["quote"] in policy_text:
            relation.append(SurfaceMarker(item["id"], item["surface"], item["quote"]))
    facts = tuple(sorted(facts, key=lambda atom: int(atom.atom_id[1:])))
    modality = tuple(sorted(modality, key=lambda marker: int(marker.marker_id[1:])))
    relation = tuple(sorted(relation, key=lambda marker: int(marker.marker_id[1:])))
    if not facts:
        return GrounderResult(FrontendCandidate("grs_grounder", False, "COMPILE", "no grounded atoms"), None)
    return GrounderResult(FrontendCandidate("grs_grounder", True, None),
                          GroundedInventory(facts, tuple(modality), tuple(relation)))
