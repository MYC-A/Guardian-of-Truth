"""Offline, explicit claim-premise checks; never a response-level verdict.

Callers bind typed predicates and structured evidence. This module deliberately
does not extract accusations from prose, interpret instructions inside evidence,
or promote a source's assertion into current world truth. All five checks are
conservative provenance/arithmetic signals pending separate integration evidence.
"""

from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from .types import Source


@dataclass(frozen=True)
class Evidence:
    source_id: str
    role: str
    source: Source
    namespace: str
    fields: dict[str, Any]
    bindings: dict[str, Any] = dataclass_field(default_factory=dict)
    field_types: dict[str, str] = dataclass_field(default_factory=dict)
    units: dict[str, str] = dataclass_field(default_factory=dict)
    kind: str = 'structured'


@dataclass(frozen=True)
class Predicate:
    claim: str
    reason_type: str
    assertion: str
    namespace: str
    field: str = ''
    value: Any = None
    bindings: dict[str, Any] = dataclass_field(default_factory=dict)
    required_bindings: tuple[str, ...] = ()
    cited_evidence_ids: tuple[str, ...] = ()
    scope: str = 'source_presence'
    arithmetic: dict[str, Any] | None = None


_EXACT = {
    'EXACT_ENTITY_EXISTS': ({'absent'}, {'entity'}),
    'EXACT_VALUE_EXISTS': ({'absent'}, {'value', 'quantity'}),
    'EXACT_ARGUMENT_CONTRADICTION': ({'not_supplied', 'mismatch'}, {'argument'}),
}
_QUANTITIES = {'amount', 'price', 'cost', 'total', 'surcharge', 'count',
               'quantity', 'balance', 'subtotal', 'duration', 'distance', 'mass'}
_UNITS = {'USD', 'EUR', 'GBP', 'RUB', 'count', 'items', 'seconds',
          'minutes', 'hours', 'bytes', 'meters', 'kilograms'}


def _scalar(value):
    return (type(value) is str and bool(value)) or _numeric(value)


def _numeric(value):
    return type(value) is int or (type(value) is float and isfinite(value))


def _equal(left, right):
    if _numeric(left) and _numeric(right):
        return Decimal(str(left)) == Decimal(str(right))
    return type(left) is type(right) is str and left == right


def _source_ok(item):
    source = item.source
    return (isinstance(source, Source) and source.document == 'prompt'
            and type(source.start) is int and type(source.end) is int
            and 0 <= source.start < source.end
            and isinstance(item.source_id, str) and bool(item.source_id)
            and isinstance(item.namespace, str) and bool(item.namespace))


def _authority(item, reason_type):
    if not _source_ok(item):
        return False
    if any(type(item.fields[key]) is not type(value) or not _equal(item.fields[key], value)
           for key, value in item.bindings.items() if key in item.fields):
        return False
    if item.role in {'user', 'tool_response', 'tool_result'}:
        return item.kind == 'structured'
    return (reason_type == 'EXACT_ENTITY_EXISTS' and item.role == 'system'
            and item.kind == 'catalog_declaration')


def _complete_bindings(predicate):
    required = predicate.required_bindings
    return (isinstance(required, tuple) and len(set(required)) == len(required)
            and all(isinstance(key, str) and key for key in required)
            and set(required) == set(predicate.bindings)
            and all(_scalar(value) for value in predicate.bindings.values()))


def _bound(predicate, item):
    return all(key in item.bindings and type(item.bindings[key]) is type(value)
               and _equal(item.bindings[key], value)
               for key, value in predicate.bindings.items())


def _ref(item, fields):
    return {'source_id': item.source_id, 'role': item.role, 'kind': item.kind,
            'document': item.source.document, 'start': item.source.start,
            'end': item.source.end, 'namespace': item.namespace,
            'fields': {key: item.fields[key] for key in fields},
            'bindings': dict(item.bindings)}


def _result(predicate, status='ABSTAIN', evidence=(), scope='none', detail=''):
    return {'claim': predicate.claim, 'det_status': status,
            'counter_evidence': list(evidence), 'reason_type': predicate.reason_type,
            'proof_scope': scope, 'detail': detail}


def _arithmetic(predicate, evidence):
    expression = predicate.arithmetic
    if (predicate.assertion != 'arithmetic_relation'
            or predicate.scope != 'arithmetic_relation'
            or not isinstance(expression, dict)):
        return _result(predicate, detail='An explicit arithmetic relation is required.')
    operation = expression.get('operation')
    comparison = expression.get('comparison')
    expected = expression.get('expected')
    unit = expression.get('unit')
    operands = expression.get('operands')
    if (operation not in {'identity', 'add', 'subtract', 'multiply'}
            or comparison not in {'eq', 'lt', 'gt'} or not _numeric(expected)
            or unit not in _UNITS or not isinstance(operands, list)
            or not 1 <= len(operands) <= 8
            or (operation == 'identity' and len(operands) != 1)
            or (operation == 'subtract' and len(operands) != 2)):
        return _result(predicate, detail='Unsupported or ambiguous arithmetic form.')
    values, units, refs = [], [], []
    for operand in operands:
        if not isinstance(operand, dict) or set(operand) != {'source_id', 'field'}:
            return _result(predicate, detail='Operands must be explicit source/field references.')
        key = operand['field']
        matches = [item for item in evidence if item.source_id == operand['source_id']]
        if not isinstance(key, str) or len(matches) != 1:
            return _result(predicate, detail='Missing or ambiguous operand source.')
        item = matches[0]
        value = item.fields.get(key)
        operand_unit = item.units.get(key)
        if (not _authority(item, predicate.reason_type)
                or item.namespace != predicate.namespace or not _bound(predicate, item)
                or item.field_types.get(key) != 'quantity'
                or key.rsplit('.', 1)[-1] not in _QUANTITIES
                or not _numeric(value) or operand_unit not in _UNITS):
            return _result(predicate, detail='Operand is not an authorized, bound safe quantity.')
        values.append(Decimal(str(value)))
        units.append(operand_unit)
        refs.append(_ref(item, [key]))
    if operation == 'multiply':
        dimensional = [item for item in units if item != 'count']
        if (unit == 'count' and dimensional) or (unit != 'count' and dimensional != [unit]):
            return _result(predicate, detail='Multiplication supports a single unit and counts only.')
    elif any(item != unit for item in units):
        return _result(predicate, detail='Units must match; no implicit conversions.')
    try:
        # Exact finite decimal arithmetic avoids binary-float tolerance decisions.
        from decimal import localcontext
        with localcontext() as context:
            context.prec = max(64, sum(len(v.as_tuple().digits) + abs(v.as_tuple().exponent)
                                       for v in values) + len(str(expected)) + 16)
            value = values[0]
            for other in values[1:]:
                if operation == 'add':
                    value += other
                elif operation == 'subtract':
                    value -= other
                elif operation == 'multiply':
                    value *= other
            right = Decimal(str(expected))
            holds = {'eq': value == right, 'lt': value < right, 'gt': value > right}[comparison]
    except (InvalidOperation, OverflowError, ValueError):
        return _result(predicate, detail='Arithmetic could not be represented safely.')
    if holds:
        return _result(predicate, detail='The supplied arithmetic relation is not contradicted.')
    return _result(predicate, 'CONTRADICTED', refs, 'explicit_arithmetic_relation_only',
                   f'Bound operands evaluate to {value} {unit}; the declared relation fails. '
                   'This does not establish that the source values are true or currently applicable.')


def check_claim(predicate: Predicate, evidence: list[Evidence]) -> dict:
    """Check an explicitly bound premise; ambiguity always returns ABSTAIN.

    Evidence roles are lower-case user/tool_response/tool_result. A system
    catalog_declaration is additionally allowed for literal entity existence.
    Namespaces and binding-field names match exactly. No prose is executed or
    interpreted. Duplicate source IDs abstain instead of choosing a record.
    """
    if not isinstance(predicate, Predicate):
        raise TypeError('predicate must be a Predicate')
    if (not isinstance(evidence, (list, tuple))
            or any(not isinstance(item, Evidence) for item in evidence)):
        return _result(predicate, detail='Typed evidence is required.')
    if (any(not isinstance(value, str) for value in (predicate.claim, predicate.reason_type,
                                                    predicate.assertion, predicate.namespace,
                                                    predicate.field, predicate.scope))
            or not isinstance(predicate.bindings, dict)
            or not isinstance(predicate.required_bindings, tuple)
            or any(not isinstance(key, str) for key in predicate.required_bindings)
            or not isinstance(predicate.cited_evidence_ids, tuple)
            or any(not isinstance(key, str) for key in predicate.cited_evidence_ids)
            or any(not isinstance(item.source_id, str)
                   or not isinstance(item.role, str) or not isinstance(item.kind, str)
                   or not isinstance(item.namespace, str)
                   or any(not isinstance(mapping, dict) for mapping in
                          (item.fields, item.bindings, item.field_types, item.units))
                   for item in evidence)):
        return _result(predicate, detail='Malformed typed predicate or evidence.')
    if (not predicate.claim or not predicate.namespace or '*' in predicate.namespace
            or not _complete_bindings(predicate)
            or len({item.source_id for item in evidence}) != len(evidence)):
        return _result(predicate, detail='Incomplete bindings or ambiguous source identities.')
    if predicate.reason_type == 'ARITHMETIC_CONTRADICTION':
        return _arithmetic(predicate, evidence)
    if predicate.reason_type == 'ENTITY_MISMATCH':
        if (predicate.assertion != 'same_entity' or predicate.scope != 'cited_binding'
                or not predicate.required_bindings or not predicate.cited_evidence_ids
                or not predicate.field):
            return _result(predicate, detail='An explicit complete cited-entity binding is required.')
        cited = [item for item in evidence if item.source_id in predicate.cited_evidence_ids]
        if len(cited) != len(set(predicate.cited_evidence_ids)):
            return _result(predicate, detail='A cited source is unavailable.')
        for item in cited:
            if (not _authority(item, predicate.reason_type)
                    or item.namespace != predicate.namespace
                    or item.field_types.get(predicate.field) != 'entity'
                    or predicate.field not in item.fields
                    or any(key not in item.bindings or not _scalar(item.bindings[key])
                           for key in predicate.required_bindings)
                    or _bound(predicate, item)):
                return _result(predicate, detail='Cited evidence is incomplete, differently typed, or matches.')
        return _result(predicate, 'INVALID_BASIS', [_ref(item, [predicate.field]) for item in cited],
                       'cited_binding_only', 'Every cited record has a complete but different binding. '
                       'This invalidates that comparison, not the whole accusation or row.')
    spec = _EXACT.get(predicate.reason_type)
    if (spec is None or predicate.assertion not in spec[0]
            or predicate.scope != 'source_presence' or not predicate.field
            or not _scalar(predicate.value)
            or (predicate.reason_type == 'EXACT_ENTITY_EXISTS'
                and type(predicate.value) not in {str, int})):
        return _result(predicate, detail='Only explicit literal source-presence premises are supported.')
    matches = [item for item in evidence
               if _authority(item, predicate.reason_type)
               and item.namespace == predicate.namespace and _bound(predicate, item)
               and item.field_types.get(predicate.field) in spec[1]
               and predicate.field in item.fields
               and (predicate.reason_type != 'EXACT_ENTITY_EXISTS'
                    or type(item.fields[predicate.field]) is type(predicate.value))
               and _equal(item.fields[predicate.field], predicate.value)]
    if not matches:
        return _result(predicate, detail='No exact bound counter-source; absence is not proved.')
    return _result(predicate, 'CONTRADICTED', [_ref(item, [predicate.field]) for item in matches],
                   'literal_source_presence_only', 'The exact value is supplied in a matching source. '
                   'This proves provenance only, not ownership, correct price, current state, '
                   'authorization, or the final response label.')
