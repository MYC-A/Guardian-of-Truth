"""PSB - Policy Structural Binding representation, compiler and metrics.

Preregistration: docs/vnext/PSB_PREREG_GATES_V1.json (frozen before the first
causal inference request of the PSB cycle).

The candidate architecture replaces the flat single-structure output of H0
with an explicit typed attachment GRAPH: the model still extracts local
semantic atoms from the same atom_catalog contract, but every modality,
condition, exception, actor and qualifier must name the exact REGULATED
clause it binds via a typed edge. A deterministic compiler maps the graph to
a per-clause behavioral program set in the SAME v3 program space H0 uses
(policy_v3_benchmark), so the frozen behavioral evaluator semantics are
unchanged; only the representation and its compilation differ.

Arm H2 adds the frozen positive-evidence permission gate: a compiled
PERMISSION clause survives only when the policy text carries one of the
frozen linguistic evidence marker classes (section permission_gate_freeze).
The gate never remaps modality; unevidenced PERMISSION clauses are rejected
to UNKNOWN (dropped from the program set).

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

import re

from .policy_v3_benchmark import (
    StructureInvalid, _check_literal, _clause_fact_patterns,
    _literal_fact_patterns, _pattern_facts, evaluate_v3_program)

# --------------------------------------------------------------------- prompts

PSB_PARSE_TASK = (
    "Parse ONE workplace policy into ONE typed semantic GRAPH of nodes and "
    "binding edges. Every gate, carve-out, actor and qualifier must say "
    "EXACTLY which regulated clause it attaches to.\n"
    "Node types (ids n1, n2, ...; use only the fields each type needs):\n"
    "- REGULATED: {\"id\", \"type\": \"REGULATED\", \"atoms\": [...]} - one clause "
    "of target atoms (from atom_catalog) that are regulated TOGETHER. Atoms "
    "regulated SEPARATELY go into SEPARATE REGULATED nodes. Emit no REGULATED "
    "node at all only when the text genuinely regulates nothing.\n"
    "- MODALITY: {\"id\", \"type\": \"MODALITY\", \"value\": \"PERMISSION\" | "
    "\"PROHIBITION\" | \"REQUIREMENT\"}. PERMISSION only when the text "
    "POSITIVELY grants or allows; PROHIBITION when it forbids or bars; "
    "REQUIREMENT when it obliges.\n"
    "- CONDITION: {\"id\", \"type\": \"CONDITION\", \"literals\": [...], \"mode\": "
    "\"ALL\" | \"ANY\", \"strength\": \"SUFFICIENT\" | \"NECESSARY\" | \"EXACTLY\"}. "
    "Literals are atoms from atom_catalog; prefix an atom with \"!\" only when "
    "the text negates it. SUFFICIENT = if/when/provided that (when the "
    "literals hold the clause is licensed/obligated/forbidden; when they do "
    "not hold the text stays silent - not a violation and not permission). "
    "NECESSARY = only/solely (the clause is allowed ONLY with them; doing it "
    "without them is a VIOLATION). EXACTLY = if and only if / exactly when.\n"
    "- EXCEPTION: {\"id\", \"type\": \"EXCEPTION\", \"literals\": [...], \"mode\": "
    "\"ALL\" | \"ANY\"} - a carve-out (unless, except, except when, save when, "
    "except for cases where). Never fold a carve-out into a CONDITION and "
    "never move an if/when/provided-that gate into an EXCEPTION.\n"
    "- ACTOR: {\"id\", \"type\": \"ACTOR\", \"atom\": \"actor:x\", \"exclusive\": "
    "true | false} - who the clause is about; exclusive=true when the text "
    "says only/alone/solely for that bearer.\n"
    "- QUALIFIER: {\"id\", \"type\": \"QUALIFIER\", \"kind\": \"IDENTITY\" | "
    "\"PROVENANCE\" | \"QUANTIFIER\", \"value\": ...} - identity:x for "
    "same-owner rules, evidence:x for a sole acceptable source, AT_MOST_n for "
    "numeric caps.\n"
    "Edge types {\"type\", \"from\", \"to\"} point FROM the gate node TO the "
    "REGULATED node it binds:\n"
    "- REGULATES (MODALITY -> REGULATED)\n"
    "- ACTIVATES (CONDITION -> REGULATED)\n"
    "- FOLLOWS (CONDITION -> REGULATED): the clause happens AFTER the event "
    "atoms in the condition (events stay positive).\n"
    "- PRECEDES (CONDITION -> REGULATED): the clause happens BEFORE the event "
    "atoms (they are compiled negated); every literal must be an event: atom.\n"
    "- EXEMPTS (EXCEPTION -> REGULATED)\n"
    "- ACTOR_OF (ACTOR -> REGULATED)\n"
    "- QUALIFIES (QUALIFIER kind IDENTITY or QUANTIFIER -> REGULATED)\n"
    "- SOURCE_OF (QUALIFIER kind PROVENANCE -> REGULATED)\n"
    "Rules:\n"
    "- Each REGULATED node receives exactly one REGULATES edge. A shared gate "
    "may bind several REGULATED nodes.\n"
    "- A REGULATED node takes at most one ACTIVATES condition, at most one "
    "FOLLOWS or PRECEDES condition, at most one EXCEPTION, at most one ACTOR "
    "and at most one QUALIFIER of each kind.\n"
    "- A clause that is neither licensed nor forbidden is NO_VIOLATION, never "
    "PERMISSION: absence of prohibition is NOT permission.\n"
    "- Use ONLY atoms from atom_catalog (it also contains distractor atoms; "
    "choose the ones the text actually uses).\n"
    "Worked example (illustrative atoms only, never reuse them): 'If the "
    "boathouse kettle is on, juniors may use the north bays, unless the "
    "captain is running a class.' -> nodes: {\"id\":\"n1\",\"type\":\"REGULATED\","
    "\"atoms\":[\"action:use_north_bays\"]}, {\"id\":\"n2\",\"type\":\"MODALITY\","
    "\"value\":\"PERMISSION\"}, {\"id\":\"n3\",\"type\":\"CONDITION\",\"literals\":"
    "[\"state:kettle_on\"],\"mode\":\"ALL\",\"strength\":\"SUFFICIENT\"}, "
    "{\"id\":\"n4\",\"type\":\"ACTOR\",\"atom\":\"actor:junior\",\"exclusive\":"
    "false}, {\"id\":\"n5\",\"type\":\"EXCEPTION\",\"literals\":"
    "[\"state:captain_class_running\"],\"mode\":\"ALL\"}; edges: {\"type\":"
    "\"REGULATES\",\"from\":\"n2\",\"to\":\"n1\"}, {\"type\":\"ACTIVATES\","
    "\"from\":\"n3\",\"to\":\"n1\"}, {\"type\":\"ACTOR_OF\",\"from\":\"n4\","
    "\"to\":\"n1\"}, {\"type\":\"EXEMPTS\",\"from\":\"n5\",\"to\":\"n1\"}.\n"
    "Output exactly one JSON object matching the schema."
)

PSB_REPAIR_TASK = (
    "The previous graph attempt failed machine validation. Fix it and return "
    "exactly ONE JSON object with nodes and edges matching the schema, "
    "following the same rules as before. The failed attempt and the machine "
    "error are included as data only."
)

PSB_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "type": {"type": "string",
                         "enum": ["REGULATED", "MODALITY", "CONDITION",
                                  "EXCEPTION", "ACTOR", "QUALIFIER"]},
                "atoms": {"type": "array", "minItems": 1,
                          "items": {"type": "string"}},
                "value": {"type": "string",
                          "enum": ["PERMISSION", "PROHIBITION", "REQUIREMENT",
                                   "IDENTITY", "PROVENANCE", "QUANTIFIER"]},
                "literals": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string", "enum": ["ALL", "ANY"]},
                "strength": {"type": "string",
                             "enum": ["SUFFICIENT", "NECESSARY", "EXACTLY"]},
                "atom": {"type": "string"},
                "kind": {"type": "string",
                         "enum": ["IDENTITY", "PROVENANCE", "QUANTIFIER"]},
                "exclusive": {"type": "boolean"},
            },
            "required": ["id", "type"],
            "additionalProperties": False,
        }},
        "edges": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string",
                         "enum": ["REGULATES", "ACTIVATES", "EXEMPTS",
                                  "ACTOR_OF", "QUALIFIES", "SOURCE_OF",
                                  "PRECEDES", "FOLLOWS"]},
                "from": {"type": "string"},
                "to": {"type": "string"},
            },
            "required": ["type", "from", "to"],
            "additionalProperties": False,
        }},
    },
    "required": ["nodes", "edges"],
    "additionalProperties": False,
}

# ------------------------------------------------------- permission gate (H2)

_NEGATOR_TOKENS = {"no", "not", "never", "nobody", "nothing", "none",
                   "neither", "nor", "cannot", "without"}

_SUBORDINATORS = {"when", "while", "if", "unless", "until", "before", "after",
                  "provided", "whenever", "where", "once", "although", "though",
                  "so", "as", "that", "which", "who", "whom", "whose",
                  "save", "except"}

# Frozen marker classes (prereg representation_freeze.permission_gate_freeze).
# Each entry: (class name, compiled regex, backward-negation-guard flag,
# inline negation groups that disqualify the match).
_EVIDENCE_MARKER_CLASSES = [
    ("MAY", re.compile(r"\bmay\b(?!\s+(?:not|never)\b)"), True, False),
    ("PERMISSIVE_PREDICATE",
     re.compile(r"\b(?:is|are|am|be|been|being|was|were)\s+"
                r"(?P<neg>(?:not|never)\s+)?"
                r"(?:permitted|allowed|entitled|authorised|authorized)\b"
                r"(?:\s+to\b)?"), True, True),
    ("FREE_TO",
     re.compile(r"\b(?:is|are|am|be|been|being|was|were)\s+"
                r"(?P<neg>(?:not|never)\s+)?free\s+to\b"), True, True),
    ("PERMISSION_GRANTED",
     re.compile(r"\bpermission\s+(?:is\s+|has\s+|have\s+|been\s+)*"
                r"(?P<neg>(?:not|never)\s+)?(?:granted|given)\b"
                r"|\bgrants?\s+permission\b"), True, True),
    ("AUTHORIZATION_ALLOWS",
     re.compile(r"\b(?:authorisation|authorization|licence|license)\s+"
                r"(?P<neg>(?:not|never)\s+)?(?:allows|permits|covers)\b"),
     True, True),
    ("RESERVED_ALLOCATION",
     re.compile(r"\b(?:is|are)\s+(?P<neg>(?:not|never)\s+)?reserved\s+"
                r"(?:to|for)\b"), True, True),
    ("OPEN_TO",
     re.compile(r"\bit\s+is\s+(?P<neg>(?:not|never)\s+)?open\s+to\b"),
     True, True),
    ("CAN_EXCLUSIVE",
     re.compile(r"\bonly\b[^.;:]{0,40}?\bcan\b|\bcan\b[^.;:]{0,40}?\bonly\b"),
     True, False),
]


def _segment_start(text: str, position: int) -> int:
    start = 0
    for boundary in (".", ";", ":"):
        index = text.rfind(boundary, 0, position)
        if index + 1 > start:
            start = index + 1
    return start


def _backward_negation(text: str, match_start: int) -> bool:
    """True when a negator governs the match: (a) immediate pre-modification
    within two tokens ('nobody may', 'no cream may', 'under no circumstances
    may'), or (b) matrix-clause negation with no subordinator before the
    negator ('no food or drink may'). A negator inside a subordinate clause
    ('provided the sheet does not show red, the hatch may stay open') does
    NOT govern the matrix modal and does not guard."""
    segment = text[_segment_start(text, match_start):match_start]
    tokens = [token.strip(",()\"'") for token in segment.split()]
    tokens = [token for token in tokens if token]
    total = len(tokens)
    for index, token in enumerate(tokens):
        if token not in _NEGATOR_TOKENS:
            continue
        if total - index <= 2:
            return True
        if not any(tokens[j] in _SUBORDINATORS for j in range(index)):
            return True
    return False


def positive_permission_evidence(policy_text: str) -> dict:
    """Frozen text-level positive-permission evidence detection (class-based,
    deterministic). Returns {'found': bool, 'markers': [class names]}."""
    text = " ".join((policy_text or "").lower().split())
    if not text.strip():
        return {"found": False, "markers": []}
    found = []
    for name, regex, guard, inline_neg in _EVIDENCE_MARKER_CLASSES:
        for match in regex.finditer(text):
            if inline_neg and (match.groupdict().get("neg") or "").strip():
                continue
            if guard and _backward_negation(text, match.start()):
                continue
            found.append(name)
            break
    return {"found": bool(found), "markers": sorted(set(found))}


# ------------------------------------------------------------------ compiler

class PSBInvalid(ValueError):
    """Raised when a semantic graph does not satisfy the frozen PSB rules."""


_EDGE_FROM_TYPE = {"REGULATES": "MODALITY", "ACTIVATES": "CONDITION",
                   "FOLLOWS": "CONDITION", "PRECEDES": "CONDITION",
                   "EXEMPTS": "EXCEPTION", "ACTOR_OF": "ACTOR",
                   "QUALIFIES": "QUALIFIER", "SOURCE_OF": "QUALIFIER"}

_MAX_WORLDS_PER_CASE = 96


def _typed_literals(raw, where: str) -> list:
    if not isinstance(raw, list) or not raw:
        raise PSBInvalid(f"{where}: literals must be a non-empty list")
    return [_check_literal(lit, where) for lit in raw]


def compile_psb_graph(graph, *, permission_gate: bool = False,
                      policy_text: str | None = None):
    """Deterministically compile a typed attachment graph into a per-clause
    behavioral program set (v3 program space). Returns (programs,
    rejected_permission_clauses). Raises PSBInvalid on rule violations.

    permission_gate=True (arm H2): compiled PERMISSION clauses are rejected
    (dropped, recorded) when the policy text carries no frozen positive
    permission evidence. Never remapped."""
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) \
            or not isinstance(graph.get("edges"), list):
        raise PSBInvalid("graph must be an object with nodes and edges arrays")
    by_id: dict[str, dict] = {}
    for node in graph["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise PSBInvalid("every node needs a string id")
        if node["id"] in by_id:
            raise PSBInvalid(f"duplicate node id {node['id']!r}")
        by_id[node["id"]] = node
    regulated_ids = [nid for nid, node in by_id.items()
                     if node.get("type") == "REGULATED"]

    incoming: dict[str, dict[str, list]] = {rid: {} for rid in regulated_ids}
    for edge in graph["edges"]:
        if not isinstance(edge, dict):
            raise PSBInvalid("every edge must be an object")
        etype, src, dst = edge.get("type"), edge.get("from"), edge.get("to")
        if etype not in _EDGE_FROM_TYPE:
            raise PSBInvalid(f"unknown edge type {etype!r}")
        if src not in by_id or dst not in by_id:
            raise PSBInvalid("edge references an unknown node id")
        if dst not in incoming:
            raise PSBInvalid(f"{etype} target must be a REGULATED node")
        if by_id[src].get("type") != _EDGE_FROM_TYPE[etype]:
            raise PSBInvalid(f"{etype} must start at a "
                             f"{_EDGE_FROM_TYPE[etype]} node")
        if etype == "QUALIFIES" and by_id[src].get("kind") == "PROVENANCE":
            raise PSBInvalid("QUALIFIES cannot bind a PROVENANCE qualifier; "
                             "use SOURCE_OF")
        if etype == "SOURCE_OF" and by_id[src].get("kind") != "PROVENANCE":
            raise PSBInvalid("SOURCE_OF requires a PROVENANCE qualifier")
        incoming[dst].setdefault(etype, []).append(src)

    programs = []
    for rid in regulated_ids:
        node = by_id[rid]
        regs = incoming[rid].get("REGULATES", [])
        if len(regs) != 1:
            raise PSBInvalid(f"{rid}: exactly one REGULATES edge is required")
        modality = by_id[regs[0]].get("value")
        if modality not in ("PERMISSION", "PROHIBITION", "REQUIREMENT"):
            raise PSBInvalid(f"{rid}: regulating MODALITY has no value")
        atoms = _typed_literals(node.get("atoms"), f"{rid}.atoms")

        def _one(etype: str, what: str):
            sources = incoming[rid].get(etype, [])
            if len(sources) > 1:
                raise PSBInvalid(f"{rid}: at most one {what} may bind")
            return by_id[sources[0]] if sources else None

        activ = _one("ACTIVATES", "ACTIVATES condition")
        temporal_edge = None
        temporal_node = None
        for etype in ("FOLLOWS", "PRECEDES"):
            sources = incoming[rid].get(etype, [])
            if len(sources) > 1:
                raise PSBInvalid(f"{rid}: at most one {etype} condition")
            if sources:
                if temporal_node is not None:
                    raise PSBInvalid(f"{rid}: PRECEDES and FOLLOWS cannot "
                                     "bind the same clause")
                temporal_edge, temporal_node = etype, by_id[sources[0]]
        exception = _one("EXEMPTS", "EXCEPTION")
        actor = _one("ACTOR_OF", "ACTOR")
        qualifiers = {}
        for etype in ("QUALIFIES", "SOURCE_OF"):
            for src in incoming[rid].get(etype, []):
                kind = by_id[src].get("kind")
                if kind in qualifiers:
                    raise PSBInvalid(f"{rid}: at most one {kind} qualifier")
                qualifiers[kind] = by_id[src]

        conds: list[str] = []
        mode = None
        temporal = "NONE"
        strengths = []
        for cond in (activ, temporal_node):
            if cond is None:
                continue
            literals = _typed_literals(cond.get("literals"),
                                       f"{cond['id']}.literals")
            cmode = cond.get("mode")
            if cmode not in ("ALL", "ANY"):
                raise PSBInvalid(f"{cond['id']}: mode must be ALL or ANY")
            if mode is not None and mode != cmode:
                raise PSBInvalid(f"{rid}: condition modes disagree")
            mode = cmode
            strength = cond.get("strength")
            if strength not in ("SUFFICIENT", "NECESSARY", "EXACTLY"):
                raise PSBInvalid(f"{cond['id']}: strength is required")
            strengths.append(strength)
            if cond is activ:
                conds.extend(literals)
            else:
                for lit in literals:
                    base = lit[1:] if lit.startswith("!") else lit
                    if not base.startswith("event:"):
                        raise PSBInvalid(f"{cond['id']}: {temporal_edge} "
                                         "requires event: atoms only")
                if temporal_edge == "FOLLOWS":
                    conds.extend(literals)
                    temporal = "AFTER"
                else:
                    conds.extend("!" + lit for lit in literals)
                    temporal = "BEFORE"
        if exception is not None:
            exc_lits = _typed_literals(exception.get("literals"),
                                       f"{exception['id']}.literals")
            exc_mode = exception.get("mode")
            if exc_mode not in ("ALL", "ANY"):
                raise PSBInvalid(f"{exception['id']}: mode must be ALL or ANY")
        else:
            exc_lits, exc_mode = [], "ALL"
        if modality == "REQUIREMENT" and exception is not None \
                and (activ is not None or temporal_node is not None):
            raise PSBInvalid(f"{rid}: REQUIREMENT cannot combine a condition "
                             "with an exception (frozen envelope)")
        if actor is not None:
            atom = actor.get("atom")
            if not isinstance(atom, str) or not atom.startswith("actor:"):
                raise PSBInvalid(f"{actor['id']}: ACTOR atom must be actor:x")
            conds.append(atom)
            if actor.get("exclusive") not in (True, False):
                raise PSBInvalid(f"{actor['id']}: exclusive must be boolean")
        identity_value = provenance_value = quantifier_value = None
        if "IDENTITY" in qualifiers:
            identity_value = qualifiers["IDENTITY"].get("value")
            if not isinstance(identity_value, str) \
                    or not identity_value.startswith("identity:"):
                raise PSBInvalid("IDENTITY qualifier value must be identity:x")
            conds.append(identity_value)
        if "PROVENANCE" in qualifiers:
            provenance_value = qualifiers["PROVENANCE"].get("value")
            if not isinstance(provenance_value, str) \
                    or not provenance_value.startswith("evidence:"):
                raise PSBInvalid("PROVENANCE value must be evidence:x")
            conds.append(provenance_value)
        if "QUANTIFIER" in qualifiers:
            quantifier_value = qualifiers["QUANTIFIER"].get("value")
            if not isinstance(quantifier_value, str) or not quantifier_value:
                raise PSBInvalid("QUANTIFIER value must be a non-empty string")

        gated = (activ is not None or temporal_node is not None
                 or actor is not None or identity_value is not None
                 or provenance_value is not None)
        necessary = ("NECESSARY" in strengths
                     or (actor is not None and actor.get("exclusive") is True)
                     or identity_value is not None or provenance_value is not None)
        if modality == "REQUIREMENT" and exception is not None:
            relation = "UNLESS"
        elif "EXACTLY" in strengths:
            relation = "IF_AND_ONLY_IF"
        elif necessary:
            relation = "ONLY_IF"
        elif gated:
            relation = "IF"
        else:
            relation = "UNCONDITIONAL"
        programs.append({
            "modality": modality, "relation": relation,
            "target_clauses": [sorted(atoms)],
            "condition_literals": sorted(set(conds)),
            "condition_mode": mode or "ALL",
            "exception_literals": sorted(set(exc_lits)),
            "exception_mode": exc_mode,
            "temporal": temporal, "actor": "assistant",
            "regulated_kind": "ACTION", "facet": "primary",
            "identity": identity_value or "ANY",
            "provenance": "TOOL_RESULT" if provenance_value else "ANY",
            "quantification": quantifier_value or "ALL",
        })

    rejected = []
    if permission_gate:
        evidence = positive_permission_evidence(policy_text or "")
        if not evidence["found"]:
            kept = []
            for program in programs:
                if program["modality"] == "PERMISSION":
                    rejected.append({"target_clauses": program["target_clauses"],
                                     "reason": "no_positive_permission_evidence"})
                else:
                    kept.append(program)
            programs = kept
    return programs, rejected


# ------------------------------------------------------- composed evaluation

def composed_verdict(programs, facts) -> str:
    """VIOLATION if any clause program yields VIOLATION, else PERMITTED if
    any yields PERMITTED, else NO_VIOLATION. A single-program list composes
    to exactly the v3 verdict (H0 scoring continuity)."""
    verdicts = [evaluate_v3_program(program, facts) for program in programs]
    if "VIOLATION" in verdicts:
        return "VIOLATION"
    if "PERMITTED" in verdicts:
        return "PERMITTED"
    return "NO_VIOLATION"


def generate_worlds_for_sets(admissible_sets, atom_catalog=None) -> list:
    """Deterministic combined-surface worlds for a program-set gold: the
    union target/condition/exception fact patterns of every gold program,
    each world carrying the composed verdict of the primary admissible set
    (alternative admissible sets contribute alternative_expected when they
    differ). Deduped by facts; capped at 96 worlds (deterministic order)."""
    every_program = [program for admissible in admissible_sets
                     for program in admissible]
    if not every_program:
        return [{"facts": [], "expected": "NO_VIOLATION"}]
    combined = {
        "target_clauses": [list(clause) for program in every_program
                           for clause in program["target_clauses"]],
        "condition_literals": sorted({lit for program in every_program
                                      for lit in program["condition_literals"]}),
        "exception_literals": sorted({lit for program in every_program
                                      for lit in program["exception_literals"]}),
    }
    worlds, seen = [], {}
    for tpat in _clause_fact_patterns(combined["target_clauses"]):
        for cpat in _literal_fact_patterns(combined["condition_literals"]):
            for epat in _literal_fact_patterns(combined["exception_literals"]):
                facts = _pattern_facts(tpat, cpat, epat)
                key = " ".join(sorted(facts))
                if key in seen:
                    continue
                expected = composed_verdict(admissible_sets[0], facts)
                alternatives = sorted({composed_verdict(admissible, facts)
                                       for admissible in admissible_sets[1:]}
                                      - {expected})
                world = {"facts": sorted(facts), "expected": expected}
                if alternatives:
                    world["alternative_expected"] = alternatives
                seen[key] = world
                worlds.append(world)
                if len(worlds) >= _MAX_WORLDS_PER_CASE:
                    return worlds
    return worlds


def score_program_set(programs, worlds, admissible_sets):
    """Behavioral scoring of a compiled program set against a case's frozen
    world surface. Acceptable verdicts per fact set are the composed verdicts
    of the admissible gold sets. Returns (case_correct, per_world)."""
    fact_sets, seen = [], set()
    for world in worlds:
        key = frozenset(world["facts"])
        if key not in seen:
            seen.add(key)
            fact_sets.append(key)
    per_world, correct = [], True
    for facts in fact_sets:
        verdict = composed_verdict(programs, facts)
        acceptable = sorted({composed_verdict(admissible, facts)
                             for admissible in admissible_sets})
        ok = verdict in acceptable
        correct = correct and ok
        per_world.append({"facts": sorted(facts), "verdict": verdict,
                          "acceptable": acceptable, "match": ok})
    return correct, per_world


# ------------------------------------------------- canonical binding triples

TRIPLE_CLASSES = ("MODALITY", "CONDITION", "EXCEPTION", "ACTOR",
                  "QUALIFIER_IDENTITY", "QUALIFIER_PROVENANCE",
                  "QUALIFIER_QUANTIFIER", "CLAUSE")


def canonical_triples_graph(graph) -> set:
    """Canonical attachment triples (class, payload, target_atoms) of a PSB
    graph. PRECEDES literals are canonicalized to their compiled negated
    form so polarity is part of the CONDITION payload."""
    if not isinstance(graph, dict):
        return set()
    by_id = {node.get("id"): node for node in graph.get("nodes", [])
             if isinstance(node, dict)}
    triples = set()
    for rid, node in by_id.items():
        if node.get("type") != "REGULATED":
            continue
        atoms = frozenset(node.get("atoms") or [])
        if not atoms:
            continue
        triples.add(("CLAUSE", frozenset(), atoms))
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        etype, src, dst = edge.get("type"), edge.get("from"), edge.get("to")
        target = by_id.get(dst)
        if target is None or target.get("type") != "REGULATED":
            continue
        atoms = frozenset(target.get("atoms") or [])
        source = by_id.get(src) or {}
        if etype == "REGULATES":
            triples.add(("MODALITY", frozenset([source.get("value")]), atoms))
        elif etype == "ACTIVATES":
            triples.add(("CONDITION", frozenset(source.get("literals") or []),
                         atoms))
        elif etype == "FOLLOWS":
            triples.add(("CONDITION", frozenset(source.get("literals") or []),
                         atoms))
        elif etype == "PRECEDES":
            triples.add(("CONDITION",
                         frozenset("!" + lit
                                   for lit in source.get("literals") or []),
                         atoms))
        elif etype == "EXEMPTS":
            triples.add(("EXCEPTION", frozenset(source.get("literals") or []),
                         atoms))
        elif etype == "ACTOR_OF":
            triples.add(("ACTOR", frozenset([source.get("atom")]), atoms))
        elif etype == "QUALIFIES":
            kind = source.get("kind")
            if kind in ("IDENTITY", "QUANTIFIER"):
                triples.add((f"QUALIFIER_{kind}",
                             frozenset([source.get("value")]), atoms))
        elif etype == "SOURCE_OF":
            triples.add(("QUALIFIER_PROVENANCE",
                         frozenset([source.get("value")]), atoms))
    return triples


def canonical_triples_flat(program) -> set:
    """Canonical projection of a flat H0 program (the formal statement of
    global attachment: every gate attaches to every target clause).
    actor:/identity:/evidence: condition literals are split into their own
    triple classes; the inert identity/provenance string fields are ignored;
    quantification is projected only when it is not the default ALL."""
    if not isinstance(program, dict):
        return set()
    triples = set()
    quantification = program.get("quantification", "ALL")
    for clause in program.get("target_clauses", []):
        atoms = frozenset(clause)
        if not atoms:
            continue
        triples.add(("CLAUSE", frozenset(), atoms))
        triples.add(("MODALITY", frozenset([program.get("modality")]), atoms))
        plain, actor_lits, identity_lits, evidence_lits = [], [], [], []
        for lit in program.get("condition_literals", []):
            base = lit[1:] if lit.startswith("!") else lit
            if base.startswith("actor:"):
                actor_lits.append(lit)
            elif base.startswith("identity:"):
                identity_lits.append(lit)
            elif base.startswith("evidence:"):
                evidence_lits.append(lit)
            else:
                plain.append(lit)
        if plain:
            triples.add(("CONDITION", frozenset(plain), atoms))
        for lit in actor_lits:
            triples.add(("ACTOR", frozenset([lit]), atoms))
        for lit in identity_lits:
            triples.add(("QUALIFIER_IDENTITY", frozenset([lit]), atoms))
        for lit in evidence_lits:
            triples.add(("QUALIFIER_PROVENANCE", frozenset([lit]), atoms))
        if program.get("exception_literals"):
            triples.add(("EXCEPTION",
                         frozenset(program["exception_literals"]), atoms))
        if quantification and quantification != "ALL":
            triples.add(("QUALIFIER_QUANTIFIER",
                         frozenset([quantification]), atoms))
    return triples


def binding_prf(predicted: set, gold: set) -> dict:
    if not predicted and not gold:
        return {"precision": None, "recall": None, "f1": None}
    tp = len(predicted & gold)
    precision = tp / len(predicted) if predicted else None
    recall = tp / len(gold) if gold else None
    if precision is not None and recall is not None and precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def binding_metrics(triples_by_case: dict, gold_triples_by_case: dict) -> dict:
    """Micro precision/recall/F1 per triple class and pooled aggregate."""
    per_class = {name: {"pred": 0, "gold": 0, "match": 0}
                 for name in TRIPLE_CLASSES}
    for case_id, gold in gold_triples_by_case.items():
        pred = triples_by_case.get(case_id, set())
        for triple in pred:
            per_class[triple[0]]["pred"] += 1
            if triple in gold:
                per_class[triple[0]]["match"] += 1
        for triple in gold:
            per_class[triple[0]]["gold"] += 1
    classes = {}
    for name, counts in per_class.items():
        if counts["pred"] == 0 and counts["gold"] == 0:
            classes[name] = {"n_gold": 0, "n_pred": 0, "match": 0,
                             "precision": None, "recall": None, "f1": None}
            continue
        classes[name] = {"n_gold": counts["gold"], "n_pred": counts["pred"],
                         "match": counts["match"],
                         **binding_prf_from_counts(counts)}
    pooled = {"pred": sum(c["pred"] for c in per_class.values()),
              "gold": sum(c["gold"] for c in per_class.values()),
              "match": sum(c["match"] for c in per_class.values())}
    aggregate = binding_prf_from_counts(pooled)
    return {"per_class": classes,
            "aggregate": {"n_gold": pooled["gold"], "n_pred": pooled["pred"],
                          "match": pooled["match"], **aggregate}}


def binding_prf_from_counts(counts: dict) -> dict:
    precision = counts["match"] / counts["pred"] if counts["pred"] else None
    recall = counts["match"] / counts["gold"] if counts["gold"] else None
    if precision is not None and recall is not None and precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0 if (counts["pred"] or counts["gold"]) else None
    return {"precision": precision, "recall": recall, "f1": f1}
