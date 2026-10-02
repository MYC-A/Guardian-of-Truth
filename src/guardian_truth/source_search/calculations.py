"""Typed arithmetic on exact source spans; never decides rule applicability."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

DATE_LITERAL = re.compile(r'(?<!\d)\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?(?!\d)')
NUMBER_PATTERN = r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
NUMBER_LITERAL = re.compile(r'(?<![\w.,])' + NUMBER_PATTERN + r'(?![\w,]|\.\d)')


def literals(store, source_id, kind):
    if kind not in ('date', 'datetime', 'decimal'):
        raise ValueError('unsupported literal kind')
    source = store.quotes.get(source_id) or store.sources.get(source_id)
    if source is None:
        raise ValueError('unknown source')
    pattern = DATE_LITERAL if kind in ('date', 'datetime') else NUMBER_LITERAL
    out = []
    for match in pattern.finditer(store.text(source_id)):
        start, end = source['start'] + match.start(), source['start'] + match.end()
        ref = store.quote_id(source['document'], start, end)
        text = store.text(ref)
        actual_kind = ('date' if len(text) == 10 else 'datetime') if pattern == DATE_LITERAL else 'decimal'
        out.append({'source_id': ref, 'literal': text, 'kind': actual_kind})
    return out


def _operand(store, spec):
    if not isinstance(spec, dict) or spec.get('kind') not in ('date', 'datetime', 'decimal'):
        raise ValueError('typed operand required')
    # No model-supplied free values. Numbers/dates must be exact source literals.
    text = store.text(spec['source_id']).strip()
    if spec['kind'] == 'date':
        if len(text) != 10:
            raise ValueError('date requires day precision')
        value = date.fromisoformat(text)
    elif spec['kind'] == 'datetime':
        value = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if value.tzinfo is None:
            raise ValueError('datetime timezone unknown; no default guessed')
    else:
        if not re.fullmatch(NUMBER_PATTERN, text):
            raise ValueError('ambiguous number format or missing literal span')
        value = Decimal(text.replace(',', ''))
    return value, {'source_id': spec['source_id'], 'literal': text, 'kind': spec['kind']}


def calculate(store, operation, operands):
    try:
        pairs = [_operand(store, s) for s in operands]
        values, refs = [p[0] for p in pairs], [p[1] for p in pairs]
        if not values or len({r['kind'] for r in refs}) != 1:
            raise ValueError('mixed or absent operand kinds')
        if operation == 'compare' and len(values) == 2:
            result = 'LESS_THAN' if values[0] < values[1] else 'GREATER_THAN' if values[0] > values[1] else 'EQUAL'
        elif operation == 'difference' and len(values) == 2:
            difference = values[0] - values[1]
            result = (str(difference.days) if refs[0]['kind'] == 'date' else
                      str(difference.total_seconds()) if refs[0]['kind'] == 'datetime' else str(difference))
        elif refs[0]['kind'] == 'decimal':
            if operation == 'sum':
                result = str(sum(values, Decimal(0)))
            elif operation == 'percentage' and len(values) == 2 and values[1] != 0:
                result = str(values[0] / values[1] * Decimal(100))
            elif operation == 'ratio' and len(values) == 2 and values[1] != 0:
                result = str(values[0] / values[1])
            else:
                raise ValueError('unsupported operation or arity')
        else:
            raise ValueError('unsupported operation or arity')
        return {'status': 'COMPUTED', 'operation': operation, 'operands': refs, 'result': result,
            'provenance': 'EXACT_SOURCE_ARITHMETIC', 'decision': 'ADVISORY',
            'limitations': ['Entity binding, units and applicable normative relation require separate checks.']}
    except (ValueError, KeyError, InvalidOperation, TypeError, OverflowError) as exc:
        return {'status': 'UNKNOWN', 'operation': operation, 'reason': str(exc), 'decision': 'UNKNOWN'}
