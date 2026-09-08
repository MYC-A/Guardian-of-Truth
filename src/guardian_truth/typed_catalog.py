"""Model-blind lexical/structured objects for constrained formalization.

This is an inventory, not a rule translator or fact verifier. Source occurrences
stay distinct; numeric/temporal literals do not establish applicability, entity
ownership, arithmetic operands, or a current world state. No labels are accepted.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import json
import math
import re
from typing import Any

from .parsing import FIELD, MARKER, TOOL, parse_events
from .types import Source


@dataclass(frozen=True)
class CatalogItem:
    id: str
    kind: str
    value: Any
    source: Source
    role: str
    event_index: int
    authority: str
    namespace: str
    path: tuple[str | int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TypedCatalog:
    items: tuple[CatalogItem, ...]
    issues: tuple[str, ...]
    complete: bool

    def get(self, item_id):
        return next((item for item in self.items if item.id == item_id), None)

    def to_dict(self):
        return asdict(self)


def select_rule_catalog(catalog: TypedCatalog, prompt: str, start: int, end: int,
                        *, max_items=160) -> TypedCatalog:
    """Select a bounded rule-local view plus lexically linked declarations.

    This is deliberately model-blind schema linking.  It does not infer a
    predicate or claim that a similarly named field applies to the rule.
    Original IDs and Source coordinates are preserved.
    """
    if (not isinstance(catalog, TypedCatalog) or not isinstance(prompt, str)
            or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(prompt)
            or type(max_items) is not int or not 8 <= max_items <= 1000):
        raise ValueError('Invalid rule catalog selection')
    rule = prompt[start:end]

    def words(value):
        value = str(value).replace('_', ' ').replace('-', ' ').lower()
        return {word for word in re.findall(r'[a-z0-9]+', value) if len(word) >= 3}

    rule_words = words(rule)
    local, linked = [], []
    for item in catalog.items:
        source_local = (item.source.document == 'prompt' and
                        ((item.kind == 'TextSpan'
                          and item.source.start < end and item.source.end > start)
                         or start <= item.source.start < item.source.end <= end))
        if source_local:
            local.append(item)
        elif item.metadata.get('declaration') and words(item.value) & rule_words:
            linked.append(item)
    # Prefer all rule-local evidence, then the most specific declarations.
    linked.sort(key=lambda item: (-len(words(item.value) & rule_words), item.id))
    chosen = local + [item for item in linked if item.id not in {x.id for x in local}]
    truncated = len(chosen) > max_items
    chosen = chosen[:max_items]
    # Malformed structured events elsewhere in the row are irrelevant to a
    # policy-only view because observations are intentionally not selected.
    global_issues = {'event_limit', 'item_limit', 'invalid_event_bounds',
                     'invalid_item_bounds', 'json_token_limit'}
    issues = [item for item in catalog.issues if item in global_issues]
    if truncated:
        issues.append('rule_catalog_limit')
    return TypedCatalog(tuple(chosen), tuple(dict.fromkeys(issues)),
                        not issues)


_DATE = re.compile(r'(?<![\w-])\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?(?![\w:-])')
_NUMBER = re.compile(r'(?<![\w.+-])-?(?:\d+(?:\.\d+)?)(?!\w|\.\d|[/-]\d)')
_OPAQUE = re.compile(r'https?://\S+|[\w.+-]+@[\w.-]+|\b\d+(?:\.\d+){2,}\b|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b[\w]*[A-Za-z_][\w-]*\d[\w-]*\b')
_CURRENCY = re.compile(r'[$€£₽]|\b(?:USD|EUR|GBP|RUB|CAD|AUD|JPY|CNY|CHF|INR)\b')
_WORDS = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
          'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
          'ноль': 0, 'один': 1, 'одна': 1, 'одно': 1, 'два': 2, 'две': 2,
          'три': 3, 'четыре': 4, 'пять': 5}
_WORD_NUMBER = re.compile(r'\b(?:' + '|'.join(_WORDS) + r')\b', re.IGNORECASE)
_STATE = re.compile(r'\b(?:active|inactive|closed|open|pending|delivered|suspended|expired|enabled|disabled|available|unavailable)\b', re.IGNORECASE)
_POLICY_ACTION = re.compile(r'`?\b([A-Za-z][A-Za-z0-9_]*_[A-Za-z0-9_]+)\s*\([^\r\n()]{0,160}\)`?')
_QUOTED = re.compile(r'(?P<q>[\'\"])(?P<value>[^\'\"\r\n]{1,120})(?P=q)')
_MODALITY = re.compile(r'\b(?:must|should|may|required|allowed|cannot|can\s+only|not\s+allowed)\b', re.IGNORECASE)
_QUANTIFIER = re.compile(r'\b(?:some|any|all|each|every)\b', re.IGNORECASE)
_OPERATOR_CUE = re.compile(
    r'\b(?:if\s+and\s+only\s+if|only\s+if|at\s+most|at\s+least|before|after|unless|otherwise|'
    r'even\s+if|different|same|not|and|or|if)\b', re.IGNORECASE)
_UNIT = re.compile(r'\s*(%|GB|MB|KB|TB|USD|EUR|GBP|RUB|CAD|AUD|JPY|CNY|CHF|INR|milliseconds?|seconds?|minutes?|hours?|hrs?|days?|weeks?)\b', re.IGNORECASE)
_FIELD_MENTION = re.compile(
    r"\b(?:[A-Za-z][A-Za-z'-]*\s+){0,3}(?:status|state|date|time|amount|level|reason|price|option|type|id|number)\b",
    re.IGNORECASE)


def _bounded_text_spans(text, start, end, maximum):
    """Yield exact clause/sentence spans, chunking only overlong clauses."""
    body = text[start:end]
    boundaries = [0]
    for match in re.finditer(r'(?:\r?\n+|(?<=[.!?;:])\s+)', body):
        boundaries.append(match.end())
    boundaries.append(len(body))
    for left, right in zip(boundaries, boundaries[1:]):
        while left < right and body[left].isspace():
            left += 1
        while right > left and body[right - 1].isspace():
            right -= 1
        for offset in range(left, right, maximum):
            yield start + offset, start + min(offset + maximum, right)


def _date_kind(value):
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            date.fromisoformat(value)
            return 'date'
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?', value):
            datetime.fromisoformat(value.replace('Z', '+00:00'))
            return 'datetime'
    except ValueError:
        pass
    return None


def _identity_field(key):
    return (key in {'id', 'ids', 'zip', 'postal_code', 'phone', 'phone_number',
                    'flight_number', 'order_number', 'reservation_number'}
            or key.endswith(('_id', '_ids', '_number')))


def _authority(event, document):
    if document == 'response':
        if event.kind == 'call':
            return 'candidate_action' if event.role == 'assistant' else 'candidate_embedded_action'
        return 'candidate_claim'
    if event.kind == 'result':
        return 'tool_observation'
    if event.kind == 'call':
        return 'historical_user_action' if event.role == 'user' else 'historical_assistant_action'
    return {'system': 'system_policy', 'user': 'user_provided',
            'assistant': 'historical_assistant_claim'}.get(event.role, 'unknown')


def _json_tokens(text, max_depth):
    """Yield key and scalar spans relative to a previously validated JSON body."""
    decoder = json.JSONDecoder()
    length = len(text)

    def whitespace(pos):
        while pos < length and text[pos].isspace():
            pos += 1
        return pos

    def walk(pos, path, depth):
        if depth > max_depth:
            raise ValueError('json_depth_limit')
        pos = whitespace(pos)
        start = pos
        if text[pos] == '{':
            pos = whitespace(pos + 1)
            if text[pos] == '}':
                return pos + 1
            while True:
                key, end = decoder.raw_decode(text, pos)
                yield ('field', key, pos, end, path + (key,))
                pos = whitespace(end)
                pos = yield from walk(pos + 1, path + (key,), depth + 1)
                pos = whitespace(pos)
                if text[pos] == '}':
                    return pos + 1
                pos = whitespace(pos + 1)
        elif text[pos] == '[':
            pos = whitespace(pos + 1)
            if text[pos] == ']':
                return pos + 1
            index = 0
            while True:
                pos = yield from walk(pos, path + (index,), depth + 1)
                pos = whitespace(pos)
                if text[pos] == ']':
                    return pos + 1
                pos = whitespace(pos + 1)
                index += 1
        else:
            value, end = decoder.raw_decode(text, pos)
            yield ('scalar', value, start, end, path)
            return end

    yield from walk(0, (), 0)


def extract_typed_catalog(prompt: str, response: str = '', *, max_items=5000,
                          max_text_span_chars=240, max_events=1000,
                          max_json_depth=32) -> TypedCatalog:
    """Extract deterministic typed occurrences with exact original coordinates.

    Structured value spans include their JSON quotes/escaping. TextSpan values
    are exact slices. IDs are stable for identical inputs and limits, assigned
    in prompt/response event order. Limits mark the catalog incomplete; they
    never imply absence of omitted objects. No natural-language formula parsing.
    """
    if not isinstance(prompt, str) or not isinstance(response, str):
        raise TypeError('prompt and response must be strings')
    limits = ((max_items, 1, 100000), (max_text_span_chars, 16, 10000),
              (max_events, 1, 10000), (max_json_depth, 1, 64))
    if any(type(value) is not int or not lo <= value <= hi for value, lo, hi in limits):
        raise ValueError('Invalid catalog limits')
    items, issues = [], []

    def issue(code):
        if code not in issues:
            issues.append(code)

    for document, text in (('prompt', prompt), ('response', response)):
        events = parse_events(text, document)
        if len(events) > max_events:
            issue('event_limit')
        for event_index, event in enumerate(events[:max_events]):
            if len(items) >= max_items:
                issue('item_limit')
                break
            authority = _authority(event, document)
            namespace = event.name or 'text'
            start, end = event.source.start, event.source.end
            if not 0 <= start <= end <= len(text):
                issue('invalid_event_bounds')
                continue

            def add(kind, value, lo, hi, *, path=(), metadata=None, auth=None, ns=None):
                if not start <= lo < hi <= end:
                    issue('invalid_item_bounds')
                    return None
                if len(items) >= max_items:
                    issue('item_limit')
                    return None
                item_id = f'tc{len(items):06d}'
                items.append(CatalogItem(item_id, kind, value, Source(document, lo, hi),
                                         event.role, event_index, auth or authority,
                                         ns or namespace, tuple(path), metadata or {}))
                return item_id

            # Every event exposes bounded sentence/clause spans; these are not facts.
            for lo, hi in _bounded_text_spans(text, start, end, max_text_span_chars):
                add('TextSpan', text[lo:hi], lo, hi, metadata={'event_kind': event.kind})

            action_id = None
            if event.kind in {'call', 'result'} and event.name:
                marker = MARKER.match(text, start)
                tool_span = None
                if marker and marker['tool']:
                    tool_span = marker.span('tool')
                elif marker and marker['header']:
                    name_attr = re.search(r'\bname="([^"]*)"', marker['header'])
                    if name_attr:
                        tool_span = (marker.start('header') + name_attr.start(1),
                                     marker.start('header') + name_attr.end(1))
                if tool_span and text[tool_span[0]:tool_span[1]] == event.name:
                    add('Tool', event.name, *tool_span,
                        metadata={'declaration': False, 'event_kind': event.kind})
                else:
                    issue('tool_name_span_unresolved')
                if event.kind == 'call':
                    action_id = add('Action', event.name, start, end,
                                    metadata={'candidate': document == 'response' and event.role == 'assistant',
                                              'arguments_json_valid': event.json_valid})

            # Only an authoritative explicit tool-schema block creates declarations.
            if document == 'prompt' and event.role == 'system' and event.kind == 'text':
                marker = event.text.find('[AVAILABLE TOOLS]')
                if marker >= 0:
                    body_start = start + marker
                    current_tool = None
                    schema_stack = []
                    offset = body_start
                    for line in text[body_start:end].splitlines(keepends=True):
                        tool_match = TOOL.match(line)
                        field_match = FIELD.match(line)
                        if tool_match:
                            current_tool = tool_match['name']
                            schema_stack = []
                            add('Tool', current_tool, offset + tool_match.start('name'),
                                offset + tool_match.end('name'), auth='system_tool_schema',
                                ns=current_tool, metadata={'declaration': True})
                        elif field_match and current_tool:
                            depth = len(field_match['indent'].expandtabs(4))
                            while schema_stack and schema_stack[-1][0] >= depth:
                                schema_stack.pop()
                            schema_path = tuple(entry[1] for entry in schema_stack) + (field_match['name'],)
                            add('Field', field_match['name'], offset + field_match.start('name'),
                                offset + field_match.end('name'), auth='system_tool_schema', ns=current_tool,
                                path=schema_path,
                                metadata={'declaration': True, 'schema_type': field_match['kind'],
                                          'required': bool(field_match['required']),
                                          'enum': field_match['enum'].split('|') if field_match['enum'] else []})
                            schema_stack.append((depth, field_match['name']))
                        offset += len(line)

            if event.json_valid:
                raw = text[start:end].rstrip()
                if not event.text or not raw.endswith(event.text):
                    issue('json_body_span_unresolved')
                    continue
                body_start = start + len(raw) - len(event.text)
                try:
                    tokens = []
                    for token in _json_tokens(event.text, max_json_depth):
                        if len(tokens) >= max_items:
                            issue('json_token_limit')
                            break
                        tokens.append(token)
                except (ValueError, IndexError, RecursionError):
                    issue('json_depth_or_token_limit')
                    continue
                for token_kind, value, lo, hi, path in tokens:
                    metadata = {'event_kind': event.kind, 'action_id': action_id,
                                'container_path': list(path[:-1]), 'structured': True}
                    if token_kind == 'field':
                        add('Field', value, body_start + lo, body_start + hi, path=path,
                            metadata={**metadata, 'declaration': False})
                        continue
                    key = next((part for part in reversed(path) if isinstance(part, str)), '')
                    if _identity_field(key) and type(value) in {str, int}:
                        kind = 'EntityID'
                        metadata['identity_field'] = key
                    elif _date_kind(value):
                        kind = 'Date'
                        metadata['temporal_type'] = _date_kind(value)
                        metadata['timezone_explicit'] = bool(re.search(r'(?:Z|[+-]\d{2}:\d{2})$', value))
                    elif type(value) in {int, float} and (type(value) is int or math.isfinite(value)):
                        kind = 'Number'
                        metadata.update({'numeric_field': key, 'arithmetic_operand_verified': False})
                    elif isinstance(value, str) and _CURRENCY.fullmatch(value):
                        kind = 'Currency'
                        metadata['symbol_ambiguous'] = value == '$'
                    elif key in {'state', 'status'} or key.endswith(('_state', '_status')) or type(value) is bool:
                        kind = 'State'
                        metadata.update({'state_field': key, 'current_state_verified': False})
                    else:
                        kind = 'FieldValue'
                    add(kind, value, body_start + lo, body_start + hi, path=path, metadata=metadata)
                continue

            if event.kind in {'call', 'result'}:
                issue('unparsed_structured_event')
                continue
            # Lexical numbers in prose are candidates, never inferred quantities.
            body = text[start:end]
            masks = [(m.start(), m.end()) for m in _OPAQUE.finditer(body)]
            for match in _DATE.finditer(body):
                masks.append((match.start(), match.end()))
                temporal_type = _date_kind(match[0])
                if temporal_type:
                    add('Date', match[0], start + match.start(), start + match.end(),
                        metadata={'structured': False, 'temporal_type': temporal_type})
            for match in _CURRENCY.finditer(body):
                if any(lo <= match.start() < hi for lo, hi in masks):
                    continue
                add('Currency', match[0], start + match.start(), start + match.end(),
                    metadata={'structured': False, 'symbol_ambiguous': match[0] == '$'})
            for match in _STATE.finditer(body):
                if any(lo <= match.start() < hi for lo, hi in masks):
                    continue
                add('State', match[0], start + match.start(), start + match.end(),
                    metadata={'structured': False, 'lexical_state_mention': True,
                              'current_state_verified': False})
            for match in _POLICY_ACTION.finditer(body):
                lo, hi = match.span(1)
                add('PolicyActionMention', match[1], start + lo, start + hi,
                    metadata={'structured': False, 'declared_tool_verified': False})
            for match in _FIELD_MENTION.finditer(body):
                add('FieldMention', match[0], start + match.start(), start + match.end(),
                    metadata={'structured': False, 'declaration': False,
                              'schema_field_verified': False})
            for match in _QUOTED.finditer(body):
                lo, hi = match.span('value')
                add('EnumValue', match['value'], start + lo, start + hi,
                    metadata={'structured': False, 'closed_enum_verified': False})
            for kind, regex in (('Modality', _MODALITY), ('Quantifier', _QUANTIFIER),
                                ('OperatorCue', _OPERATOR_CUE)):
                for match in regex.finditer(body):
                    add(kind, match[0].lower(), start + match.start(), start + match.end(),
                        metadata={'structured': False})
            for regex, word in ((_NUMBER, False), (_WORD_NUMBER, True)):
                for match in regex.finditer(body):
                    if any(lo < match.end() and hi > match.start() for lo, hi in masks):
                        continue
                    if not word and len(match[0].lstrip('-')) >= 7 and '.' not in match[0]:
                        continue  # Long untyped digits may be IDs or phone numbers.
                    value = (_WORDS[match[0].lower()] if word else
                             float(match[0]) if '.' in match[0] else int(match[0]))
                    if type(value) is float and not math.isfinite(value):
                        continue
                    unit_match = _UNIT.match(body, match.end())
                    unit = unit_match[1] if unit_match else None
                    add('Number', value, start + match.start(), start + match.end(),
                        metadata={'structured': False, 'number_word': word,
                                  'percent': body[match.end():match.end()+1] == '%',
                                  'unit': unit,
                                  'arithmetic_operand_verified': False})
    return TypedCatalog(tuple(items), tuple(issues), not issues)
