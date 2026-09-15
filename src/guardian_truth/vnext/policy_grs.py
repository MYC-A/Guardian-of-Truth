"""GRS - Grounded Rule Synthesis: frozen DSL grammar, parser, deterministic
validator, compiler, inventory model and prompts.

Preregistration: docs/vnext/GRS_PREREG_GATES_V1.json (frozen before the
first inference request of the GRS cycle).

Decomposition under test: one LLM is never asked to ground AND compose at
the same time.  Stage A (oracle): the synthesizer receives a correct
grounded inventory (facts with spans, plus modality/relation surface
markers) and may only compose rules over inventory fact IDs in a small
typed DSL; it cannot invent atoms, entities or predicates because every
semantic leaf is a machine-checked inventory reference.  Stage B
(end-to-end): a grounder first extracts the inventory from the policy text
choosing atoms ONLY from a supplied atom catalog (with exact spans, UNKNOWN
abstention), then the same frozen synthesizer composes over that
inventory.  A deterministic compiler maps the DSL ruleset into the SAME
v3 program space H0 uses (policy_v3_benchmark), so the frozen behavioral
evaluator semantics are unchanged; only the representation and its
compilation differ.

DSL grammar (frozen; see GRS_GRAMMAR_SPEC):
  RULESET( rule* )
  rule := RULE( modality , target , gate* )
       | ONE_OF( RULE(...) , RULE(...) )          # local ambiguity, <=1/ruleset
  modality := PERMIT | PROHIBIT | REQUIRE
  target := ref | TOGETHER( ref+ ) | SEPARATE( ref+ )
  gate := WHEN( boolexpr ) | ONLY_WHEN( boolexpr ) | IFF( boolexpr )
       | EXCEPT( boolexpr ) | BEFORE( boolexpr ) | AFTER( boolexpr )
       | ACTOR( ref ) | ONLY_ACTOR( ref ) | IDENTITY( ref ) | PROVENANCE( ref )
       | UNKNOWN_RELATION( boolexpr ) | UNKNOWN_ATTACHMENT( ref )
  boolexpr := leaf | AND( leaf+ ) | OR( leaf+ )
  leaf := ref | NOT( ref )

UNKNOWN_RELATION / UNKNOWN_ATTACHMENT gates drop the containing rule
(recorded) - abstention, never a silent semantic repair.  ONE_OF yields two
alternative program sets; behavioral scoring requires every alternative to
reproduce acceptable gold verdicts.

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

import re

from .policy_v3_benchmark import _check_literal, evaluate_v3_program
from .policy_psb import composed_verdict, generate_worlds_for_sets

# --------------------------------------------------------------------- prompts

GRS_SYNTH_TASK = (
    "Synthesize ONE policy ruleset in the frozen DSL below. You receive "
    "POLICY_TEXT and INVENTORY: grounded semantic items with neutral IDs "
    "(F# facts with kind/atom/span; M# modality markers and R# relation "
    "markers with value/span).\n"
    "CORE INVARIANT: every fact leaf in your ruleset MUST be an inventory "
    "fact ID (F#). You may NOT invent facts, atoms, entities or predicates. "
    "Markers (M#/R#) are evidence for your choices but are never rule "
    "references. You decide ONLY how the grounded facts compose: how many "
    "rules exist, each rule's modality, target shape, gates, condition vs "
    "exception roles, actors, temporal order, AND/OR, together/separate.\n"
    "DSL GRAMMAR (frozen; uppercase operators, refs are inventory IDs):\n"
    "RULESET( rule [, rule]* ) - zero or more rules; RULESET() means the "
    "text regulates nothing.\n"
    "rule := RULE( modality , target [, gate]* ) | ONE_OF( RULE(...) , "
    "RULE(...) ) - ONE_OF ONLY for genuine local ambiguity between exactly "
    "two readings of ONE rule; at most one ONE_OF per ruleset.\n"
    "modality := PERMIT | PROHIBIT | REQUIRE\n"
    "target := ref | TOGETHER( ref [, ref]* ) | SEPARATE( ref [, ref]* )\n"
    "gate := WHEN( boolexpr ) | ONLY_WHEN( boolexpr ) | IFF( boolexpr ) | "
    "EXCEPT( boolexpr ) | BEFORE( boolexpr ) | AFTER( boolexpr ) | "
    "ACTOR( ref ) | ONLY_ACTOR( ref ) | IDENTITY( ref ) | PROVENANCE( ref ) "
    "| UNKNOWN_RELATION( boolexpr ) | UNKNOWN_ATTACHMENT( ref )\n"
    "boolexpr := leaf | AND( leaf [, leaf]* ) | OR( leaf [, leaf]* )\n"
    "leaf := ref | NOT( ref )\n"
    "OPERATOR MEANINGS:\n"
    "- PERMIT: the text positively grants or allows. PROHIBIT: the text "
    "forbids or bars. REQUIRE: the text obliges. An act that is neither "
    "licensed nor forbidden is NO_VIOLATION, never permission: absence of "
    "prohibition is NOT permission.\n"
    "- WHEN(c): the rule applies while c holds (sufficient gate: if/when/"
    "whenever/while/provided that). ONLY_WHEN(c): the rule applies ONLY "
    "under c (necessary gate: only/only when/only with/only for; outside c "
    "a PERMIT/REQUIRE target done anyway is a VIOLATION). IFF(c): exactly "
    "under c (if and only if / exactly when).\n"
    "- EXCEPT(c): carve-out (unless/except/save when); never fold a "
    "carve-out into WHEN and never move an if/when gate into EXCEPT.\n"
    "- BEFORE(e)/AFTER(e): the target happens before/after event e (e must "
    "be an EVENT fact).\n"
    "- ACTOR(f): the rule is about that actor. ONLY_ACTOR(f): exclusively "
    "that actor (only X / no one but X).\n"
    "- IDENTITY(f): same-owner/identity constraint (identity fact). "
    "PROVENANCE(f): sole acceptable evidence source (evidence fact).\n"
    "- TOGETHER(a,b): the atoms are regulated as ONE joint act. SEPARATE"
    "(a,b): the atoms are regulated as independent acts within this rule.\n"
    "- NOT(f): the fact does not hold.\n"
    "- UNKNOWN_RELATION(c)/UNKNOWN_ATTACHMENT(f): use ONLY when the "
    "relation or the attachment is genuinely undeterminable; the rule is "
    "then dropped as unresolved and hurts coverage. Do not use them as a "
    "default.\n"
    "TYPE RULES (machine-validated; violations are rejected):\n"
    "- target refs: ACTION or STATE facts only. WHEN/ONLY_WHEN/IFF/EXCEPT "
    "leaves: ACTION, STATE or EVENT facts. BEFORE/AFTER leaves: EVENT facts "
    "only. ACTOR/ONLY_ACTOR: ACTOR facts. IDENTITY: IDENTITY facts. "
    "PROVENANCE: PROVENANCE facts.\n"
    "- at most one gate of each kind per rule; at most one relation gate "
    "(WHEN/ONLY_WHEN/IFF); at most one temporal gate (BEFORE or AFTER, not "
    "both); REQUIRE with both EXCEPT and a WHEN/ONLY_WHEN/IFF/BEFORE/AFTER "
    "gate is outside the frozen envelope.\n"
    "- when several gates contribute condition leaves, their top-level "
    "combinator must agree (both AND-top or both OR-top).\n"
    "Worked example (illustrative only; never reuse its atoms): POLICY 'If "
    "the night fridge is unlocked, bar staff may pour samples, unless the "
    "cellar door is alarmed.' INVENTORY F1=ACTION action:pour_samples 'pour "
    "samples', F2=STATE state:night_fridge_unlocked 'the night fridge is "
    "unlocked', F3=STATE state:cellar_door_alarmed 'the cellar door is "
    "alarmed', F4=ACTOR actor:bar_staff 'bar staff', M1=MODAL_MARKER PERMIT "
    "'may', R1=RELATION_MARKER IF 'If', R2=RELATION_MARKER UNLESS 'unless' "
    "-> RULESET(RULE(PERMIT, F1, WHEN(F2), EXCEPT(F3), ACTOR(F4))).\n"
    "Output exactly one JSON object: {\"dsl\": \"<your ruleset>\"}."
)

GRS_SYNTH_REPAIR_TASK = (
    "The previous DSL attempt failed machine validation. Fix it and return "
    "exactly ONE JSON object {\"dsl\": \"...\"} following the same frozen "
    "grammar, type rules and core invariant as before (every fact leaf must "
    "be an inventory fact ID). The failed attempt and the machine error are "
    "included as data only."
)

GRS_DSL_SCHEMA = {
    "type": "object",
    "properties": {"dsl": {"type": "string"}},
    "required": ["dsl"],
    "additionalProperties": False,
}

GRS_GROUND_TASK = (
    "Extract the grounded semantic inventory of ONE policy text. You "
    "receive POLICY_TEXT and ATOM_CATALOG (typed atoms; it also contains "
    "distractor atoms the text does not use).\n"
    "Extract:\n"
    "1. FACTS: every catalog atom the text actually uses, each with its "
    "exact supporting span copied character-for-character from POLICY_TEXT. "
    "Choose atoms ONLY from ATOM_CATALOG; never invent or modify atom "
    "strings. If you cannot confidently ground an atom, omit it - do not "
    "guess.\n"
    "2. MARKERS: surface cues present in the text:\n"
    "- modality markers: PERMIT (may, can, is allowed to, is permitted to, "
    "is free to), PROHIBIT (must not, may not, cannot, is forbidden, is "
    "barred, is not allowed, never, do not), REQUIRE (must, shall, has to, "
    "is required to, is to be).\n"
    "- relation markers: IF (if, when, whenever, while, provided that, so "
    "long as), ONLY_IF (only when, only if, only while, only with, only "
    "for, solely), IFF (exactly when, if and only if), UNLESS (unless, "
    "except, except when, save when, apart from), BEFORE (before), AFTER "
    "(after, once).\n"
    "Rules:\n"
    "- span must be an exact substring of POLICY_TEXT.\n"
    "- do NOT decide roles or attachments (which fact is a condition, "
    "exception or target, or which clause a gate belongs to) - that is NOT "
    "your task.\n"
    "- assign fact IDs F1, F2, ... in order of first appearance in the "
    "text; marker IDs M1.. for modality markers and R1.. for relation "
    "markers in order of first appearance.\n"
    "Output exactly one JSON object: {\"facts\": [{\"id\", \"atom\", "
    "\"span\"}...], \"markers\": [{\"id\", \"kind\", \"value\", \"span\"}"
    "...]} (empty arrays allowed; kind is MODAL_MARKER or RELATION_MARKER)."
)

GRS_GROUND_REPAIR_TASK = (
    "The previous inventory attempt failed machine validation. Fix it and "
    "return exactly ONE JSON object with facts and markers arrays, "
    "following the same rules as before (atoms only from ATOM_CATALOG; "
    "spans copied character-for-character from POLICY_TEXT; no roles or "
    "attachments). The failed attempt and the machine error are included "
    "as data only."
)

GRS_GROUND_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "atom": {"type": "string"},
                           "span": {"type": "string"}},
            "required": ["id", "atom", "span"],
            "additionalProperties": False}},
        "markers": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"},
                           "kind": {"type": "string",
                                    "enum": ["MODAL_MARKER", "RELATION_MARKER"]},
                           "value": {"type": "string"}, "span": {"type": "string"}},
            "required": ["id", "kind", "value", "span"],
            "additionalProperties": False}},
    },
    "required": ["facts", "markers"],
    "additionalProperties": False,
}

# ------------------------------------------------------------------- inventory

FACT_KINDS = ("ACTION", "STATE", "EVENT", "ACTOR", "IDENTITY", "PROVENANCE")
ATOM_KIND_PREFIX = {"ACTION": "action:", "STATE": "state:", "EVENT": "event:",
                    "ACTOR": "actor:", "IDENTITY": "identity:",
                    "PROVENANCE": "evidence:"}
KIND_OF_PREFIX = {prefix: kind for kind, prefix in ATOM_KIND_PREFIX.items()}
MODAL_MARKER_VALUES = ("PERMIT", "PROHIBIT", "REQUIRE")
RELATION_MARKER_VALUES = ("IF", "ONLY_IF", "IFF", "UNLESS", "BEFORE", "AFTER")

_FACT_ID_RE = re.compile(r"^F\d+$")
_MARKER_ID_RE = re.compile(r"^[MR]\d+$")


class GRSInvalid(ValueError):
    """Raised when a DSL ruleset or inventory violates the frozen rules.

    Message prefixes are machine-consumed by the failure taxonomy:
    DSL_INVALID / UNKNOWN_REFERENCE / TYPE_ERROR / GRULE / INVENTORY.
    """


def _kind_of_atom(atom: str) -> str | None:
    for prefix, kind in KIND_OF_PREFIX.items():
        if atom.startswith(prefix):
            return kind
    return None


def validate_inventory(inventory: dict, policy_text: str) -> None:
    """Deterministic well-formedness of a grounded inventory: unique IDs
    with neutral prefixes, kinds consistent with atom prefixes, marker
    values in the frozen enums, spans exact substrings of the policy text,
    and no attachment/role fields anywhere."""
    if not isinstance(inventory, dict) or set(inventory) != {"facts", "markers"}:
        raise GRSInvalid("INVENTORY: must be an object with facts and markers")
    facts, markers = inventory["facts"], inventory["markers"]
    if not isinstance(facts, list) or not isinstance(markers, list):
        raise GRSInvalid("INVENTORY: facts and markers must be arrays")
    seen: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {"id", "kind", "atom", "span"}:
            raise GRSInvalid("INVENTORY: fact fields must be exactly "
                             "id, kind, atom, span")
        fid, kind, atom, span = fact["id"], fact["kind"], fact["atom"], fact["span"]
        if not isinstance(fid, str) or not _FACT_ID_RE.fullmatch(fid):
            raise GRSInvalid(f"INVENTORY: fact id {fid!r} must be neutral F#")
        if fid in seen:
            raise GRSInvalid(f"INVENTORY: duplicate id {fid!r}")
        seen.add(fid)
        if kind not in FACT_KINDS:
            raise GRSInvalid(f"INVENTORY: bad fact kind {kind!r}")
        if not isinstance(atom, str) or _kind_of_atom(atom) != kind:
            raise GRSInvalid(f"INVENTORY: atom {atom!r} does not match kind {kind!r}")
        if not isinstance(span, str) or span not in policy_text:
            raise GRSInvalid(f"INVENTORY: span of {fid} is not an exact "
                             "substring of the policy text")
    for marker in markers:
        if not isinstance(marker, dict) or set(marker) != {"id", "kind", "value", "span"}:
            raise GRSInvalid("INVENTORY: marker fields must be exactly "
                             "id, kind, value, span")
        mid, kind, value, span = (marker["id"], marker["kind"],
                                  marker["value"], marker["span"])
        if not isinstance(mid, str) or not _MARKER_ID_RE.fullmatch(mid):
            raise GRSInvalid(f"INVENTORY: marker id {mid!r} must be M# or R#")
        if mid in seen:
            raise GRSInvalid(f"INVENTORY: duplicate id {mid!r}")
        seen.add(mid)
        if kind not in ("MODAL_MARKER", "RELATION_MARKER"):
            raise GRSInvalid(f"INVENTORY: bad marker kind {kind!r}")
        allowed = (MODAL_MARKER_VALUES if kind == "MODAL_MARKER"
                   else RELATION_MARKER_VALUES)
        if value not in allowed:
            raise GRSInvalid(f"INVENTORY: marker value {value!r} not in {allowed}")
        if not isinstance(span, str) or span not in policy_text:
            raise GRSInvalid(f"INVENTORY: span of {mid} is not an exact "
                             "substring of the policy text")


def inventory_fact_map(inventory: dict) -> dict:
    return {fact["id"]: fact for fact in inventory["facts"]}


# ------------------------------------------------------------------ DSL parser

_TOKEN_RE = re.compile(r"[()]|,|[A-Za-z_][A-Za-z0-9_]*")

_MODALITY_OPS = ("PERMIT", "PROHIBIT", "REQUIRE")
_GATE_OPS = ("WHEN", "ONLY_WHEN", "IFF", "EXCEPT", "BEFORE", "AFTER",
             "ACTOR", "ONLY_ACTOR", "IDENTITY", "PROVENANCE",
             "UNKNOWN_RELATION", "UNKNOWN_ATTACHMENT")
_REF_GATE_OPS = ("ACTOR", "ONLY_ACTOR", "IDENTITY", "PROVENANCE",
                 "UNKNOWN_ATTACHMENT")
_BOOL_GATE_OPS = ("WHEN", "ONLY_WHEN", "IFF", "EXCEPT", "BEFORE", "AFTER",
                  "UNKNOWN_RELATION")
_RELATION_GATE_OPS = ("WHEN", "ONLY_WHEN", "IFF")
_TEMPORAL_GATE_OPS = ("BEFORE", "AFTER")


def _tokenize(text: str) -> list[str]:
    tokens, position = [], 0
    for match in _TOKEN_RE.finditer(text):
        if text[position:match.start()].strip():
            raise GRSInvalid(f"DSL_INVALID: unexpected characters "
                             f"{text[position:match.start()]!r}")
        tokens.append(match.group(0))
        position = match.end()
    if text[position:].strip():
        raise GRSInvalid(f"DSL_INVALID: unexpected characters {text[position:]!r}")
    return tokens


def parse_dsl(text: str):
    """Parse DSL text into a nested-tuple AST.  Leaves are ('REF', id) /
    ('NOT', id); boolexprs are ('AND'|'OR'|'SINGLE', [leaves]); targets are
    ('REF'|'TOGETHER'|'SEPARATE', ...); rules are ('RULE', modality, target,
    [gates]) or ('ONE_OF', ruleA, ruleB); the root is ('RULESET', [rules])."""
    tokens = _tokenize(text) if isinstance(text, str) else None
    if tokens is None:
        raise GRSInvalid("DSL_INVALID: dsl must be a string")
    cursor = 0

    def peek():
        return tokens[cursor] if cursor < len(tokens) else None

    def take(expected: str | None = None) -> str:
        nonlocal cursor
        token = peek()
        if token is None:
            raise GRSInvalid(f"DSL_INVALID: unexpected end of input "
                             f"(expected {expected or 'token'})")
        if expected is not None and token != expected:
            raise GRSInvalid(f"DSL_INVALID: expected {expected!r}, got {token!r}")
        cursor += 1
        return token

    def parse_ref() -> str:
        token = take()
        if token in ("(", ")", ","):
            raise GRSInvalid(f"DSL_INVALID: expected a reference, got {token!r}")
        return token

    def parse_leaf():
        if peek() == "NOT":
            take("NOT")
            take("(")
            ref = parse_ref()
            take(")")
            return ("NOT", ref)
        return ("REF", parse_ref())

    def parse_boolexpr():
        if peek() in ("AND", "OR"):
            op = take()
            take("(")
            leaves = [parse_leaf()]
            while peek() == ",":
                take(",")
                leaves.append(parse_leaf())
            take(")")
            return (op, leaves)
        return ("SINGLE", [parse_leaf()])

    def parse_target():
        if peek() in ("TOGETHER", "SEPARATE"):
            op = take()
            take("(")
            refs = [parse_ref()]
            while peek() == ",":
                take(",")
                refs.append(parse_ref())
            take(")")
            return (op, refs)
        return ("REF", parse_ref())

    def parse_gate():
        op = peek()
        if op not in _GATE_OPS:
            raise GRSInvalid(f"DSL_INVALID: {op!r} is not a frozen gate "
                             f"operator (allowed: {', '.join(_GATE_OPS)})")
        take()
        take("(")
        if op in _REF_GATE_OPS:
            arg = parse_ref()
        else:
            arg = parse_boolexpr()
        take(")")
        return (op, arg)

    def parse_rule():
        if peek() == "ONE_OF":
            take("ONE_OF")
            take("(")
            first = parse_rule()
            take(",")
            second = parse_rule()
            take(")")
            return ("ONE_OF", first, second)
        take("RULE")
        take("(")
        modality = take()
        if modality not in _MODALITY_OPS:
            raise GRSInvalid(f"DSL_INVALID: modality must be one of "
                             f"{_MODALITY_OPS}, got {modality!r}")
        take(",")
        target = parse_target()
        gates = []
        while peek() == ",":
            take(",")
            gates.append(parse_gate())
        take(")")
        return ("RULE", modality, target, gates)

    take("RULESET")
    take("(")
    rules = []
    if peek() != ")":
        rules.append(parse_rule())
        while peek() == ",":
            take(",")
            rules.append(parse_rule())
    take(")")
    if cursor != len(tokens):
        raise GRSInvalid(f"DSL_INVALID: trailing tokens after RULESET: "
                         f"{tokens[cursor:]}")
    return ("RULESET", rules)


# -------------------------------------------------------------- AST serializer

def ast_to_text(ast) -> str:
    """Canonical DSL text of an AST (deterministic spacing)."""
    if ast[0] == "RULESET":
        return "RULESET(" + ", ".join(ast_to_text(rule) for rule in ast[1]) + ")"
    if ast[0] == "ONE_OF":
        return f"ONE_OF({ast_to_text(ast[1])}, {ast_to_text(ast[2])})"
    if ast[0] == "RULE":
        parts = [ast[1], ast_to_text(ast[2])] + [ast_to_text(g) for g in ast[3]]
        return "RULE(" + ", ".join(parts) + ")"
    if ast[0] in ("REF",):
        return ast[1]
    if ast[0] in ("TOGETHER", "SEPARATE"):
        return ast[0] + "(" + ", ".join(ast[1]) + ")"
    if ast[0] in _REF_GATE_OPS:
        return f"{ast[0]}({ast[1]})"
    if ast[0] in _BOOL_GATE_OPS:
        return f"{ast[0]}({_bool_text(ast[1])})"
    if ast[0] == "NOT":
        return f"NOT({ast[1]})"
    raise GRSInvalid(f"DSL_INVALID: unknown AST node {ast[0]!r}")


def _bool_text(node) -> str:
    if node[0] in ("AND", "OR"):
        return node[0] + "(" + ", ".join(_leaf_text(leaf) for leaf in node[1]) + ")"
    return _leaf_text(node[1][0])


def _leaf_text(leaf) -> str:
    return f"NOT({leaf[1]})" if leaf[0] == "NOT" else leaf[1]


# ------------------------------------------------------------------- validator

def _ref_kind(ref: str, facts: dict) -> str:
    fact = facts.get(ref)
    if fact is None:
        raise GRSInvalid(f"UNKNOWN_REFERENCE: {ref} is not an inventory fact ID")
    return fact["kind"]


def _check_boolexpr_leaves(node, facts, allowed_kinds, where: str) -> None:
    for leaf in node[1]:
        kind = _ref_kind(leaf[1], facts)
        if kind not in allowed_kinds:
            raise GRSInvalid(f"TYPE_ERROR: {where} leaf {leaf[1]} has kind "
                             f"{kind}; allowed {allowed_kinds}")


def validate_ruleset_ast(ast, inventory: dict) -> None:
    """Deterministic structural/type validation of a parsed ruleset against
    a grounded inventory.  Rejects; never repairs."""
    if ast[0] != "RULESET":
        raise GRSInvalid("DSL_INVALID: root must be RULESET")
    facts = inventory_fact_map(inventory)
    oneof_count = 0
    for rule in ast[1]:
        if rule[0] == "ONE_OF":
            oneof_count += 1
            if oneof_count > 1:
                raise GRSInvalid("GRULE: at most one ONE_OF per ruleset")
            for alternative in (rule[1], rule[2]):
                if alternative[0] != "RULE":
                    raise GRSInvalid("GRULE: ONE_OF alternatives must be rules")
                _validate_rule(alternative, facts)
        else:
            _validate_rule(rule, facts)


def _validate_rule(rule, facts: dict) -> None:
    _modality, target, gates = rule[1], rule[2], rule[3]
    # target types
    if target[0] == "REF":
        kinds = [_ref_kind(target[1], facts)]
    else:
        if len(target[1]) < 1:
            raise GRSInvalid("DSL_INVALID: empty target list")
        kinds = [_ref_kind(ref, facts) for ref in target[1]]
    for kind in kinds:
        if kind not in ("ACTION", "STATE"):
            raise GRSInvalid(f"TYPE_ERROR: target ref kind {kind} must be "
                             "ACTION or STATE")
    seen_ops: dict[str, int] = {}
    for gate in gates:
        op, arg = gate[0], gate[1]
        seen_ops[op] = seen_ops.get(op, 0) + 1
        if seen_ops[op] > 1:
            raise GRSInvalid(f"GRULE: gate {op} appears more than once per rule")
        if len([g for g in gates if g[0] in _RELATION_GATE_OPS]) > 1:
            raise GRSInvalid("GRULE: at most one relation gate "
                             "(WHEN/ONLY_WHEN/IFF) per rule")
        if len([g for g in gates if g[0] in _TEMPORAL_GATE_OPS]) > 1:
            raise GRSInvalid("GRULE: at most one temporal gate (BEFORE/AFTER) "
                             "per rule")
        if op in _REF_GATE_OPS:
            if op == "UNKNOWN_ATTACHMENT":
                _ref_kind(arg, facts)
            else:
                kind = _ref_kind(arg, facts)
                expected = {"ACTOR": "ACTOR", "ONLY_ACTOR": "ACTOR",
                            "IDENTITY": "IDENTITY",
                            "PROVENANCE": "PROVENANCE"}[op]
                if kind != expected:
                    raise GRSInvalid(f"TYPE_ERROR: {op} ref {arg} has kind "
                                     f"{kind}; expected {expected}")
        else:
            allowed = (("EVENT",) if op in _TEMPORAL_GATE_OPS
                       else ("ACTION", "STATE", "EVENT"))
            _check_boolexpr_leaves(arg, facts, allowed, op)
    has_relation = any(g[0] in _RELATION_GATE_OPS for g in gates)
    has_temporal = any(g[0] in _TEMPORAL_GATE_OPS for g in gates)
    has_except = any(g[0] == "EXCEPT" for g in gates)
    if rule[1] == "REQUIRE" and has_except and (has_relation or has_temporal):
        raise GRSInvalid("GRULE: REQUIRE with EXCEPT and a relation/temporal "
                         "gate is outside the frozen envelope")
    # mode agreement across condition-contributing boolexprs
    tops = {g[1][0] for g in gates
            if g[0] in _RELATION_GATE_OPS + _TEMPORAL_GATE_OPS
            and g[1][0] in ("AND", "OR")}
    if len(tops) > 1:
        raise GRSInvalid("GRULE: condition-contributing boolexprs must share "
                         "their top-level combinator")


# ------------------------------------------------------------------- compiler

_MODALITY_MAP = {"PERMIT": "PERMISSION", "PROHIBIT": "PROHIBITION",
                 "REQUIRE": "REQUIREMENT"}


def _boolexpr_literals(node, facts: dict) -> tuple[list, str | None]:
    leaves = node[1]
    literals = []
    for leaf in leaves:
        atom = facts[leaf[1]]["atom"]
        literals.append("!" + atom if leaf[0] == "NOT" else atom)
    mode = None
    if node[0] in ("AND", "OR"):
        mode = "ALL" if node[0] == "AND" else "ANY"
    return literals, mode


def compile_rule(rule, facts: dict):
    """Compile ONE rule into a v3 program dict, or None when the rule is
    dropped for an UNKNOWN_* gate (recorded by the caller).  Field mapping
    mirrors the frozen PSB compiler exactly so single-rule composition
    equals the v3 verdict."""
    if any(gate[0].startswith("UNKNOWN_") for gate in rule[3]):
        return None
    modality = _MODALITY_MAP[rule[1]]
    target = rule[2]
    if target[0] == "REF":
        clauses = [[facts[target[1]]["atom"]]]
    elif target[0] == "TOGETHER":
        clauses = [sorted(facts[ref]["atom"] for ref in target[1])]
    else:  # SEPARATE
        clauses = sorted([facts[ref]["atom"]] for ref in target[1])
    conds: list[str] = []
    mode: str | None = None
    exc_lits: list[str] = []
    exc_mode = "ALL"
    temporal = "NONE"
    necessary = False
    gated = False
    identity_value = provenance_value = None
    for gate in rule[3]:
        op, arg = gate[0], gate[1]
        if op in _RELATION_GATE_OPS or op in _TEMPORAL_GATE_OPS:
            gated = True
            literals, gate_mode = _boolexpr_literals(arg, facts)
            if gate_mode is not None:
                if mode is not None and mode != gate_mode:
                    raise GRSInvalid(f"GRULE: condition modes disagree in "
                                     f"{op}")
                mode = gate_mode
            if op in _TEMPORAL_GATE_OPS:
                for literal in literals:
                    base = literal[1:] if literal.startswith("!") else literal
                    if not base.startswith("event:"):
                        raise GRSInvalid(f"TYPE_ERROR: {op} requires event: "
                                         f"atoms only")
                temporal = "BEFORE" if op == "BEFORE" else "AFTER"
                if op == "BEFORE":
                    conds.extend("!" + lit for lit in literals)
                else:
                    conds.extend(literals)
            else:
                conds.extend(literals)
                if op in ("ONLY_WHEN", "IFF"):
                    necessary = True
        elif op == "EXCEPT":
            exc_lits, exc_mode_candidate = _boolexpr_literals(arg, facts)
            exc_mode = exc_mode_candidate or "ALL"
        elif op == "ACTOR":
            gated = True
            conds.append(facts[arg]["atom"])
        elif op == "ONLY_ACTOR":
            gated = True
            necessary = True
            conds.append(facts[arg]["atom"])
        elif op == "IDENTITY":
            gated = True
            necessary = True
            identity_value = facts[arg]["atom"]
            conds.append(identity_value)
        elif op == "PROVENANCE":
            gated = True
            necessary = True
            provenance_value = facts[arg]["atom"]
            conds.append(provenance_value)
    has_except = bool(exc_lits)
    if modality == "REQUIREMENT" and has_except and gated:
        raise GRSInvalid("GRULE: REQUIREMENT cannot combine a condition with "
                         "an exception (frozen envelope)")
    if modality == "REQUIREMENT" and has_except:
        relation = "UNLESS"
    elif any(g[0] == "IFF" for g in rule[3]):
        relation = "IF_AND_ONLY_IF"
    elif necessary:
        relation = "ONLY_IF"
    elif gated:
        relation = "IF"
    else:
        relation = "UNCONDITIONAL"
    return {
        "modality": modality, "relation": relation,
        "target_clauses": sorted(clauses),
        "condition_literals": sorted(set(conds)),
        "condition_mode": mode or "ALL",
        "exception_literals": sorted(set(exc_lits)),
        "exception_mode": exc_mode,
        "temporal": temporal, "actor": "assistant",
        "regulated_kind": "ACTION", "facet": "primary",
        "identity": identity_value or "ANY",
        "provenance": "TOOL_RESULT" if provenance_value else "ANY",
        "quantification": "ALL",
    }


def compile_ruleset_ast(ast, inventory: dict):
    """Compile a validated ruleset AST into (alternatives, dropped_rules).
    alternatives: list of program lists (len 1, or 2 for ONE_OF).
    dropped_rules: [{'reason', 'detail'}] for every rule dropped via an
    UNKNOWN_* gate (abstention record)."""
    facts = inventory_fact_map(inventory)
    rules = ast[1]
    dropped = []
    base_programs = []
    alternatives: list[list] = []
    oneof = None
    for rule in rules:
        if rule[0] == "ONE_OF":
            oneof = rule
            continue
        program = compile_rule(rule, facts)
        if program is None:
            dropped.append(_unknown_reason(rule, facts))
        else:
            base_programs.append(program)
    if oneof is None:
        alternatives = [base_programs]
    else:
        for alternative in (oneof[1], oneof[2]):
            program = compile_rule(alternative, facts)
            if program is None:
                dropped.append(_unknown_reason(alternative, facts))
                alternatives.append(list(base_programs))
            else:
                alternatives.append(base_programs + [program])
    # canonical dedup of structurally identical programs per alternative
    deduped = []
    for programs in alternatives:
        seen, kept = set(), []
        for program in programs:
            key = _program_key(program)
            if key not in seen:
                seen.add(key)
                kept.append(program)
        deduped.append(kept)
    return deduped, dropped


def _unknown_reason(rule, facts: dict) -> dict:
    unknown = [gate[0] for gate in rule[3] if gate[0].startswith("UNKNOWN_")]
    refs = sorted({leaf[1] for gate in rule[3] if gate[0] in _BOOL_GATE_OPS
                   for leaf in gate[1][1]} |
                  {gate[1] for gate in rule[3] if gate[0] in _REF_GATE_OPS} |
                  ({rule[2][1]} if rule[2][0] == "REF" else set(rule[2][1])))
    return {"reason": "+".join(unknown), "refs": refs}


def _program_key(program: dict) -> str:
    return "|".join([program["modality"], program["relation"],
                     ";".join(",".join(clause) for clause
                              in program["target_clauses"]),
                     ";".join(program["condition_literals"]),
                     program["condition_mode"],
                     ";".join(program["exception_literals"]),
                     program["exception_mode"], program["temporal"],
                     program["identity"], program["provenance"]])


def compile_dsl(dsl_text: str, inventory: dict):
    """Parse + validate + compile.  Returns (alternatives, dropped).
    Raises GRSInvalid with coded prefixes on any violation."""
    ast = parse_dsl(dsl_text)
    validate_ruleset_ast(ast, inventory)
    return compile_ruleset_ast(ast, inventory)


# --------------------------------------------------- gold authoring utilities

_GOLD_PLACEHOLDER_RE = re.compile(
    r":(?:(?:action|state|event|actor|identity|evidence):[a-z0-9_]+)")


def materialize_gold_dsl(text: str, atom_to_id: dict) -> str:
    """Deterministically replace :atom placeholders in an authored gold DSL
    string with inventory fact IDs (gold-authoring convenience only; the
    model-facing grammar accepts IDs only)."""
    def substitute(match):
        atom = match.group(0)[1:]  # strip the leading ':' placeholder marker
        if atom not in atom_to_id:
            raise GRSInvalid(f"INVENTORY: gold placeholder {atom!r} has no "
                             "inventory fact")
        return atom_to_id[atom]
    return _GOLD_PLACEHOLDER_RE.sub(substitute, text)


def gold_dsl_refs(text: str) -> set:
    """Atoms referenced by an authored gold DSL string (placeholders)."""
    return {match.group(0)[1:]
            for match in _GOLD_PLACEHOLDER_RE.finditer(text)}


# --------------------------------------------------- hallucination attempts

_REF_TOKEN_RE = re.compile(r"\b[FMRS]\d+\b")
_OPERATOR_TOKEN_RE = re.compile(r"\b[A-Z][A-Z_]{2,}\b")
_QUOTED_RE = re.compile(r"[\"'][^\"']+[\"']")
_FROZEN_WORDS = set(_GATE_OPS + _MODALITY_OPS + ("RULESET", "RULE", "ONE_OF",
                                                  "AND", "OR", "NOT",
                                                  "TOGETHER", "SEPARATE"))


def hallucination_attempts(dsl_text: str, inventory: dict) -> dict:
    """Best-effort deterministic counters of ATTEMPTED violations in raw DSL
    text (rejected attempts; compiled programs are guaranteed clean by the
    validator).  Counts: unknown-reference attempts (ref-shaped tokens not
    in the inventory), out-of-grammar operator attempts (unknown ALLCAPS
    words), free-text leaf attempts (quoted strings)."""
    if not isinstance(dsl_text, str):
        return {"unknown_reference_attempts": 0,
                "out_of_grammar_operator_attempts": 0,
                "free_text_leaf_attempts": 0}
    known = {fact["id"] for fact in inventory["facts"]}
    known |= {marker["id"] for marker in inventory["markers"]}
    refs = _REF_TOKEN_RE.findall(dsl_text)
    unknown_refs = [token for token in refs if token not in known]
    operators = [token for token in _OPERATOR_TOKEN_RE.findall(dsl_text)
                 if token not in _FROZEN_WORDS]
    return {"unknown_reference_attempts": len(unknown_refs),
            "unknown_reference_examples": sorted(set(unknown_refs))[:8],
            "out_of_grammar_operator_attempts": len(operators),
            "out_of_grammar_operator_examples": sorted(set(operators))[:8],
            "free_text_leaf_attempts": len(_QUOTED_RE.findall(dsl_text))}


# ------------------------------------------------------------------- scoring

def grs_score_prediction(alternatives, worlds, admissible_sets) -> tuple[bool, list]:
    """Behavioral scoring of compiled alternatives against the case's frozen
    world surface.  A prediction is correct iff EVERY alternative reproduces
    an acceptable verdict on every world (acceptable = composed verdicts of
    the admissible gold program sets)."""
    fact_sets, seen = [], set()
    for world in worlds:
        key = frozenset(world["facts"])
        if key not in seen:
            seen.add(key)
            fact_sets.append(key)
    per_world, correct = [], True
    for facts in fact_sets:
        acceptable = sorted({composed_verdict(admissible, facts)
                             for admissible in admissible_sets})
        verdicts = [composed_verdict(programs, facts)
                    for programs in alternatives] or [None]
        ok = all(verdict in acceptable for verdict in verdicts)
        correct = correct and ok
        per_world.append({"facts": sorted(facts),
                          "verdicts": verdicts, "acceptable": acceptable,
                          "match": ok})
    return correct, per_world


def grs_worlds(admissible_sets, atom_catalog=None) -> list:
    """World surface for a gold program set.  Non-empty golds use the
    combined PSB surface.  EMPTY gold sets (texts that regulate nothing) get
    single-atom worlds over the full supplied atom catalog (distractors
    included): a prediction that regulates ANY catalog atom is then exposed
    as VIOLATION/PERMITTED where the gold expects NO_VIOLATION."""
    every_program = [program for admissible in admissible_sets
                     for program in admissible]
    if not every_program:
        worlds = [{"facts": [], "expected": "NO_VIOLATION"}]
        for atom in sorted(set(atom_catalog or [])):
            worlds.append({"facts": [atom], "expected": "NO_VIOLATION"})
        return worlds
    return generate_worlds_for_sets(admissible_sets)
