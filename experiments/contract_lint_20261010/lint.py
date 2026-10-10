"""Contract lint (L0): domain-independent checks of the current assistant turn.

Derived only from the input format contract: the tool catalog in `[AVAILABLE TOOLS]`
and the structured trace (`→ TOOL_CALL name: {json}` / `← TOOL_RESPONSE name [ERROR]: ...`).
No policy text is interpreted. Every finding carries evidence; on any parse doubt the
check abstains. Code never asserts "no violation".
"""
import json
import re

TOOL_LINE = re.compile(r'^- ([\w.\-]+) —', re.M)
PARAM_LINE = re.compile(r'^    (\w+): (string|integer|number|boolean|array|object)(!)?(?: \[enum: ([^\]]*)\])?(?: —|$)')
CALL = re.compile(r'→ TOOL_CALL ([\w.\-]+): (.*)$')
RESP = re.compile(r'← TOOL_RESPONSE ([\w.\-]+)( \[ERROR\])?:')
SECTION = re.compile(r'^(?:\[[A-Z][A-Z _]{2,40}\]|⟦|</?[a-z_]+>)')
JSON_TYPES = dict(string=lambda v: isinstance(v, str),
                  integer=lambda v: isinstance(v, int) and not isinstance(v, bool),
                  number=lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
                  boolean=lambda v: isinstance(v, bool),
                  array=lambda v: isinstance(v, list),
                  object=lambda v: isinstance(v, dict))


def parse_catalog(prompt):
    """{tool: {'params': {name: {'type', 'required', 'enum'}}}} or None if no catalog block."""
    start = prompt.find('[AVAILABLE TOOLS]')
    if start < 0:
        return None
    lines = prompt[start:].splitlines()[1:]
    catalog, current = {}, None
    for line in lines:
        if SECTION.match(line):
            break
        m = TOOL_LINE.match(line)
        if m:
            if m.group(1) in catalog:
                return None                       # duplicate tool name: ambiguous catalog
            current = catalog.setdefault(m.group(1), dict(params={}))
            continue
        p = PARAM_LINE.match(line)
        if p and current is not None:
            enum = [x.strip() for x in p.group(4).split('|')] if p.group(4) else None
            current['params'][p.group(1)] = dict(type=p.group(2), required=bool(p.group(3)), enum=enum)
    return catalog or None


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
    for key, spec in params.items():
        if spec['required'] and key not in args:
            out.append(dict(check='SCHEMA', tool=name, detail=f'missing required parameter {key}'))
    for key, value in args.items():
        spec = params.get(key)
        if spec is None:
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
    history = parse_calls(prompt)
    failed_tail = None                            # last history call if it failed and nothing followed
    for i, ev in enumerate(history):
        if ev[0] == 'call':
            nxt = history[i + 1] if i + 1 < len(history) else None
            failed = nxt is not None and nxt[0] == 'resp' and nxt[1] == ev[1] and nxt[2]
            failed_tail = (ev[1], canon(ev[2])) if failed and ev[2] is not None else None
    findings, first = [], True
    for ev in parse_calls(response):
        if ev[0] != 'call':
            continue
        name, args = ev[1], ev[2]
        if name not in catalog:
            findings.append(dict(check='UNKNOWN_TOOL', tool=name, detail='not in [AVAILABLE TOOLS]'))
        elif not isinstance(args, dict):
            findings.append(dict(check='INVALID_ARGS_JSON', tool=name, detail=ev[3][:200]))
        else:
            findings.extend(schema_findings(name, args, catalog[name]))
        if first and failed_tail is not None and isinstance(args, dict) and (name, canon(args)) == failed_tail:
            findings.append(dict(check='REPEAT_FAILED', tool=name, detail='identical to the immediately preceding failed call'))
        first = False
    return findings
