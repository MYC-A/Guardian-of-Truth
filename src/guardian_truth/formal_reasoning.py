"""Bounded formal and rule-application experiments, separate from row verdicts.

Source matching validates provenance, NOT semantic faithfulness of an LLM
translation. Forward closure is sound for the supplied ground implications but
is not a complete propositional/FOL solver: no contraposition, case splitting,
closed-world negation, code execution, or automatic converse is performed.
"""

from dataclasses import asdict, dataclass
import json
import re


MAX_ATOMS = 16
MAX_RULES = 8
MAX_OUTPUT_CHARS = 48_000
MAX_EVIDENCE_ITEMS = 64
MAX_EVIDENCE_CHARS = 128_000
RELATIONS = ("FOLLOWS", "CONTRADICTS", "INSUFFICIENT")
APPLICABILITIES = ("APPLIES", "NOT_APPLIES", "UNKNOWN")


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _array(items, maximum, minimum=0, unique=False):
    result = {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}
    if unique:
        result["uniqueItems"] = True
    return result


def _string(maximum, pattern=None):
    result = {"type": "string", "minLength": 1, "maxLength": maximum}
    if pattern:
        result["pattern"] = pattern
    return result


SOURCE_SCHEMA = _object({"source_id": _string(128), "quote": _string(1200)})
LITERAL_SCHEMA = _object({"atom_id": _string(3, r"^a[0-9]{1,2}$"),
                          "polarity": {"enum": ["POS", "NEG"]}})
FORMAL_SCHEMA = _object({
    "status": {"enum": ["FORMALIZED", "UNSUPPORTED"]},
    "atoms": _array(_object({
        "id": _string(3, r"^a[0-9]{1,2}$"), "text": _string(300),
        "entity_refs": _array(_string(128), 4, unique=True),
        "time_refs": _array(_string(128), 4, unique=True),
    }), MAX_ATOMS),
    "facts": _array(_object({"literal": LITERAL_SCHEMA,
                              "sources": _array(SOURCE_SCHEMA, 4, 1)}), MAX_ATOMS),
    "rules": _array(_object({
        "id": _string(2, r"^r[0-9]$"),
        "direction": {"enum": ["IF", "ONLY_IF", "IFF"]},
        "conditions": _array(LITERAL_SCHEMA, 4, 1, unique=True),
        "conclusion": LITERAL_SCHEMA,
        "sources": _array(SOURCE_SCHEMA, 4, 1),
    }), MAX_RULES),
    "query": {"anyOf": [LITERAL_SCHEMA, {"type": "null"}]},
})

_CHECK_SCHEMA = _object({
    "id": _string(64), "clause_quote": _string(600),
    "status": {"enum": ["TRUE", "FALSE", "UNKNOWN"]},
    "fact_ids": _array(_string(64), 8, unique=True),
})
APPLICABILITY_SCHEMA = _object({
    "rule": _object({"id": _string(64),
                     "direction": {"enum": ["IF", "ONLY_IF", "IFF", "UNCLEAR"]},
                     "source": SOURCE_SCHEMA}),
    "facts": _array(_object({"id": _string(64), "source": SOURCE_SCHEMA}), 8),
    "entity_scope": {"enum": ["MATCH", "MISMATCH", "UNKNOWN"]},
    "time_scope": {"enum": ["MATCH", "MISMATCH", "UNKNOWN"]},
    "conditions": _array(_CHECK_SCHEMA, 6, 1),
    "exceptions": _array(_CHECK_SCHEMA, 4),
    "applicability": {"enum": list(APPLICABILITIES)},
})


class FormalValidationError(ValueError):
    """Fixed safe error message, without model or source contents."""

    def __init__(self, category="invalid_output"):
        self.category = category
        super().__init__(f"Formal reasoning validation failed: {category}")


@dataclass(frozen=True)
class Citation:
    source_id: str
    quote: str


@dataclass(frozen=True)
class Literal:
    atom_id: str
    polarity: str

    def opposite(self):
        return Literal(self.atom_id, "NEG" if self.polarity == "POS" else "POS")


@dataclass(frozen=True)
class Atom:
    id: str
    text: str
    entity_refs: tuple[str, ...]
    time_refs: tuple[str, ...]


@dataclass(frozen=True)
class Fact:
    literal: Literal
    sources: tuple[Citation, ...]


@dataclass(frozen=True)
class Rule:
    id: str
    direction: str
    conditions: tuple[Literal, ...]
    conclusion: Literal
    sources: tuple[Citation, ...]


@dataclass(frozen=True)
class FormalProgram:
    status: str
    atoms: tuple[Atom, ...]
    facts: tuple[Fact, ...]
    rules: tuple[Rule, ...]
    query: Literal | None


@dataclass(frozen=True)
class ProofStep:
    literal: Literal
    rule_id: str | None
    premises: tuple[Literal, ...]
    sources: tuple[Citation, ...]


@dataclass(frozen=True)
class FormalResult:
    relation: str
    proof: tuple[ProofStep, ...] = ()
    conflicts: tuple[str, ...] = ()
    reason: str = "not_derived"
    scope: str = "relative_to_supplied_formalization"


@dataclass(frozen=True)
class ApplicabilityResult:
    applicability: str
    rule_id: str
    fact_ids: tuple[str, ...]
    reason: str
    scope: str = "consistency_of_supplied_application_record"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError


def _loads(raw):
    if not isinstance(raw, str) or len(raw) > MAX_OUTPUT_CHARS:
        raise FormalValidationError()
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError):
        raise FormalValidationError() from None


def _validate(value, schema):
    """Validate only the fixed JSON Schema subset above; no executable schemas."""
    if "anyOf" in schema:
        for choice in schema["anyOf"]:
            try:
                _validate(value, choice)
                return
            except FormalValidationError:
                pass
        raise FormalValidationError()
    if "enum" in schema:
        if not isinstance(value, str) or value not in schema["enum"]:
            raise FormalValidationError()
        return
    kind = schema["type"]
    if kind == "null":
        if value is not None:
            raise FormalValidationError()
    elif kind == "string":
        if (not isinstance(value, str) or not value.strip()
                or not schema["minLength"] <= len(value) <= schema["maxLength"]
                or ("pattern" in schema and not re.fullmatch(schema["pattern"], value))):
            raise FormalValidationError()
    elif kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["required"]):
            raise FormalValidationError()
        for key, sub_schema in schema["properties"].items():
            _validate(value[key], sub_schema)
    elif kind == "array":
        if not isinstance(value, list) or not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise FormalValidationError()
        for item in value:
            _validate(item, schema["items"])
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise FormalValidationError()
    else:
        raise FormalValidationError()


def _evidence(evidence):
    if not isinstance(evidence, list) or len(evidence) > MAX_EVIDENCE_ITEMS:
        raise FormalValidationError("invalid_evidence")
    sources = {}
    total = 0
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"id", "text"}:
            raise FormalValidationError("invalid_evidence")
        if (not isinstance(item["id"], str) or not item["id"].strip() or len(item["id"]) > 128
                or item["id"] in sources or not isinstance(item["text"], str)
                or not item["text"].strip()):
            raise FormalValidationError("invalid_evidence")
        total += len(item["text"])
        if total > MAX_EVIDENCE_CHARS:
            raise FormalValidationError("invalid_evidence")
        sources[item["id"]] = item["text"]
    return sources


def _citation(value, sources):
    if sources is not None:
        text = sources.get(value["source_id"])
        quote = value["quote"]
        if text is None:
            raise FormalValidationError("unknown_source")
        first = text.find(quote)
        if first < 0 or text.find(quote, first + 1) >= 0:
            raise FormalValidationError("invalid_quote")
    return Citation(**value)


def _citations(values, sources):
    result = tuple(_citation(value, sources) for value in values)
    if len(set(result)) != len(result):
        raise FormalValidationError()
    return result


def _program(payload, sources):
    _validate(payload, FORMAL_SCHEMA)
    if payload["status"] == "UNSUPPORTED":
        if any(payload[key] for key in ("atoms", "facts", "rules")) or payload["query"] is not None:
            raise FormalValidationError()
        return FormalProgram("UNSUPPORTED", (), (), (), None)
    if not payload["atoms"] or payload["query"] is None:
        raise FormalValidationError()
    atoms = tuple(Atom(item["id"], item["text"], tuple(item["entity_refs"]), tuple(item["time_refs"]))
                  for item in payload["atoms"])
    ids = {atom.id for atom in atoms}
    if len(ids) != len(atoms):
        raise FormalValidationError()

    def literal(item):
        if item["atom_id"] not in ids:
            raise FormalValidationError("unknown_atom")
        return Literal(**item)

    facts = tuple(Fact(literal(item["literal"]), _citations(item["sources"], sources))
                  for item in payload["facts"])
    if len({fact.literal for fact in facts}) != len(facts):
        raise FormalValidationError()
    rules = tuple(Rule(item["id"], item["direction"],
                       tuple(literal(condition) for condition in item["conditions"]),
                       literal(item["conclusion"]), _citations(item["sources"], sources))
                  for item in payload["rules"])
    if len({rule.id for rule in rules}) != len(rules):
        raise FormalValidationError()
    return FormalProgram("FORMALIZED", atoms, facts, rules, literal(payload["query"]))


def parse_formalization(raw: str, evidence: list[dict]) -> FormalProgram:
    """Parse a finite ground translation and verify exact source quotations.

    Entity/time references remain uninterpreted atom identity annotations. There
    is no cross-entity unification or assertion that those annotations are true.
    """
    return _program(_loads(raw), _evidence(evidence))


def solve(program: FormalProgram) -> FormalResult:
    """Compute finite signed forward closure, retaining a small proof certificate.

    ONLY_IF means conclusion -> EACH condition, never the converse. No missing
    fact becomes false. A conflict anywhere in closure makes the result unknown.
    """
    if not isinstance(program, FormalProgram):
        raise FormalValidationError()
    # Revalidate structure/bounds even for manually constructed dataclasses.
    try:
        program = _program(_loads(json.dumps(asdict(program), allow_nan=False)), None)
    except (ValueError, TypeError, RecursionError):
        raise FormalValidationError() from None
    if program.status == "UNSUPPORTED":
        return FormalResult("INSUFFICIENT", reason="unsupported_translation")
    known = {fact.literal: ProofStep(fact.literal, None, (), fact.sources) for fact in program.facts}
    implications = []
    for rule in program.rules:
        if rule.direction in ("IF", "IFF"):
            implications.append((rule.conditions, rule.conclusion, rule))
        if rule.direction in ("ONLY_IF", "IFF"):
            implications.extend(((rule.conclusion,), condition, rule) for condition in rule.conditions)
    # At most 2 * MAX_ATOMS signed literals can be added. Cyclic rules terminate.
    for _ in range(2 * MAX_ATOMS + 1):
        changed = False
        for premises, conclusion, rule in implications:
            if conclusion not in known and all(item in known for item in premises):
                known[conclusion] = ProofStep(conclusion, rule.id, premises, rule.sources)
                changed = True
        if not changed:
            break
    conflicts = tuple(sorted({item.atom_id for item in known if item.opposite() in known}))
    if conflicts:
        return FormalResult("INSUFFICIENT", conflicts=conflicts, reason="conflicting_closure")
    if program.query in known:
        target, relation = program.query, "FOLLOWS"
    elif program.query.opposite() in known:
        target, relation = program.query.opposite(), "CONTRADICTS"
    else:
        return FormalResult("INSUFFICIENT")
    proof, visited = [], set()

    def visit(item):
        if item in visited:
            return
        visited.add(item)
        step = known[item]
        for premise in step.premises:
            visit(premise)
        proof.append(step)

    visit(target)
    return FormalResult(relation, tuple(proof), reason="derived")


def evaluate_formalization(raw: str, evidence: list[dict]) -> FormalResult:
    return solve(parse_formalization(raw, evidence))


def validate_applicability(raw: str, evidence: list[dict]) -> ApplicabilityResult:
    """Check FaiRR record structure/provenance and derive its declared outcome.

    Conditions describe antecedents for a proposed conclusion. A necessary-only
    rule cannot certify that conclusion from satisfied conditions. Scope/status
    judgments and completeness of clause extraction remain model hypotheses;
    this validator does not independently prove their natural-language meaning.
    """
    payload = _loads(raw)
    _validate(payload, APPLICABILITY_SCHEMA)
    sources = _evidence(evidence)
    rule = payload["rule"]
    rule_source = _citation(rule["source"], sources)
    fact_ids = {fact["id"] for fact in payload["facts"]}
    if len(fact_ids) != len(payload["facts"]):
        raise FormalValidationError()
    for fact in payload["facts"]:
        _citation(fact["source"], sources)
    checks = payload["conditions"] + payload["exceptions"]
    if len({check["id"] for check in checks}) != len(checks):
        raise FormalValidationError()
    used = set()
    for check in checks:
        quote = check["clause_quote"]
        first = rule_source.quote.find(quote)
        if first < 0 or rule_source.quote.find(quote, first + 1) >= 0:
            raise FormalValidationError("invalid_clause_quote")
        if any(identifier not in fact_ids for identifier in check["fact_ids"]):
            raise FormalValidationError("unknown_fact")
        if check["status"] != "UNKNOWN" and not check["fact_ids"]:
            raise FormalValidationError("missing_fact_support")
        used.update(check["fact_ids"])
    scopes = (payload["entity_scope"], payload["time_scope"])
    conditions = [item["status"] for item in payload["conditions"]]
    exceptions = [item["status"] for item in payload["exceptions"]]
    if "MISMATCH" in scopes:
        outcome, reason = "NOT_APPLIES", "scope_mismatch"
    elif rule["direction"] in ("ONLY_IF", "UNCLEAR"):
        outcome, reason = "UNKNOWN", "direction_does_not_certify_conclusion"
    elif "FALSE" in conditions or "TRUE" in exceptions:
        outcome, reason = "NOT_APPLIES", "unmet_condition_or_active_exception"
    elif "UNKNOWN" in (*scopes, *conditions, *exceptions):
        outcome, reason = "UNKNOWN", "unknown_applicability"
    else:
        outcome, reason = "APPLIES", "all_recorded_checks_satisfied"
    if payload["applicability"] != outcome:
        raise FormalValidationError("inconsistent_applicability")
    return ApplicabilityResult(outcome, rule["id"], tuple(sorted(used)), reason)
