"""Domain-agnostic call invariants (no policy table, no LLM, no dataset IDs).

* PLACEHOLDER_ARGUMENT: a template/placeholder string is passed as a value.
* NOOP_REPLACEMENT: ``x`` / ``new_x`` arguments are equal (same position for arrays):
  a replacement that replaces an item with itself.
* REPEATED_FAILED_CALL: the exact same tool + arguments already returned an error
  in the visible history and nothing since then succeeded with them.
"""
import json
import re

_PLACEHOLDER = re.compile(r'placeholder|^<[^<>]{1,60}>$|^\{\{.*\}\}$|^(?:tbd|todo|n/?a|xxx+|unknown_[a-z_]+|your_[a-z_]+)$'
                          r'|_here$|^example_?id$', re.I)
_RESPONSE = re.compile(r'\n\s*← TOOL_RESPONSE\s+(\S+)\s*(\[ERROR\])?\s*:?', re.U)


def _expand(value):
    """Decode JSON-object strings (e.g. wrapped tool arguments) so leaves are inspected."""
    if isinstance(value, str) and value.strip().startswith('{'):
        try: return _expand(json.loads(value))
        except ValueError: return value
    if isinstance(value, dict): return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list): return [_expand(v) for v in value]
    return value


def _leaves(value, path=''):
    if isinstance(value, dict):
        for k, v in value.items(): yield from _leaves(v, f'{path}.{k}' if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value): yield from _leaves(v, f'{path}[{i}]')
    else: yield path, value


def placeholder_violations(arguments):
    return [{'code': 'PLACEHOLDER_ARGUMENT', 'argument': k, 'value': v}
            for k, v in _leaves(_expand(arguments)) if isinstance(v, str) and _PLACEHOLDER.search(v.strip())]


def _pairs(obj):
    if not isinstance(obj, dict): return
    for key, value in obj.items():
        if key.startswith('new_') and key[4:] in obj: yield key[4:], obj[key[4:]], key, value
        if isinstance(value, dict): yield from _pairs(value)


def noop_replacement_violations(arguments):
    out = []
    for old_key, old, new_key, new in _pairs(_expand(arguments)):
        if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
            same = [i for i, (a, b) in enumerate(zip(old, new)) if a == b and a not in (None, '')]
            if same: out.append({'code': 'NOOP_REPLACEMENT', 'argument': new_key, 'positions': same,
                                 'values': [new[i] for i in same]})
        elif not isinstance(old, (list, dict)) and old == new and old not in (None, ''):
            out.append({'code': 'NOOP_REPLACEMENT', 'argument': new_key, 'value': new})
    return out


def _history_calls(events):
    """(tool, arguments, failed) for every visible call, including inline responses."""
    calls = []
    for e in events:
        if e.kind == 'call':
            args, failed = e.value, None
            m = _RESPONSE.search(e.text or '')
            if m:
                failed = bool(m.group(2))
                if args is None:
                    try: args = json.loads(e.text[:m.start()])
                    except ValueError: args = None
            calls.append([e.name, args, failed])
        elif e.kind == 'result' and calls and calls[-1][2] is None:
            calls[-1][2] = bool(re.match(r'\s*(?:\[ERROR\]|error\b)', e.text or '', re.I))
    return calls


def repeated_failed_call_violations(history_events, tool, arguments):
    if not isinstance(arguments, dict) or not arguments: return []
    last = None
    for name, args, failed in _history_calls(history_events):
        if name == tool and args == arguments: last = failed
    return [{'code': 'REPEATED_FAILED_CALL', 'tool': tool}] if last else []


def call_invariants(history_events, tool, arguments):
    return (placeholder_violations(arguments) + noop_replacement_violations(arguments) +
            repeated_failed_call_violations(history_events, tool, arguments))
