"""Bounded typed rule formalization with proof-carrying source references.

The language deliberately is not a general logic DSL.  Models may select only
catalogue references and a small fixed set of operators.  Validation proves
shape, typing and provenance properties of the returned object; it does *not*
prove that the natural-language rule was translated faithfully.
"""

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from itertools import product
import json
import math
from typing import Any

from .typed_catalog import CatalogItem, TypedCatalog


MAX_NODES = 12
MAX_CHILDREN = 3
MAX_REFS = 3
MAX_SUPPORT = 4
MAX_OUTPUT_CHARS = 48_000
NODE_IDS = tuple(f"n{i}" for i in range(MAX_NODES))
RELATIONS = ("IF", "ONLY_IF", "IFF", "UNCONDITIONAL")
EFFECTS = ("ASSERTED", "PERMITTED", "PROHIBITED", "REQUIRED")
OPERATORS = (
    "REF", "IS_TRUE", "FIELD_EQUALS", "VALUE_OF", "IS_PAST", "COUNT",
    "EXISTS", "SAME_ENTITY", "EQ", "NE", "LT", "LE", "GT", "GE",
    "BEFORE", "AFTER", "AND", "OR", "NOT",
)
FEATURES = {
    "modality": ("NONE", "MAY", "SHOULD", "MUST"),
    "quantifier": ("NONE", "SOME", "ANY", "ALL"),
    "causality": ("NONE", "RELATED", "CONTRIBUTES", "CAUSES"),
    "strength": ("NONE", "POSSIBLE", "LIKELY", "CERTAIN"),
    "condition": ("NONE", "NECESSARY", "SUFFICIENT", "BOTH"),
}


class TypedFormalizationError(ValueError):
    """A safe fixed-category error which never includes untrusted content."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(f"Typed formalization failed: {category}")


@dataclass(frozen=True)
class TypedNode:
    id: str
    op: str
    refs: tuple[str, ...]
    children: tuple[str, ...]
    support_ids: tuple[str, ...]


@dataclass(frozen=True)
class SemanticFeatures:
    modality: str
    quantifier: str
    causality: str
    strength: str
    condition: str


@dataclass(frozen=True)
class TypedProgram:
    status: str
    relation: str
    effect: str
    nodes: tuple[TypedNode, ...]
    condition_root: str | None
    conclusion_root: str | None
    coverage_span_ids: tuple[str, ...]
    unsupported_span_ids: tuple[str, ...]
    features: SemanticFeatures


@dataclass(frozen=True)
class VerificationResult:
    status: str
    program: TypedProgram
    node_types: tuple[tuple[str, str], ...] = ()
    verification_scope: tuple[str, ...] = ()
    error_category: str | None = None


@dataclass(frozen=True)
class AmbiguityResult:
    ambiguous: bool
    witness: dict[str, Any] | None
    checked_scenarios: int
    scope: str = "bounded_catalog_domain"


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _array(items, maximum, minimum=0):
    # Length limits are enforced locally.  Keeping them out of the wire schema
    # stays inside the strict subset implemented by the current Groq backend.
    return {"type": "array", "items": items}


def schema_for_catalog(catalog: TypedCatalog) -> dict:
    """Build a dynamic schema whose references are catalogue IDs.

    Passing this schema to a backend with strict structured output is method C.
    Using the same prompt and language with ordinary JSON mode plus local
    validation is method B.  A backend that ignores strict schema constraints
    must not be reported as grammar-constrained decoding.
    """
    if not isinstance(catalog, TypedCatalog) or not catalog.items:
        raise ValueError("A non-empty typed catalog is required")
    ids = [item.id for item in catalog.items]
    spans = [item.id for item in catalog.items if item.kind == "TextSpan"]
    if not spans:
        spans = ids
    node = _object({
        "id": {"enum": list(NODE_IDS)},
        "op": {"enum": list(OPERATORS)},
        "refs": _array({"enum": ids}, MAX_REFS),
        "children": _array({"enum": list(NODE_IDS)}, MAX_CHILDREN),
        "support_ids": _array({"enum": spans}, MAX_SUPPORT, 1),
    })
    nullable_node = {"anyOf": [{"enum": list(NODE_IDS)}, {"type": "null"}]}
    return _object({
        "status": {"enum": ["FORMALIZED", "UNSUPPORTED"]},
        "relation": {"enum": list(RELATIONS)},
        "effect": {"enum": list(EFFECTS)},
        "nodes": _array(node, MAX_NODES),
        "condition_root": nullable_node,
        "conclusion_root": nullable_node,
        "coverage_span_ids": _array({"enum": spans}, MAX_SUPPORT * 2),
        "unsupported_span_ids": _array({"enum": spans}, MAX_SUPPORT * 2),
        "features": _object({name: {"enum": list(values)}
                              for name, values in FEATURES.items()}),
    })


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TypedFormalizationError("duplicate_json_key")
        result[key] = value
    return result


def _loads(raw):
    if not isinstance(raw, str) or len(raw) > MAX_OUTPUT_CHARS:
        raise TypedFormalizationError("invalid_json")
    try:
        return json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except TypedFormalizationError:
        raise
    except (ValueError, TypeError, RecursionError):
        raise TypedFormalizationError("invalid_json") from None


def _exact_keys(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def _strings(value, maximum, *, allowed=None):
    if (not isinstance(value, list) or len(value) > maximum
            or any(not isinstance(item, str) or not item for item in value)
            or len(set(value)) != len(value)):
        raise TypedFormalizationError("invalid_shape")
    if allowed is not None and any(item not in allowed for item in value):
        raise TypedFormalizationError("unknown_reference")
    return tuple(value)


def _parse(raw: str, catalog: TypedCatalog) -> TypedProgram:
    payload = _loads(raw)
    keys = ("status", "relation", "effect", "nodes", "condition_root",
            "conclusion_root", "coverage_span_ids", "unsupported_span_ids", "features")
    if not _exact_keys(payload, keys):
        raise TypedFormalizationError("invalid_shape")
    if (payload["status"] not in ("FORMALIZED", "UNSUPPORTED")
            or payload["relation"] not in RELATIONS or payload["effect"] not in EFFECTS):
        raise TypedFormalizationError("invalid_enum")
    if not isinstance(payload["nodes"], list) or len(payload["nodes"]) > MAX_NODES:
        raise TypedFormalizationError("invalid_shape")
    item_ids = {item.id for item in catalog.items}
    span_ids = {item.id for item in catalog.items if item.kind == "TextSpan"}
    nodes = []
    for value in payload["nodes"]:
        if not _exact_keys(value, ("id", "op", "refs", "children", "support_ids")):
            raise TypedFormalizationError("invalid_shape")
        if value["id"] not in NODE_IDS or value["op"] not in OPERATORS:
            raise TypedFormalizationError("invalid_enum")
        refs = _strings(value["refs"], MAX_REFS, allowed=item_ids)
        children = _strings(value["children"], MAX_CHILDREN, allowed=set(NODE_IDS))
        supports = _strings(value["support_ids"], MAX_SUPPORT, allowed=span_ids)
        if not supports:
            raise TypedFormalizationError("unsupported_condition")
        nodes.append(TypedNode(value["id"], value["op"], refs, children, supports))
    if len({node.id for node in nodes}) != len(nodes):
        raise TypedFormalizationError("duplicate_node")
    roots = (payload["condition_root"], payload["conclusion_root"])
    if any(root is not None and root not in NODE_IDS for root in roots):
        raise TypedFormalizationError("invalid_shape")
    coverage = _strings(payload["coverage_span_ids"], MAX_SUPPORT * 2, allowed=span_ids)
    unsupported = _strings(payload["unsupported_span_ids"], MAX_SUPPORT * 2, allowed=span_ids)
    features = payload["features"]
    if not _exact_keys(features, FEATURES):
        raise TypedFormalizationError("invalid_shape")
    if any(features[name] not in allowed for name, allowed in FEATURES.items()):
        raise TypedFormalizationError("invalid_enum")
    return TypedProgram(payload["status"], payload["relation"], payload["effect"],
                        tuple(nodes), *roots, coverage, unsupported,
                        SemanticFeatures(**features))


def _ref_type(item: CatalogItem) -> str:
    return {
        "Number": "NUMBER", "Date": "DATE", "State": "STATE",
        "Field": "FIELD", "Action": "ACTION", "Tool": "ACTION",
        "EntityID": "ENTITY", "Currency": "CURRENCY",
        "TextSpan": "BOOL", "FieldValue": "VALUE", "EnumValue": "VALUE",
        "PolicyActionMention": "ACTION", "Modality": "VALUE",
        "Quantifier": "VALUE", "OperatorCue": "VALUE", "FieldMention": "FIELD",
    }.get(item.kind, "VALUE")


def verify_formalization(raw: str, catalog: TypedCatalog) -> VerificationResult:
    """Parse and type-check a candidate, returning the public status taxonomy."""
    try:
        program = _parse(raw, catalog)
    except TypedFormalizationError as error:
        empty = TypedProgram("UNSUPPORTED", "UNCONDITIONAL", "ASSERTED", (), None,
                             None, (), (), SemanticFeatures("NONE", "NONE", "NONE",
                                                            "NONE", "NONE"))
        status = "UNSUPPORTED" if error.category in {
            "unknown_reference", "unsupported_condition"} else "TYPE_ERROR"
        return VerificationResult(status, empty, error_category=error.category)
    if program.status == "UNSUPPORTED":
        if program.nodes or program.condition_root is not None or program.conclusion_root is not None:
            return VerificationResult("TYPE_ERROR", program,
                                      error_category="nonempty_unsupported")
        return VerificationResult("UNSUPPORTED", program,
                                  verification_scope=("bounded_schema",))
    if not catalog.complete:
        return VerificationResult("UNRESOLVED", program,
                                  error_category="incomplete_catalog")
    by_id = {node.id: node for node in program.nodes}
    if (program.conclusion_root not in by_id
            or (program.relation != "UNCONDITIONAL" and program.condition_root not in by_id)
            or (program.relation == "UNCONDITIONAL" and program.condition_root is not None)):
        return VerificationResult("TYPE_ERROR", program, error_category="invalid_root")
    items = {item.id: item for item in catalog.items}
    types = {}
    visiting = set()

    def infer(node_id, depth=0):
        if node_id in types:
            return types[node_id]
        if node_id in visiting or depth > 3:
            raise TypedFormalizationError("cycle_or_depth")
        visiting.add(node_id)
        node = by_id.get(node_id)
        if node is None:
            raise TypedFormalizationError("unknown_node")
        child_types = tuple(infer(child, depth + 1) for child in node.children)
        ref_types = tuple(_ref_type(items[ref]) for ref in node.refs)
        if node.op == "REF":
            if len(ref_types) != 1 or child_types:
                raise TypedFormalizationError("operator_arity")
            result = ref_types[0]
        elif node.op == "IS_TRUE":
            if len(ref_types) != 1 or child_types or ref_types[0] not in {"BOOL", "STATE", "VALUE"}:
                raise TypedFormalizationError("operator_type")
            result = "BOOL"
        elif node.op == "FIELD_EQUALS":
            if len(ref_types) != 2 or child_types or ref_types[0] != "FIELD" or ref_types[1] not in {
                    "STATE", "VALUE", "NUMBER", "DATE", "ENTITY"}:
                raise TypedFormalizationError("operator_type")
            result = "BOOL"
        elif node.op == "VALUE_OF":
            if len(ref_types) != 1 or child_types or ref_types[0] != "FIELD":
                raise TypedFormalizationError("operator_type")
            name = str(items[node.refs[0]].value).lower()
            if any(token in name for token in ("date", "time")):
                result = "DATE"
            elif any(token in name for token in ("amount", "count", "number", "price", "level")):
                result = "NUMBER"
            else:
                result = "VALUE"
        elif node.op == "IS_PAST":
            if len(ref_types) != 1 or child_types or ref_types[0] != "FIELD":
                raise TypedFormalizationError("operator_type")
            result = "BOOL"
        elif node.op == "COUNT":
            if len(ref_types) != 1 or child_types or ref_types[0] not in {"ACTION", "ENTITY", "VALUE"}:
                raise TypedFormalizationError("operator_type")
            result = "NUMBER"
        elif node.op == "EXISTS":
            if len(ref_types) != 1 or child_types or ref_types[0] not in {"ACTION", "ENTITY", "VALUE", "BOOL"}:
                raise TypedFormalizationError("operator_type")
            result = "BOOL"
        elif node.op == "SAME_ENTITY":
            if not 2 <= len(ref_types) <= 3 or child_types or any(x not in {"ACTION", "ENTITY", "FIELD", "VALUE"} for x in ref_types):
                raise TypedFormalizationError("operator_type")
            result = "BOOL"
        elif node.op in {"EQ", "NE", "LT", "LE", "GT", "GE", "BEFORE", "AFTER"}:
            if ref_types or len(child_types) != 2:
                raise TypedFormalizationError("operator_arity")
            left, right = child_types
            if node.op in {"BEFORE", "AFTER"}:
                valid = (left == right == "DATE" or left == right == "ACTION")
            elif node.op in {"LT", "LE", "GT", "GE"}:
                valid = left == right == "NUMBER"
            else:
                valid = left == right or {left, right} <= {"STATE", "VALUE"}
            if not valid:
                raise TypedFormalizationError("operator_type")
            result = "BOOL"
        elif node.op in {"AND", "OR"}:
            if ref_types or not 2 <= len(child_types) <= MAX_CHILDREN or any(x != "BOOL" for x in child_types):
                raise TypedFormalizationError("operator_type")
            result = "BOOL"
        elif node.op == "NOT":
            if ref_types or child_types != ("BOOL",):
                raise TypedFormalizationError("operator_type")
            result = "BOOL"
        else:
            raise TypedFormalizationError("invalid_operator")
        visiting.remove(node_id)
        types[node_id] = result
        return result

    try:
        condition_type = "BOOL" if program.condition_root is None else infer(program.condition_root)
        conclusion_type = infer(program.conclusion_root)
        valid_conclusion = (conclusion_type == "BOOL"
                            or (conclusion_type == "ACTION" and program.effect != "ASSERTED"))
        if condition_type != "BOOL" or not valid_conclusion:
            raise TypedFormalizationError("root_type")
        reachable = set()

        def visit(node_id):
            if node_id in reachable:
                return
            reachable.add(node_id)
            for child in by_id[node_id].children:
                visit(child)

        if program.condition_root:
            visit(program.condition_root)
        visit(program.conclusion_root)
        if reachable != set(by_id):
            raise TypedFormalizationError("unreachable_node")
    except TypedFormalizationError as error:
        return VerificationResult("TYPE_ERROR", program, error_category=error.category)
    if program.unsupported_span_ids:
        return VerificationResult("UNSUPPORTED", program, tuple(sorted(types.items())),
                                  ("bounded_schema", "catalog_references", "types", "source_links"),
                                  "unsupported_condition")
    return VerificationResult("VERIFIED", program, tuple(sorted(types.items())),
                              ("bounded_schema", "catalog_references", "types", "source_links"))


def canonical_program(program: TypedProgram) -> dict:
    """Canonicalize node names and commutative operands for stability metrics."""
    by_id = {node.id: node for node in program.nodes}

    def expression(node_id):
        node = by_id[node_id]
        children = [expression(child) for child in node.children]
        if node.op in {"AND", "OR", "EQ", "NE"}:
            children.sort(key=lambda value: json.dumps(value, sort_keys=True))
        return (node.op, tuple(sorted(node.refs)), tuple(children))

    return {
        "status": program.status,
        "relation": program.relation,
        "effect": program.effect,
        "condition": expression(program.condition_root) if program.condition_root else None,
        "conclusion": expression(program.conclusion_root) if program.conclusion_root else None,
        "features": asdict(program.features),
        "unsupported": bool(program.unsupported_span_ids),
    }


def render_controlled_text(program: TypedProgram, catalog: TypedCatalog) -> str:
    """Render an AST deterministically; this is a diagnostic round trip only."""
    items = {item.id: item for item in catalog.items}
    nodes = {node.id: node for node in program.nodes}

    def ref(identifier):
        item = items[identifier]
        return f"{item.kind}[{identifier}]"

    def expr(identifier):
        node = nodes[identifier]
        args = [ref(value) for value in node.refs] + [expr(value) for value in node.children]
        if node.op == "REF":
            return args[0]
        if node.op == "NOT":
            return f"NOT ({args[0]})"
        return f"{node.op}({', '.join(args)})"

    if program.status == "UNSUPPORTED":
        return "UNSUPPORTED"
    conclusion = expr(program.conclusion_root)
    conclusion = f"{program.effect}({conclusion})"
    if program.relation == "UNCONDITIONAL":
        return conclusion
    condition = expr(program.condition_root)
    if program.relation == "IF":
        return f"IF {condition} THEN {conclusion}"
    if program.relation == "ONLY_IF":
        return f"{conclusion} ONLY IF {condition}"
    return f"{conclusion} IF AND ONLY IF {condition}"


def _literal(item):
    if item.kind == "Number":
        return item.value
    if item.kind == "Date":
        try:
            return date.fromisoformat(str(item.value)[:10])
        except ValueError:
            return None
    return None


def _evaluate(program, catalog, environment):
    items = {item.id: item for item in catalog.items}
    nodes = {node.id: node for node in program.nodes}
    memo = {}

    def value_ref(identifier):
        fixed = _literal(items[identifier])
        return fixed if fixed is not None else environment[identifier]

    def value(identifier):
        if identifier in memo:
            return memo[identifier]
        node = nodes[identifier]
        children = [value(child) for child in node.children]
        refs = [value_ref(ref) for ref in node.refs]
        if node.op == "REF": result = refs[0]
        elif node.op == "IS_TRUE": result = bool(refs[0])
        elif node.op == "FIELD_EQUALS": result = environment[node.refs[0]] == refs[1]
        elif node.op == "VALUE_OF": result = environment[node.refs[0]]
        elif node.op == "IS_PAST": result = bool(environment[node.refs[0]])
        elif node.op == "COUNT": result = environment[node.refs[0]]
        elif node.op == "EXISTS": result = bool(environment[node.refs[0]])
        elif node.op == "SAME_ENTITY": result = len(set(refs)) == 1
        elif node.op == "EQ": result = children[0] == children[1]
        elif node.op == "NE": result = children[0] != children[1]
        elif node.op == "LT": result = children[0] < children[1]
        elif node.op == "LE": result = children[0] <= children[1]
        elif node.op == "GT": result = children[0] > children[1]
        elif node.op == "GE": result = children[0] >= children[1]
        elif node.op == "BEFORE": result = children[0] < children[1]
        elif node.op == "AFTER": result = children[0] > children[1]
        elif node.op == "AND": result = all(children)
        elif node.op == "OR": result = any(children)
        elif node.op == "NOT": result = not children[0]
        else: raise TypedFormalizationError("invalid_operator")
        memo[identifier] = result
        return result

    conclusion = bool(value(program.conclusion_root))
    if program.effect == "PROHIBITED":
        conclusion = not conclusion
    if program.relation == "UNCONDITIONAL":
        return conclusion
    condition = bool(value(program.condition_root))
    if program.relation == "IF":
        return not condition or conclusion
    if program.relation == "ONLY_IF":
        return not conclusion or condition
    return condition == conclusion


def distinguishing_witness(left: TypedProgram, right: TypedProgram,
                           catalog: TypedCatalog, *, max_scenarios=4096) -> AmbiguityResult:
    """Find a small semantic counterexample by bounded deterministic enumeration."""
    if canonical_program(left) == canonical_program(right):
        return AmbiguityResult(False, None, 0)
    used = set()
    for program in (left, right):
        for node in program.nodes:
            used.update(node.refs)
    items = {item.id: item for item in catalog.items}
    numeric_literals = [item.value for item in catalog.items if item.kind == "Number"]
    date_literals = []
    for item in catalog.items:
        parsed = _literal(item)
        if isinstance(parsed, date):
            date_literals.append(parsed)
    domains = {}
    for identifier in sorted(used):
        item = items[identifier]
        if _literal(item) is not None:
            continue
        kind = _ref_type(item)
        if kind in {"ACTION", "ENTITY"}:
            domains[identifier] = tuple(sorted(set([0, 1, 2, *[max(0, int(x)) for x in numeric_literals if isinstance(x, (int, float))]])))
        elif kind == "FIELD":
            boundaries = [0, 1]
            for number in numeric_literals:
                if isinstance(number, (int, float)) and math.isfinite(number):
                    boundaries.extend((number - 1, number, number + 1))
            domains[identifier] = tuple(sorted(set(boundaries)))[:12]
        elif kind == "DATE" and date_literals:
            values = {value + timedelta(days=delta) for value in date_literals for delta in (-1, 0, 1)}
            domains[identifier] = tuple(sorted(values))
        elif kind == "STATE":
            domains[identifier] = (False, True, item.value)
        else:
            domains[identifier] = (False, True)
    names = tuple(domains)
    checked = 0
    for values in product(*(domains[name] for name in names)):
        if checked >= max_scenarios:
            return AmbiguityResult(False, None, checked, "bounded_search_exhausted")
        environment = dict(zip(names, values))
        try:
            a = _evaluate(left, catalog, environment)
            b = _evaluate(right, catalog, environment)
        except (KeyError, TypeError, ValueError):
            continue
        checked += 1
        if a != b:
            serializable = {key: value.isoformat() if isinstance(value, date) else value
                            for key, value in environment.items()}
            return AmbiguityResult(True, {"environment": serializable,
                                          "left": a, "right": b}, checked)
    return AmbiguityResult(False, None, checked)
