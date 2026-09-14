"""DETERMINISTIC REIMPLEMENTATION of the lost policy_v3_benchmark semantics.

The original src/guardian_truth/vnext/policy_v3_benchmark.py was lost with the
previous sandbox (never committed, never pushed; see
docs/vnext/RECOVERY evidence in the repo worklog). The recovered, verbatim
benchmark sources policy_v4_benchmark.py and policy_v5_benchmark.py import:

    compile_v3_structure, evaluate_v3_program, generate_worlds,
    _distinguishing_world

from this module path. This reimplementation defines those semantics from
scratch and is frozen by git BEFORE any prediction request of the C-ALR
reimplementation study (prereg: docs/vnext/C_ALR_REIMPL_STUDY_V1.json).

Declared semantic model (static worlds):
  - A world is a set of TRUE atoms; every other catalog atom is false.
  - Literals are atom strings, optionally negated with a leading "!".
  - A target clause is "realized" when ALL of its literals hold; a structure
    is triggered when ANY clause is realized. A multi-literal clause therefore
    regulates the targets TOGETHER; separate single-literal clauses regulate
    each SEPARATELY (the together/separate scope axis).
  - condition_mode/exception_mode ALL vs ANY aggregate their literal lists
    (the coordination axis). Empty lists evaluate to True.
  - modality x relation -> verdict:
      PERMISSION/IF            : triggered+conds+not excs -> PERMITTED, else
                                 NO_VIOLATION (descriptive permission; silence
                                 about everyone else, NO_VIOLATION != PERMITTED)
      PERMISSION/ONLY_IF|IFF   : triggered+conds -> PERMITTED; triggered
                                 without conds -> VIOLATION (exclusivity);
                                 exception lifts to NO_VIOLATION
      PERMISSION/UNCONDITIONAL : triggered -> PERMITTED
      PROHIBITION (any gate)   : triggered+gate+not excs -> VIOLATION;
                                 triggered+excs -> PERMITTED (explicit
                                 permission by exception); else NO_VIOLATION
                                 (gate: UNCONDITIONAL/AND_NOT_EACH always;
                                 IF/ONLY_IF/IFF require conds; UNLESS uses
                                 exceptions as the gate)
      REQUIREMENT/UNCONDITIONAL: not triggered -> VIOLATION
      REQUIREMENT/IF           : conds and not triggered -> VIOLATION
      REQUIREMENT/ONLY_IF|IFF  : triggered without conds -> VIOLATION
  - temporal qualifiers are carried in the structure but collapse to their
    condition literals in static-world evaluation (no temporal mutation in the
    v5 benchmark is behaviorally load-bearing on its own).
  - actor roles ride on actor:* condition literals; the structure "actor"
    field is carried and inert in evaluation.
  - identity/provenance/regulated_kind/facet/quantification are carried;
    quantification NOT_BOTH rides on clause conjunction (both targets issued
    -> clause realized); AT_MOST_N rides on its state target atom.

Verdict vocabulary: VIOLATION | NO_VIOLATION | PERMITTED.
Everything here is deterministic: no LLM, no network, no RNG, no wall-clock.
"""
from __future__ import annotations

import json

VERDICTS = ("VIOLATION", "NO_VIOLATION", "PERMITTED")

MODALITIES = ("PERMISSION", "PROHIBITION", "REQUIREMENT")
RELATIONS = ("IF", "ONLY_IF", "UNLESS", "UNCONDITIONAL", "IF_AND_ONLY_IF", "AND_NOT_EACH")
MODES = ("ALL", "ANY")
TEMPORALS = ("NONE", "BEFORE", "AFTER")

_FIELD_ENUMS = {
    "modality": MODALITIES,
    "relation": RELATIONS,
    "condition_mode": MODES,
    "exception_mode": MODES,
    "temporal": TEMPORALS,
}
_CARRIED_STRINGS = ("actor", "regulated_kind", "facet", "identity", "provenance", "quantification")
_DEFAULTS = {
    "condition_literals": [],
    "exception_literals": [],
    "condition_mode": "ALL",
    "exception_mode": "ALL",
    "temporal": "NONE",
    "actor": "assistant",
    "regulated_kind": "ACTION",
    "facet": "primary",
    "identity": "ANY",
    "provenance": "ANY",
    "quantification": "ALL",
}
ATOM_PREFIXES = ("action:", "state:", "event:", "claim:", "actor:", "evidence:", "identity:")


class StructureInvalid(ValueError):
    """Raised when a structure does not satisfy the compiled schema."""


def _check_literal(lit, where: str) -> str:
    if not isinstance(lit, str) or not lit:
        raise StructureInvalid(f"{where}: literal must be a non-empty string")
    base = lit[1:] if lit.startswith("!") else lit
    if ":" not in base:
        raise StructureInvalid(f"{where}: literal must be a typed atom (prefix:name), got {lit!r}")
    return lit


def compile_v3_structure(structure: dict) -> dict:
    """Validate and canonicalize a structure into a program dict. Raises
    StructureInvalid on schema violations. Unknown extra fields are dropped
    (deterministic normalization)."""
    if not isinstance(structure, dict):
        raise StructureInvalid("structure must be an object")
    for field in ("modality", "relation", "target_clauses"):
        if field not in structure:
            raise StructureInvalid(f"missing required field {field}")
    for field, allowed in _FIELD_ENUMS.items():
        value = structure.get(field, _DEFAULTS.get(field))
        if value is None or value not in allowed:
            raise StructureInvalid(f"{field} must be one of {allowed}, got {value!r}")
    clauses = structure["target_clauses"]
    if not isinstance(clauses, list) or not clauses:
        raise StructureInvalid("target_clauses must be a non-empty list")
    norm_clauses = []
    for i, clause in enumerate(clauses):
        if not isinstance(clause, list) or not clause:
            raise StructureInvalid(f"target_clauses[{i}] must be a non-empty list")
        norm_clauses.append(sorted(_check_literal(l, f"target_clauses[{i}]") for l in clause))
    program = {
        "modality": structure["modality"],
        "relation": structure["relation"],
        "target_clauses": sorted(norm_clauses),
        "condition_literals": sorted(
            _check_literal(l, "condition_literals")
            for l in (structure.get("condition_literals") or [])),
        "exception_literals": sorted(
            _check_literal(l, "exception_literals")
            for l in (structure.get("exception_literals") or [])),
        "condition_mode": structure.get("condition_mode", "ALL"),
        "exception_mode": structure.get("exception_mode", "ALL"),
        "temporal": structure.get("temporal", "NONE"),
        "actor": structure.get("actor", "assistant"),
        "regulated_kind": structure.get("regulated_kind", "ACTION"),
        "facet": structure.get("facet", "primary"),
        "identity": structure.get("identity", "ANY"),
        "provenance": structure.get("provenance", "ANY"),
        "quantification": structure.get("quantification", "ALL"),
    }
    for field in _CARRIED_STRINGS:
        if not isinstance(program[field], str):
            raise StructureInvalid(f"{field} must be a string")
    return program


def _lit_holds(lit: str, facts: frozenset) -> bool:
    if lit.startswith("!"):
        return lit[1:] not in facts
    return lit in facts


def _mode_holds(literals: list, mode: str, facts: frozenset) -> bool:
    if not literals:
        return True
    if mode == "ANY":
        return any(_lit_holds(l, facts) for l in literals)
    return all(_lit_holds(l, facts) for l in literals)


def evaluate_v3_program(program: dict, facts) -> str:
    """Deterministic behavioral verdict of a compiled program on a world
    (facts: iterable of true atoms). One of VERDICTS."""
    facts = frozenset(facts)
    modality, relation = program["modality"], program["relation"]
    realized = [all(_lit_holds(l, facts) for l in clause) for clause in program["target_clauses"]]
    triggered = any(realized)
    conds = _mode_holds(program["condition_literals"], program["condition_mode"], facts)
    # empty condition list = vacuous gate (True); empty exception list = no
    # exception applies (False) - the two empty conventions differ on purpose.
    excs = (_mode_holds(program["exception_literals"], program["exception_mode"], facts)
            if program["exception_literals"] else False)

    if modality == "PERMISSION":
        if relation == "UNLESS":
            if triggered and not excs:
                return "PERMITTED"
            return "NO_VIOLATION"
        if relation in ("ONLY_IF", "IF_AND_ONLY_IF"):
            if triggered and excs:
                return "NO_VIOLATION"
            if triggered and conds:
                return "PERMITTED"
            if triggered:
                return "VIOLATION"
            return "NO_VIOLATION"
        if relation in ("IF", "UNCONDITIONAL", "AND_NOT_EACH"):
            if triggered and conds and not excs:
                return "PERMITTED"
            return "NO_VIOLATION"

    if modality == "PROHIBITION":
        if relation == "UNLESS":
            if not triggered:
                return "NO_VIOLATION"
            return "PERMITTED" if excs else "VIOLATION"
        if relation in ("IF", "ONLY_IF", "IF_AND_ONLY_IF"):
            if not triggered or not conds:
                return "NO_VIOLATION"
            return "PERMITTED" if excs else "VIOLATION"
        if relation in ("UNCONDITIONAL", "AND_NOT_EACH"):
            if not triggered:
                return "NO_VIOLATION"
            return "PERMITTED" if excs else "VIOLATION"

    if modality == "REQUIREMENT":
        if relation == "UNCONDITIONAL":
            return "NO_VIOLATION" if triggered else "VIOLATION"
        if relation == "IF":
            return "VIOLATION" if (conds and not triggered) else "NO_VIOLATION"
        if relation in ("ONLY_IF", "IF_AND_ONLY_IF"):
            return "VIOLATION" if (triggered and not conds) else "NO_VIOLATION"
        if relation == "UNLESS":
            return "VIOLATION" if (not excs and not triggered) else "NO_VIOLATION"

    raise StructureInvalid(f"undefined combination {modality}/{relation}")


def _dedup(seq: list) -> list:
    seen, out = set(), []
    for item in seq:
        key = frozenset(item) if isinstance(item, (set, frozenset, list)) else item
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _clause_fact_patterns(clauses: list) -> list:
    """Fact patterns over target clauses: each clause full and each single
    literal; plus all-clauses-full and empty. Same surface for together and
    separate readings of the same atoms (they differ in verdicts, not facts)."""
    pats: list = []
    for clause in clauses:
        pats.append(frozenset(clause))
        for lit in clause:
            pats.append(frozenset([lit]))
    if len(clauses) > 1:
        pats.append(frozenset(l for clause in clauses for l in clause))
    pats.append(frozenset())
    return _dedup(pats)


def _literal_fact_patterns(literals: list) -> list:
    """Fact sets over a literal list: all-literals-false, each-literal-true
    (others false), all-true. For a negated literal '!x', 'literal false'
    means the base atom x IS TRUE; 'literal true' means x is absent. This is
    what makes IF vs ONLY_IF distinguishable on negated-event conditions."""
    def base(lit):
        return lit[1:] if lit.startswith("!") else lit
    pats = [frozenset(base(l) for l in literals if l.startswith("!"))]
    for lit in literals:
        if lit.startswith("!"):
            pats.append(frozenset(base(o) for o in literals
                                  if o != lit and o.startswith("!")))
        else:
            pats.append(frozenset([lit]))
    if len(literals) > 1:
        pats.append(frozenset(l for l in literals if not l.startswith("!")))
    return _dedup(pats)


def _pattern_facts(tpat, cpat, epat) -> frozenset:
    """Clause patterns are literal-sets (strip '!'); condition/exception
    patterns are already atom fact-sets."""
    facts = {l for l in tpat if not l.startswith("!")}
    facts |= cpat
    facts |= epat
    return frozenset(facts)


def generate_worlds(program: dict, atom_catalog=None) -> list:
    """Deterministic world surface for a program: cross of target / condition /
    exception fact patterns, each world carrying the program's own expected
    verdict. Deduped by facts; capped at 48 worlds (deterministic truncation
    would be recorded, never sampled)."""
    tp = _clause_fact_patterns(program["target_clauses"])
    cp = _literal_fact_patterns(program["condition_literals"])
    ep = _literal_fact_patterns(program["exception_literals"])
    worlds, seen = [], set()
    for tpat in tp:
        for cpat in cp:
            for epat in ep:
                facts = _pattern_facts(tpat, cpat, epat)
                if facts in seen:
                    continue
                seen.add(facts)
                worlds.append({"facts": sorted(facts),
                               "expected": evaluate_v3_program(program, facts)})
                if len(worlds) >= 48:
                    return worlds
    return worlds


def _distinguishing_world(program_a: dict, program_b: dict, atom_catalog=None):
    """Search the combined structured fact surface of two programs for a world
    where their verdicts differ. Returns (sorted facts, verdict_a, verdict_b)
    or None. Purely deterministic."""
    combined = {
        "target_clauses": program_a["target_clauses"] + program_b["target_clauses"],
        "condition_literals": sorted(set(program_a["condition_literals"])
                                     | set(program_b["condition_literals"])),
        "exception_literals": sorted(set(program_a["exception_literals"])
                                     | set(program_b["exception_literals"])),
    }
    tp = _clause_fact_patterns(combined["target_clauses"])
    cp = _literal_fact_patterns(combined["condition_literals"])
    ep = _literal_fact_patterns(combined["exception_literals"])
    for tpat in tp:
        for cpat in cp:
            for epat in ep:
                facts = _pattern_facts(tpat, cpat, epat)
                va = evaluate_v3_program(program_a, facts)
                vb = evaluate_v3_program(program_b, facts)
                if va != vb:
                    return (sorted(facts), va, vb)
    return None


# ---------------------------------------------------------------------------
# typed local mutation catalog (frozen for the C-ALR reimplementation study)
# ---------------------------------------------------------------------------

MUTATION_CATALOG_V1 = {
    "IF_TO_ONLY_IF": "relation IF -> ONLY_IF (permission becomes exclusive)",
    "ONLY_IF_TO_IF": "relation ONLY_IF -> IF (exclusivity dropped)",
    "IF_TO_IF_AND_ONLY_IF": "relation IF -> IF_AND_ONLY_IF",
    "ONLY_IF_TO_IF_AND_ONLY_IF": "relation ONLY_IF -> IF_AND_ONLY_IF",
    "IFF_TO_ONLY_IF": "relation IF_AND_ONLY_IF -> ONLY_IF",
    "IFF_TO_IF": "relation IF_AND_ONLY_IF -> IF",
    "COND_ANY_TO_ALL": "condition_mode ANY -> ALL",
    "COND_ALL_TO_ANY": "condition_mode ALL -> ANY",
    "EXC_ANY_TO_ALL": "exception_mode ANY -> ALL",
    "EXC_ALL_TO_ANY": "exception_mode ALL -> ANY",
    "CLAUSE_MERGE_TO_SPLIT": "one multi-literal target clause -> separate single-literal clauses",
    "CLAUSE_SPLIT_TO_MERGE": "separate single-literal target clauses -> one merged clause",
    "TEMPORAL_BEFORE_TO_AFTER": "temporal BEFORE -> AFTER",
    "TEMPORAL_AFTER_TO_BEFORE": "temporal AFTER -> BEFORE",
    "ACTOR_BEARER_SWAP": "swap the actor-bearer condition literal to the default bearer",
}


def propose_mutations(program: dict) -> list:
    """Deterministic typed local mutations applicable to a compiled program.
    Returns [{mutation_type, patch, description}]; order is catalog order."""
    proposals = []

    def add(mtype, patch):
        proposals.append({"mutation_type": mtype, "patch": patch,
                          "description": MUTATION_CATALOG_V1[mtype]})

    rel = program["relation"]
    if rel == "IF":
        add("IF_TO_ONLY_IF", {"relation": "ONLY_IF"})
        add("IF_TO_IF_AND_ONLY_IF", {"relation": "IF_AND_ONLY_IF"})
    elif rel == "ONLY_IF":
        add("ONLY_IF_TO_IF", {"relation": "IF"})
        add("ONLY_IF_TO_IF_AND_ONLY_IF", {"relation": "IF_AND_ONLY_IF"})
    elif rel == "IF_AND_ONLY_IF":
        add("IFF_TO_ONLY_IF", {"relation": "ONLY_IF"})
        add("IFF_TO_IF", {"relation": "IF"})
    if len(program["condition_literals"]) >= 2:
        m = program["condition_mode"]
        add("COND_ANY_TO_ALL" if m == "ANY" else "COND_ALL_TO_ANY",
            {"condition_mode": "ALL" if m == "ANY" else "ANY"})
    if len(program["exception_literals"]) >= 2:
        m = program["exception_mode"]
        add("EXC_ANY_TO_ALL" if m == "ANY" else "EXC_ALL_TO_ANY",
            {"exception_mode": "ALL" if m == "ANY" else "ANY"})
    clauses = program["target_clauses"]
    if len(clauses) == 1 and len(clauses[0]) >= 2:
        add("CLAUSE_MERGE_TO_SPLIT", {"target_clauses": [[l] for l in clauses[0]]})
    if len(clauses) >= 2 and all(len(c) == 1 for c in clauses):
        add("CLAUSE_SPLIT_TO_MERGE",
            {"target_clauses": [sorted(l for c in clauses for l in c)]})
    if program["temporal"] == "BEFORE":
        add("TEMPORAL_BEFORE_TO_AFTER", {"temporal": "AFTER"})
    elif program["temporal"] == "AFTER":
        add("TEMPORAL_AFTER_TO_BEFORE", {"temporal": "BEFORE"})
    if program["modality"] == "PERMISSION":
        actor_lits = [l for l in program["condition_literals"] if l.startswith("actor:")]
        # never propose the identity swap actor:assistant -> actor:assistant
        if actor_lits and actor_lits[0] != "actor:assistant":
            swapped = ["actor:assistant" if l == actor_lits[0] else l
                       for l in program["condition_literals"]]
            add("ACTOR_BEARER_SWAP", {"condition_literals": sorted(set(swapped))})
    return proposals


def apply_patch(program: dict, patch: dict) -> dict:
    """Apply a typed mutation patch to a compiled program (pure copy)."""
    out = json.loads(json.dumps(program))
    out.update(patch)
    if "condition_literals" in patch:
        out["condition_literals"] = sorted(patch["condition_literals"])
    if "target_clauses" in patch:
        out["target_clauses"] = sorted(
            sorted(c) if isinstance(c, list) else c for c in patch["target_clauses"])
    return out


def normalize_span_text(text: str) -> str:
    return " ".join((text or "").split())


def span_is_verbatim(span, policy_text: str) -> bool:
    """Machine-side grounding check: a SUPPORTED verdict only counts when its
    claimed source span appears verbatim (whitespace-normalized) in the
    policy text."""
    if not isinstance(span, str) or not span.strip():
        return False
    return normalize_span_text(span) in normalize_span_text(policy_text)


def case_world_acceptance(worlds: list) -> dict:
    """Merge the frozen world list of a case into {facts_key: acceptable
    verdict sets}. Duplicate fact sets (e.g. the appended distinguishing world)
    merge their acceptable verdicts."""
    merged: dict = {}
    for world in worlds:
        key = " ".join(sorted(world["facts"]))
        acceptable = merged.setdefault(key, {"facts": world["facts"], "acceptable": set()})
        acceptable["acceptable"].add(world["expected"])
        if world.get("alternative_expected"):
            merged[key]["acceptable"].add(world["alternative_expected"])
    return merged


def score_candidate_structure(structure: dict, worlds: list,
                              admissible_programs=None):
    """Behavioral scoring of a candidate structure against a case's frozen
    world surface. Acceptable verdicts per fact set are the verdicts of the
    case's admissible gold programs (deterministic gold join; both readings of
    ambiguous cases are acceptable). Returns (case_correct, per_world,
    program_or_None). Invalid structures are incorrect by definition (never
    re-judged by hand)."""
    try:
        program = compile_v3_structure(structure)
    except StructureInvalid as error:
        return False, [{"error": f"schema_invalid: {error}"}], None
    fact_sets, seen = [], set()
    for world in worlds:
        fs = frozenset(world["facts"])
        if fs not in seen:
            seen.add(fs)
            fact_sets.append(fs)
    if admissible_programs:
        acceptable_by_facts = {
            fs: {evaluate_v3_program(p, fs) for p in admissible_programs}
            for fs in fact_sets}
    else:
        acceptable_by_facts = {
            frozenset(entry["facts"]): set(entry["acceptable"])
            for entry in case_world_acceptance(worlds).values()}
    per_world, correct = [], True
    for fs in fact_sets:
        verdict = evaluate_v3_program(program, fs)
        acceptable = sorted(acceptable_by_facts[fs])
        ok = verdict in acceptable_by_facts[fs]
        correct = correct and ok
        per_world.append({"facts": sorted(fs), "verdict": verdict,
                          "acceptable": acceptable, "match": ok})
    return correct, per_world, program
