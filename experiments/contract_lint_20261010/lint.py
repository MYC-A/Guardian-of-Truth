"""Contract lint (L0): domain-independent checks of the current assistant turn.

Derived only from the input format contract: the tool catalog in `[AVAILABLE TOOLS]`
and the structured trace (`→ TOOL_CALL name: {json}` / `← TOOL_RESPONSE name [ERROR]: ...`).
No policy text is interpreted. Every finding carries evidence; on any parse doubt the
check abstains. Code never asserts "no violation".
"""
import json
import re

HEADER = re.compile(r'^\[AVAILABLE TOOLS\][ \t]*$', re.M)
TOOL_LINE = re.compile(r'^- ([\w.\-]+) —', re.M)
PARAM_LINE = re.compile(r'^    (\w+): (string|integer|number|boolean|array|object)(!)?(?: \[enum: ([^\]]*)\])?(?: —|$)')
CALL = re.compile(r'→ TOOL_CALL ([\w.\-]+): (.*)$')
RESP = re.compile(r'← TOOL_RESPONSE ([\w.\-]+)( \[ERROR\])?:')
SECTION = re.compile(r'^(?:\[[A-Z][A-Z _]{2,40}\]|⟦|</?[a-z_]+>)')
PARAM_LIKE = re.compile(r'^    [a-z_][a-z0-9_]*: ')       # looks like a parameter line
BLOCK = re.compile(r'^⟦([A-Z]+)[^⟧]*⟧[^\n]*$', re.M)
JSON_TYPES = dict(string=lambda v: isinstance(v, str),
                  integer=lambda v: isinstance(v, int) and not isinstance(v, bool),
                  number=lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
                  boolean=lambda v: isinstance(v, bool),
                  array=lambda v: isinstance(v, list),
                  object=lambda v: isinstance(v, dict))


def parse_catalog(prompt):
    """{tool: {'params': {name: {'type', 'required', 'enum'}}}} or None if no catalog block."""
    # The header must be a line of its own: policies may mention "[AVAILABLE TOOLS]" inline.
    headers = list(HEADER.finditer(prompt))
    if len(headers) != 1:
        return None                               # missing or ambiguous catalog block: abstain
    lines = prompt[headers[0].end():].splitlines()[1:]
    catalog, current, terminated = {}, None, False
    for line in lines:
        if SECTION.match(line):
            terminated = True
            break
        m = TOOL_LINE.match(line)
        if m:
            if m.group(1) in catalog:
                return None                       # duplicate tool name: ambiguous catalog
            current = catalog.setdefault(m.group(1), dict(params={}, complete=True))
            continue
        p = PARAM_LINE.match(line)
        if p and current is not None:
            enum = [x.strip() for x in p.group(4).split('|')] if p.group(4) else None
            current['params'][p.group(1)] = dict(type=p.group(2), required=bool(p.group(3)), enum=enum)
        elif current is not None and PARAM_LIKE.match(line):
            current['complete'] = False           # parameter in an unknown notation: schema unknown
    if not terminated:
        return None                               # catalog runs to end of prompt: possibly truncated
    return catalog or None


def catalog_text(prompt):
    headers = list(HEADER.finditer(prompt))
    rest = prompt[headers[0].end():] if len(headers) == 1 else ''
    m = re.search(r'^(?:\[[A-Z][A-Z _]{2,40}\]|⟦|</?[a-z_]+>)', rest, re.M)
    return rest[:m.start()] if m else rest


def blocks(text):
    """[(role, body)] for ⟦ROLE ...⟧ blocks; text before the first block is role None."""
    marks = list(BLOCK.finditer(text))
    out = [(None, text[:marks[0].start()] if marks else text)]
    for i, m in enumerate(marks):
        out.append((m.group(1), text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)]))
    return out


def paired_history(prompt):
    """Chronological [(role, name, args|None, failed|None)] for calls, and 'USER' markers.

    Within a turn all TOOL_CALL lines precede all TOOL_RESPONSE lines (FIFO order); the i-th
    response belongs to the i-th call. If names/counts disagree, `failed` is None (unknown).
    """
    out = []
    for role, body in blocks(prompt):
        if role == 'USER':
            out.append(('USER', None, None, None))
            continue
        ev = parse_calls(body)
        calls = [e for e in ev if e[0] == 'call']
        resps = [e for e in ev if e[0] == 'resp']
        ok = len(calls) == len(resps) and all(c[1] == r[1] for c, r in zip(calls, resps))
        for i, c in enumerate(calls):
            out.append(('call', c[1], c[2], resps[i][2] if ok else None))
    return out


def parse_calls(text):
    """Ordered events: ('call', name, args|None, raw) and ('resp', name, is_error)."""
    events = []
    for line in text.splitlines():
        s = line.strip()
        m = CALL.match(s)
        if m:
            try:
                args = json.loads(m.group(2))
            except ValueError:
                args = None
            events.append(('call', m.group(1), args, m.group(2)))
            continue
        r = RESP.match(s)
        if r:
            events.append(('resp', r.group(1), bool(r.group(2))))
    return events


def canon(args):
    return json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def schema_findings(name, args, entry):
    out, params = [], entry['params']
    if not params:
        return out                                # no parsed parameters: abstain
    check_unknown = entry.get('complete', True)
    for key, spec in params.items():
        if spec['required'] and key not in args:
            out.append(dict(check='SCHEMA', tool=name, detail=f'missing required parameter {key}'))
    for key, value in args.items():
        spec = params.get(key)
        if spec is None:
            if check_unknown:
                out.append(dict(check='SCHEMA', tool=name, detail=f'unknown parameter {key}'))
            continue
        if value is None and not spec['required']:
            continue
        if not JSON_TYPES[spec['type']](value):
            out.append(dict(check='SCHEMA', tool=name, detail=f'{key}: expected {spec["type"]}, got {type(value).__name__}'))
        elif spec['enum'] and isinstance(value, str) and value not in spec['enum']:
            out.append(dict(check='SCHEMA', tool=name, detail=f'{key}: {value!r} not in enum'))
    return out


def lint(prompt, response):
    """Findings for the current turn (`response`), given the history/catalog in `prompt`."""
    catalog = parse_catalog(prompt)
    if catalog is None:
        return []
    history = paired_history(prompt)
    failed_tail = None                            # last history event, if it is a call known to have failed
    if history and history[-1][0] == 'call' and history[-1][3] is True and history[-1][2] is not None:
        failed_tail = (history[-1][1], canon(history[-1][2]))
    findings, first = [], True
    for ev in parse_calls(response):
        if ev[0] != 'call':
            continue
        name, args = ev[1], ev[2]
        if name not in catalog:
            if re.search(r'(?<![\w.\-])' + re.escape(name) + r'(?![\w.\-])', catalog_text(prompt)):
                continue                          # mentioned inside the catalog (alias/note): abstain
            findings.append(dict(check='UNKNOWN_TOOL', tool=name, detail='not in [AVAILABLE TOOLS]'))
        elif not isinstance(args, dict):
            findings.append(dict(check='INVALID_ARGS_JSON', tool=name, detail=ev[3][:200]))
        else:
            findings.extend(schema_findings(name, args, catalog[name]))
        if first and failed_tail is not None and isinstance(args, dict) and (name, canon(args)) == failed_tail:
            findings.append(dict(check='REPEAT_FAILED', tool=name, detail='identical to the immediately preceding failed call'))
        first = False
    return findings
