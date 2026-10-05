"""Generic declaration guard (ported verbatim in logic from experiments/whole_move_v1/mechanical.py,
origin commit 5c31da6e) so the installable package does not import experiments.*.


This checks the native indented declaration grammar, not natural-language
policy applicability. Unsupported or ambiguous declarations abstain. Passing
schema checks never establishes NO_ERROR for the whole assistant move.
"""
from collections import Counter
import re

from ..parsing import parse_catalog, TOOL, decode_json
from ..source_search.store import SourceStore

_FIELD = re.compile(
    r'^(?P<indent>[ \t]+)(?:·\s*)?(?P<name>\w+):\s*'
    r'(?P<kind>string|integer|number|boolean|array|object)(?P<required>!)?'
    r'(?:\s+\[enum:\s*(?P<enum>[^\]]+)\])?'
    r'(?:\s+[—–]\s*.*)?\s*$')


def _type_matches(value, kind):
    return {'string': type(value) is str, 'integer': type(value) is int,
            'number': type(value) in (int, float), 'boolean': type(value) is bool,
            'array': type(value) is list, 'object': type(value) is dict}[kind]


def _enum_values(kind, raw):
    if raw is None:
        return None
    if kind not in ('string', 'integer', 'number', 'boolean'):
        raise ValueError('container_enum_unsupported')
    result = []
    for choice in raw.split('|'):
        choice = choice.strip()
        if not choice:
            raise ValueError('empty_enum_alternative')
        if kind == 'string' and not choice.startswith('"'):
            if any(c in choice for c in '"\'[]'):
                raise ValueError('ambiguous_string_enum')
            value = choice
        else:
            value, valid = decode_json(choice)
            if not valid or not _type_matches(value, kind):
                raise ValueError('enum_type_unsupported_or_inconsistent')
        result.append(value)
    return result


def _audit_tool(spec, raw):
    """Cross-check every executable line and tree against native FieldSpecs."""
    problems, lines = [], []
    for offset, text in _lines(raw, spec.source.start, spec.source.end):
        if offset == spec.source.start or not text.strip():
            continue
        match = _FIELD.fullmatch(text.rstrip('\r\n'))
        if match is None:
            problems.append('unsupported_declaration_line')
            continue
        lines.append((offset, match))
    native = []

    def walk(fields):
        names = [f.name for f in fields]
        if len(set(names)) != len(names):
            problems.append('duplicate_field_declaration')
        for field in fields:
            native.append(field)
            if field.children and field.kind not in ('array', 'object'):
                problems.append('children_below_primitive')
            walk(field.children)

    walk(spec.fields)
    parsed = {f.source.start: f for f in native}
    if len(parsed) != len(native) or len(lines) != len(native):
        problems.append('field_grammar_not_fully_accounted')
    enum_values = {}
    for offset, match in lines:
        field = parsed.get(offset)
        if field is None or (field.name, field.kind, field.required) != (
                match['name'], match['kind'], bool(match['required'])):
            problems.append('native_parser_grammar_disagreement')
            continue
        try:
            enum_values[offset] = _enum_values(field.kind, match['enum'])
        except ValueError as exc:
            problems.append(str(exc))
    if not spec.schema_understood:
        problems.append('native_schema_not_understood')
    return sorted(set(problems)), enum_values


def _lines(raw, start, end):
    offset = start
    for text in raw[start:end].splitlines(keepends=True):
        yield offset, text
        offset += len(text)


def _audit_catalog(store, catalog):
    markers = sum(event.text.count('[AVAILABLE TOOLS]') for event in store.history_events
                  if event.role == 'system')
    if markers != 1 or catalog.source is None:
        return False, False, {}, ['missing_or_ambiguous_catalog']
    raw = store.raw['prompt']
    text = raw[catalog.source.start:catalog.source.end]
    definitions = list(TOOL.finditer(text))
    counts = Counter(m['name'] for m in definitions)
    problems = list(catalog.issues)
    if text.splitlines()[0].strip() != '[AVAILABLE TOOLS]':
        problems.append('catalog_marker_line_not_exact')
    # Everything before the first definition must be the marker or whitespace.
    prefix = text[:definitions[0].start()] if definitions else text
    if any(line.strip() not in ('', '[AVAILABLE TOOLS]') for line in prefix.splitlines()):
        problems.append('unsupported_catalog_prefix')
    audits = {}
    for name, spec in catalog.tools.items():
        issues, enums = _audit_tool(spec, raw)
        if counts[name] != 1:
            issues.append('duplicate_tool_declaration')
        audits[name] = (sorted(set(issues)), enums)
        problems.extend(issues)
    if set(counts) != set(catalog.tools):
        problems.append('catalog_inventory_disagreement')
    complete = catalog.complete and not problems and bool(definitions)
    return True, complete, audits, sorted(set(problems))


def check(row, *, tool_universe_closed=False):
    """Return sourced findings and gaps; never a whole-move clean verdict.

    Only prompt/response are read. Labels, explanations and reference spans are
    not accepted as inputs to selection or checks. Tool-name absence requires
    an explicit caller format-contract that the tool universe is closed;
    a catalog header alone never supplies that premise.
    """
    if type(tool_universe_closed) is not bool:
        raise ValueError('TOOL_UNIVERSE_CLOSURE_MUST_BE_EXPLICIT_BOOLEAN')
    store = SourceStore({k: row[k] for k in ('prompt', 'response')})
    catalog = parse_catalog(store.history_events, store.raw['prompt'])
    authoritative, complete, audits, catalog_gaps = _audit_catalog(store, catalog)
    findings, gaps, targets = [], [], []
    checked = 0

    def ref(source, sid=None):
        sid = sid or store.quote_id(source.document, source.start, source.end)
        return dict(source_id=sid, document=source.document, start=source.start,
                    end=source.end, text=store.raw[source.document][source.start:source.end])

    def emit(container, code, target, claim, sources, path=None):
        refs = []
        seen = set()
        for source, sid in sources:
            identity = (source.document, source.start, source.end)
            if identity not in seen:
                refs.append(ref(source, sid)); seen.add(identity)
        container.append(dict(code=code, target_id=target, path=path,
                              source_refs=refs, claim=claim))

    def fields(value, declared, enums, target, call, prefix='$', ancestors=()):
        for field in declared:
            path = prefix + '.' + field.name
            sources = [(call.source, target)] + [(s, None) for s in ancestors + (field.source,)]
            if field.name not in value:
                if field.required:
                    emit(findings, 'missing_argument', target,
                         f'Explicit required field {path} is absent from this current call.', sources, path)
                continue
            actual = value[field.name]
            if not _type_matches(actual, field.kind):
                emit(findings, 'argument_type', target,
                     f'{path} has JSON type {type(actual).__name__}; its declaration requires {field.kind}.',
                     sources, path)
                continue
            choices = enums.get(field.source.start)
            if choices is not None and not any(type(actual) is type(c) and actual == c or (
                    field.kind == 'number' and type(actual) in (int, float)
                    and type(c) in (int, float) and actual == c) for c in choices):
                emit(findings, 'argument_enum', target,
                     f'{path} is not exactly one of the explicitly enumerated values.', sources, path)
            if field.children and type(actual) is dict:
                fields(actual, field.children, enums, target, call, path, ancestors + (field.source,))
            elif field.children and type(actual) is list:
                for index, item in enumerate(actual):
                    if type(item) is not dict:
                        emit(findings, 'argument_type', target,
                             f'{path}[{index}] is not an object with the declared child fields.',
                             sources + [(f.source, None) for f in field.children], f'{path}[{index}]')
                    else:
                        fields(item, field.children, enums, target, call, f'{path}[{index}]',
                               ancestors + (field.source,))

    for index, call in enumerate(store.target_events):
        if call.role != 'assistant' or call.kind != 'call':
            continue
        target = 't' + str(index)
        targets.append(dict(target_id=target, tool=call.name, source=ref(call.source, target),
                            schema_status='UNKNOWN'))
        if not call.json_valid:
            emit(gaps, 'call_arguments_unparsed', target,
                 'Current call JSON cannot be decoded; formatting alone is not a certified task violation.',
                 [(call.source, target)])
            continue
        if not isinstance(call.name, str) or not call.name:
            emit(gaps, 'call_name_unparsed', target,
                 'The current call has no parsed tool name; tool absence is not established.',
                 [(call.source, target)])
            continue
        spec = catalog.tools.get(call.name) if authoritative else None
        if spec is None:
            if complete and tool_universe_closed:
                emit(findings, 'unavailable_tool', target,
                     'This current call name is absent from the fully audited original tool catalog.',
                     [(call.source, target), (catalog.source, None)])
                targets[-1]['schema_status'] = 'MECHANICAL_FINDING'
            else:
                emit(gaps, 'tool_availability_unknown', target,
                     ('Tool name is absent from the parsed inventory, but a closed-tool-universe '
                      'format-contract is not supplied.' if complete and not tool_universe_closed else
                      'Original tool inventory is missing, partial or ambiguous; absence is not established.'),
                     [(call.source, target)] + ([(catalog.source, None)] if catalog.source else []))
            continue
        issues, enums = audits[call.name]
        if issues:
            emit(gaps, 'tool_schema_not_fully_understood', target,
                 'Declaration grammar is partial or ambiguous: ' + ', '.join(issues),
                 [(call.source, target), (spec.source, None)])
            continue
        if not spec.fields:
            emit(gaps, 'no_explicit_argument_schema', target,
                 'Tool declaration has no executable field constraints; no closed argument schema is inferred.',
                 [(call.source, target), (spec.source, None)])
            continue
        if type(call.value) is not dict:
            emit(gaps, 'root_argument_structure_unknown', target,
                 'Field declarations alone do not explicitly establish the root JSON object contract.',
                 [(call.source, target), (spec.source, None)])
            continue
        checked += 1
        before = len(findings)
        fields(call.value, spec.fields, enums, target, call)
        targets[-1]['schema_status'] = 'MECHANICAL_FINDING' if len(findings) > before else 'DECLARED_FIELDS_CHECKED'
    return dict(version='integrated-declaration-guard-v1 (logic = whole-move-mechanical-v1)', source_sha256=store.source_sha256,
        targets=targets, findings=findings, gaps=gaps, mechanically_established_error=bool(findings),
        catalog=dict(authoritative=authoritative, executable_inventory_complete=complete,
                     tool_universe_closed=tool_universe_closed,
                     absence_check_enabled=complete and tool_universe_closed, gaps=catalog_gaps),
        coverage=dict(status=('NO_CURRENT_ASSISTANT_CALLS' if not targets else
                              'PARTIAL' if gaps else 'CALL_SCHEMA_SCOPE_ONLY'),
                      total_current_assistant_calls=len(targets), schema_checked_calls=checked,
                      whole_move_certified=False), inference_http=0)
