"""GRS emission-boundary refinements (final Policy cycle, development phase).

The GRS SEMANTIC HYPOTHESIS stays frozen (docs/vnext/GRS_PREREG_GATES_V1.json):
closed grounded leaves, per-clause composition, source-backed inventory,
typed operators, deterministic semantic compilation.  Only the EMISSION
BOUNDARY varies (user sections 13-20 of the final-cycle protocol):

  B1  direct textual DSL (frozen Stage A arm; sealed baseline)
  B2  per-rule structured JSON proposal + TRUSTED ASSEMBLER that builds the
      canonical AST deterministically
  B3  permissive surface DSL + DETERMINISTIC CANONICALIZER that repairs the
      observed RULE(...)-wrapper omission (one-to-one, unambiguous,
      semantics-preserving) before the frozen parser/validator/compiler

Trust rules (user sections 18-19): the canonicalizer/assembler may change
surface syntax, wrappers, brackets, field ordering and serialization.  It
may NOT change operator, target, actor, condition, exception, scope,
relation or semantic cardinality, may not invent leaves, and the FROZEN
validator always runs AFTER canonicalization/assembly (type rules, unknown
references, envelope rules unchanged).  Hallucination counters always run
on the RAW proposal.

Canonicalizer scope (minimal, evidence-driven): inside RULESET(...), a
top-level element sequence that begins with a bare modality operator
(PERMIT/PROHIBIT/REQUIRE) instead of RULE(...)/ONE_OF(...) is wrapped as
the contents of one RULE(...).  A second bare modality starts a new rule.
Nothing else is repaired; every other malformation stays invalid.

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

import re

from .policy_grs import (_MODALITY_OPS, _TOKEN_RE, GRSInvalid, ast_to_text,
                         hallucination_attempts, parse_dsl)

# ------------------------------------------------------------------ prompts

_B2_SEMANTIC_CORE = (
    "Synthesize ONE policy ruleset. You receive POLICY_TEXT and INVENTORY: "
    "grounded semantic items with neutral IDs (F# facts with kind/atom/span; "
    "M# modality markers and R# relation markers with value/span).\n"
    "CORE INVARIANT: every fact leaf in your rules MUST be an inventory fact "
    "ID (F#). You may NOT invent facts, atoms, entities or predicates. "
    "Markers (M#/R#) are evidence for your choices but are never rule "
    "references. You decide ONLY how the grounded facts compose: how many "
    "rules exist, each rule's modality, target shape, gates, condition vs "
    "exception roles, actors, temporal order, AND/OR, together/separate.\n"
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
    "-> rules=[{'operator':'PERMIT','target':'F1','gates':[{'op':'WHEN',"
    "'expr':'F2'},{'op':'EXCEPT','expr':'F3'},"
    "{'op':'ACTOR','ref':'F4'}]}].\n"
)

B2_SYNTH_TASK = (
    _B2_SEMANTIC_CORE +
    "OUTPUT FORMAT (a trusted deterministic assembler builds the canonical "
    "ruleset from your proposal; you never serialize DSL text):\n"
    "Output exactly one JSON object {\"rules\": [rule, ...]} where each rule "
    "is either\n"
    "  {\"operator\": \"PERMIT\" | \"PROHIBIT\" | \"REQUIRE\",\n"
    "   \"target\": \"F3\" | {\"together\": [\"F1\", ...]} | "
    "{\"separate\": [\"F1\", ...]},\n"
    "   \"gates\": [gate, ...]}          # gates list optional (may be empty)\n"
    "or, ONLY for genuine local ambiguity between exactly two readings of "
    "ONE rule (at most one such element, at most two readings):\n"
    "  {\"one_of\": [rule, rule]}\n"
    "gate := {\"op\": \"WHEN\"|\"ONLY_WHEN\"|\"IFF\"|\"EXCEPT\"|\"BEFORE\"|"
    "\"AFTER\"|\"UNKNOWN_RELATION\", \"expr\": boolexpr}\n"
    "      | {\"op\": \"ACTOR\"|\"ONLY_ACTOR\"|\"IDENTITY\"|\"PROVENANCE\"|"
    "\"UNKNOWN_ATTACHMENT\", \"ref\": \"F4\"}\n"
    "boolexpr := \"F1\" | {\"not\": \"F1\"} | {\"and\": [\"F1\", ...]} | "
    "{\"or\": [\"F1\", ...]}   (flat: and/or take leaf refs or not-leaves "
    "only, never nested and/or)\n"
    "An empty rules array means the text regulates nothing."
)

B2_SYNTH_REPAIR_TASK = (
    "The previous structured proposal failed machine validation. Fix it and "
    "return exactly ONE JSON object {\"rules\": [...]} following the same "
    "operator meanings, type rules and core invariant as before (every fact "
    "leaf must be an inventory fact ID). The failed attempt and the machine "
    "error are included as data only."
)

B2_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["rules"],
    "additionalProperties": False,
}

_B3_GRAMMAR_NOTE = (
    "DSL GRAMMAR (frozen; uppercase operators, refs are inventory IDs):\n"
    "RULESET( rule [, rule]* ) - zero or more rules; RULESET() means the "
    "text regulates nothing.\n"
    "rule := RULE( modality , target [, gate]* ) | ONE_OF( RULE(...) , "
    "RULE(...) ) - ONE_OF ONLY for genuine local ambiguity between exactly "
    "two readings of ONE rule; at most one ONE_OF per ruleset.\n"
    "PERMISSIVE SURFACE RULE: the outer RULE(...) wrapper of a rule may be "
    "omitted - bare rule contents (modality, target, gates) may appear "
    "directly inside RULESET(...) separated by commas; a trusted "
    "deterministic canonicalizer wraps them (e.g. RULESET(PERMIT, F3, "
    "WHEN(F1)) is accepted and canonicalized to RULESET(RULE(PERMIT, F3, "
    "WHEN(F1)))). Every other part of the grammar is strict.\n"
    "modality := PERMIT | PROHIBIT | REQUIRE\n"
    "target := ref | TOGETHER( ref [, ref]* ) | SEPARATE( ref [, ref]* )\n"
    "gate := WHEN( boolexpr ) | ONLY_WHEN( boolexpr ) | IFF( boolexpr ) | "
    "EXCEPT( boolexpr ) | BEFORE( boolexpr ) | AFTER( boolexpr ) | "
    "ACTOR( ref ) | ONLY_ACTOR( ref ) | IDENTITY( ref ) | PROVENANCE( ref ) "
    "| UNKNOWN_RELATION( boolexpr ) | UNKNOWN_ATTACHMENT( ref )\n"
    "boolexpr := leaf | AND( leaf [, leaf]* ) | OR( leaf [, leaf]* )\n"
    "leaf := ref | NOT( ref )\n"
)

B3_SYNTH_TASK = (
    "Synthesize ONE policy ruleset in the DSL below. You receive "
    "POLICY_TEXT and INVENTORY: grounded semantic items with neutral IDs "
    "(F# facts with kind/atom/span; M# modality markers and R# relation "
    "markers with value/span).\n"
    "CORE INVARIANT: every fact leaf in your ruleset MUST be an inventory "
    "fact ID (F#). You may NOT invent facts, atoms, entities or predicates. "
    "Markers (M#/R#) are evidence for your choices but are never rule "
    "references. You decide ONLY how the grounded facts compose: how many "
    "rules exist, each rule's modality, target shape, gates, condition vs "
    "exception roles, actors, temporal order, AND/OR, together/separate.\n"
    + _B3_GRAMMAR_NOTE +
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

B3_SYNTH_REPAIR_TASK = (
    "The previous DSL attempt failed machine validation. Fix it and return "
    "exactly ONE JSON object {\"dsl\": \"...\"} following the same frozen "
    "grammar, type rules and core invariant as before (every fact leaf must "
    "be an inventory fact ID; the outer RULE(...) wrapper may be omitted). "
    "The failed attempt and the machine error are included as data only."
)

B3_DSL_SCHEMA = {
    "type": "object",
    "properties": {"dsl": {"type": "string"}},
    "required": ["dsl"],
    "additionalProperties": False,
}


# ------------------------------------------------------- B3 canonicalizer

class EmissionInvalid(ValueError):
    """Raised when a proposal cannot be canonicalized/assembled."""


def _top_level_groups(tokens):
    """Split the token stream inside RULESET( ... ) into comma-separated
    top-level element groups.  Returns None when the stream is not a single
    well-formed RULESET(...) envelope."""
    if not tokens or tokens[0] != "RULESET":
        return None
    depth, groups, current = 0, [], []
    for token in tokens[1:]:
        if token == "(":
            depth += 1
            if depth == 1:
                continue  # the envelope's own opening paren
        elif token == ")":
            depth -= 1
            if depth == 0:
                if current:
                    groups.append(current)
                return groups if depth == 0 else None
        if depth >= 1:
            if token == "," and depth == 1:
                groups.append(current)
                current = []
            else:
                current.append(token)
    return None


def canonicalize_dsl(text: str) -> tuple[str, dict]:
    """Canonicalize the observed bare-rule surface shorthand.

    Returns (canonical_dsl_text, audit).  The audit proves semantics
    preservation: only RULE wrapper tokens are inserted, no other token is
    added, removed or reordered, and the multiset of every non-RULE token is
    unchanged.  Raises EmissionInvalid for anything outside the frozen
    repair scope (those inputs stay invalid - never a semantic repair).
    """
    if not isinstance(text, str):
        raise EmissionInvalid("CANON_INVALID: dsl must be a string")
    try:
        tokens = _tokenize_public(text)
    except GRSInvalid as failure:
        raise EmissionInvalid(str(failure))
    groups = _top_level_groups(tokens)
    if groups is None:
        raise EmissionInvalid("CANON_INVALID: not a single well-formed "
                              "RULESET(...) envelope")
    if not groups or all(group[0] in ("RULE", "ONE_OF") for group in groups):
        # already canonical: identity (no change at all)
        return text, {'changed': False, 'inserted_rule_wrappers': 0,
                      'bare_rules_wrapped': 0}
    # segmentation: a bare modality starts a rule; following non-rule groups
    # belong to it until the next modality / RULE / ONE_OF group
    rebuilt, open_bare, wrapped = [], None, 0
    for group in groups:
        head = group[0] if group else None
        if head in ("RULE", "ONE_OF"):
            if open_bare is not None:
                rebuilt.append(open_bare)
                open_bare = None
            rebuilt.append(group)
        elif head in _MODALITY_OPS:
            if open_bare is not None:
                rebuilt.append(open_bare)
            open_bare = group
            wrapped += 1
        else:
            if open_bare is None:
                raise EmissionInvalid(
                    f"CANON_INVALID: top-level element {group[:2]} is "
                    "outside the canonicalization scope")
            open_bare = open_bare + [","] + group
    if open_bare is not None:
        rebuilt.append(open_bare)

    stream = ["RULESET", "("]
    for position, rule in enumerate(rebuilt):
        if position:
            stream.append(",")
        if rule[0] in ("RULE", "ONE_OF"):
            stream.extend(rule)
        else:
            stream.extend(["RULE", "("] + rule + [")"])
    stream.append(")")
    canonical_text = _join_tokens(stream)

    # semantics-preservation proof: the token multiset delta is EXACTLY one
    # 'RULE' + one '(' + one ')' per inserted wrapper, nothing else, and
    # nothing removed - no semantic token is added, removed or reordered
    original = [t for t in tokens]
    canon_tokens = _tokenize_public(canonical_text)
    from collections import Counter
    delta = Counter(canon_tokens) - Counter(original)
    removed = Counter(original) - Counter(canon_tokens)
    wrappers = delta.get('RULE', 0)
    if removed or set(delta) - {'RULE', '(', ')'} \
            or delta.get('(', 0) != wrappers or delta.get(')', 0) != wrappers:
        raise EmissionInvalid("CANON_INVALID: canonicalization would change "
                              f"semantic tokens (added {dict(delta)}, "
                              f"removed {dict(removed)})")
    audit = {'changed': True,
             'inserted_rule_wrappers': wrappers,
             'bare_rules_wrapped': wrapped}
    return canonical_text, audit


def _tokenize_public(text):
    """grs._tokenize without relying on the private name at import time."""
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


def _join_tokens(tokens):
    """Deterministic token->text join: the result re-tokenizes to exactly
    the given token stream (whitespace is insignificant to the tokenizer)."""
    text = " ".join(tokens)
    text = text.replace(" (", "(").replace(" )", ")").replace(" ,", ",")
    return text


def parse_b3(text: str):
    """Permissive-parse entry for B3: strict frozen parse first; on the
    observed failure class, deterministic canonicalization then the SAME
    frozen parser.  Returns (ast, audit)."""
    try:
        return parse_dsl(text), {'changed': False, 'canonicalized': False}
    except GRSInvalid:
        canonical_text, audit = canonicalize_dsl(text)
        ast = parse_dsl(canonical_text)  # frozen parser on canonical text
        audit['canonicalized'] = True
        return ast, audit


# ------------------------------------------------------- B2 trusted assembly

_B2_OPERATORS = ("PERMIT", "PROHIBIT", "REQUIRE")
_B2_BOOL_GATES = ("WHEN", "ONLY_WHEN", "IFF", "EXCEPT", "BEFORE", "AFTER",
                  "UNKNOWN_RELATION")
_B2_REF_GATES = ("ACTOR", "ONLY_ACTOR", "IDENTITY", "PROVENANCE",
                 "UNKNOWN_ATTACHMENT")
_B2_GATES = _B2_BOOL_GATES + _B2_REF_GATES


def _b2_leaf(value):
    """leaf spec -> ('REF', id) | ('NOT', id)."""
    if isinstance(value, str):
        return ("REF", value)
    if isinstance(value, dict) and set(value) == {"not"} \
            and isinstance(value["not"], str):
        return ("NOT", value["not"])
    raise EmissionInvalid("B2_INVALID: leaf must be a ref string or "
                          "{'not': ref}")


def _b2_boolexpr(value):
    """boolexpr spec -> frozen AST boolexpr ('AND'|'OR'|'SINGLE', [leaves]).
    The frozen grammar has FLAT conjunctions/disjunctions of leaves; nested
    and/or is outside the frozen envelope and is rejected here (never
    silently re-associated)."""
    if isinstance(value, (str, dict)) and not (isinstance(value, dict)
                                               and set(value) <= {"and", "or"}
                                               and value):
        return ("SINGLE", [_b2_leaf(value)])
    if isinstance(value, dict) and len(value) == 1:
        if "and" in value or "or" in value:
            op = "AND" if "and" in value else "OR"
            leaves = value[op.lower()]
            if not isinstance(leaves, list) or not leaves:
                raise EmissionInvalid(f"B2_INVALID: {op} needs a non-empty "
                                      "array of leaves")
            return (op, [_b2_leaf(leaf) for leaf in leaves])
    raise EmissionInvalid("B2_INVALID: boolexpr must be a leaf ref, "
                          "{'not': ref}, {'and': [leaves]} or "
                          "{'or': [leaves]}")


def _b2_target(value):
    if isinstance(value, str):
        return ("REF", value)
    if isinstance(value, dict) and len(value) == 1:
        if "together" in value or "separate" in value:
            op = "TOGETHER" if "together" in value else "SEPARATE"
            refs = value[op.lower()]
            if not isinstance(refs, list) or not refs \
                    or not all(isinstance(r, str) for r in refs):
                raise EmissionInvalid(f"B2_INVALID: {op} refs must be a "
                                      "non-empty array of strings")
            return (op, list(refs))
    raise EmissionInvalid("B2_INVALID: target must be a ref string or "
                          "{together|separate: [refs]}")


def _b2_gate(value):
    if not isinstance(value, dict):
        raise EmissionInvalid("B2_INVALID: gate must be an object")
    op, unknown = value.get("op"), set(value) - {"op"}
    if op in _B2_BOOL_GATES:
        if unknown != {"expr"}:
            raise EmissionInvalid(f"B2_INVALID: gate {op} needs exactly "
                                  "an 'expr' field")
        return (op, _b2_boolexpr(value["expr"]))
    if op in _B2_REF_GATES:
        if unknown != {"ref"} or not isinstance(value.get("ref"), str):
            raise EmissionInvalid(f"B2_INVALID: gate {op} needs exactly a "
                                  "string 'ref' field")
        return (op, value["ref"])
    raise EmissionInvalid(f"B2_INVALID: unknown gate op {op!r} "
                          f"(allowed: {', '.join(_B2_GATES)})")


def _b2_rule(value):
    if not isinstance(value, dict):
        raise EmissionInvalid("B2_INVALID: rule must be an object")
    keys = set(value)
    if keys == {"one_of"}:
        readings = value["one_of"]
        if not isinstance(readings, list) or len(readings) != 2:
            raise EmissionInvalid("B2_INVALID: one_of needs exactly two "
                                  "readings")
        return ("ONE_OF", _b2_rule(readings[0]), _b2_rule(readings[1]))
    if not {"operator", "target"} <= keys or not keys <= {"operator", "target",
                                                          "gates"}:
        raise EmissionInvalid("B2_INVALID: rule needs operator+target"
                              "(+gates) fields only")
    operator = value["operator"]
    if operator not in _B2_OPERATORS:
        raise EmissionInvalid(f"B2_INVALID: operator must be one of "
                              f"{_B2_OPERATORS}, got {operator!r}")
    gates_value = value.get("gates", [])
    if not isinstance(gates_value, list):
        raise EmissionInvalid("B2_INVALID: gates must be an array")
    return ("RULE", operator, _b2_target(value["target"]),
            [_b2_gate(gate) for gate in gates_value])


def assemble_b2(value):
    """Trusted deterministic assembler: structured proposal -> canonical
    ruleset AST (same AST shape the frozen DSL parser produces).  The FROZEN
    validator must still run on the assembled AST afterwards."""
    if not isinstance(value, dict) or set(value) != {"rules"} \
            or not isinstance(value["rules"], list):
        raise EmissionInvalid("B2_INVALID: proposal must be exactly "
                              "{\"rules\": [...]}")
    rules = [_b2_rule(item) for item in value["rules"]]
    return ("RULESET", rules)


def b2_hallucination_attempts(value, inventory: dict) -> dict:
    """Mirror of the frozen hallucination counters for structured proposals:
    counts ref-shaped strings and ALLCAPS operator words anywhere in the
    RAW proposal JSON that are not inventory IDs / frozen words."""
    known = {fact["id"] for fact in inventory["facts"]}
    known |= {marker["id"] for marker in inventory["markers"]}
    frozen_words = set(_B2_OPERATORS) | set(_B2_GATES) | {
        "RULESET", "RULE", "ONE_OF", "AND", "OR", "NOT", "TOGETHER",
        "SEPARATE", "op", "operator", "target", "gates", "rules", "expr",
        "ref", "leaf", "not", "and", "or", "together", "separate", "one_of"}

    def walk(node, refs, operators):
        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, refs, operators)
        elif isinstance(node, list):
            for child in node:
                walk(child, refs, operators)
        elif isinstance(node, str):
            for token in re.findall(r"\b[FMRS]\d+\b", node):
                refs.append(token)
            for token in re.findall(r"\b[A-Z][A-Z_]{2,}\b", node):
                operators.append(token)

    refs: list = []
    operators: list = []
    walk(value, refs, operators)
    unknown_refs = [token for token in refs if token not in known]
    unknown_ops = [token for token in operators if token not in frozen_words]
    return {"unknown_reference_attempts": len(unknown_refs),
            "unknown_reference_examples": sorted(set(unknown_refs))[:8],
            "out_of_grammar_operator_attempts": len(unknown_ops),
            "out_of_grammar_operator_examples": sorted(set(unknown_ops))[:8],
            "free_text_leaf_attempts": 0}


def compile_b2(value, inventory: dict):
    """Assemble + frozen-validate + frozen-compile.  Returns
    (alternatives, dropped, audit) where audit carries the canonical DSL
    text of the assembled AST (for the record)."""
    ast = assemble_b2(value)
    from .policy_grs import (compile_ruleset_ast, validate_ruleset_ast)
    validate_ruleset_ast(ast, inventory)
    alternatives, dropped = compile_ruleset_ast(ast, inventory)
    return alternatives, dropped, {'canonical_dsl': ast_to_text(ast)}


def compile_b3(dsl_text: str, inventory: dict):
    """Permissive-parse + frozen-validate + frozen-compile.  Returns
    (alternatives, dropped, audit)."""
    ast, audit = parse_b3(dsl_text)
    from .policy_grs import compile_ruleset_ast, validate_ruleset_ast
    validate_ruleset_ast(ast, inventory)
    alternatives, dropped = compile_ruleset_ast(ast, inventory)
    return alternatives, dropped, audit
