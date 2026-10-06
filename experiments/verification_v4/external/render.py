"""Guardian-native rendering of tau2-bench data (tool catalog, conversation). Format = valid46 markup:
⟦SYSTEM⟧ <instructions>…</instructions> <policy>…</policy> [AVAILABLE TOOLS] …, ⟦ASSISTANT⟧ greeting, ⟦USER⟧ turns (user
text + user-device tool lines), ⟦ASSISTANT · ход N⟧ blocks with '\t→ TOOL_CALL name: {json}' and '\t← TOOL_RESPONSE name: …'
lines (multi-line responses continue with '\t  '; failed tool results as 'TOOL_RESPONSE name [ERROR]: …')."""
import json
import re


def _type(p, defs):
    if '$ref' in p:
        return 'object', defs[p['$ref'].split('/')[-1]]
    if 'anyOf' in p:
        ts = [x for x in p['anyOf'] if x.get('type') != 'null']
        if len(ts) == 1:
            t, sub = _type(ts[0], defs)
            return t, sub
        return '|'.join(x.get('type', 'object') for x in ts), None
    t = p.get('type', 'object')
    if t == 'array':
        it = p.get('items') or {}
        if 'anyOf' in it:
            it = next((x for x in it['anyOf'] if '$ref' in x), it)
        if '$ref' in it:
            return 'array', defs[it['$ref'].split('/')[-1]]
        return 'array', None
    return t, None


def _args(params, defs, indent, bullet):
    out = []
    req = set(params.get('required') or [])
    for name, p in (params.get('properties') or {}).items():
        t, sub = _type(p, defs)
        enum = p.get('enum') or next((x.get('enum') for x in p.get('anyOf') or [] if x.get('enum')), None)
        e = f' [enum: {"|".join(map(str, enum))}]' if enum else ''
        desc = re.sub(r'\s*\n\s*', ' ', (p.get('description') or '').strip())
        out.append(f'{indent}{bullet}{name}: {t}{"!" if name in req else ""}{e}' + (f' — {desc}' if desc else ''))
        if sub:
            out += _args(sub, defs, '        ', '· ')
    return out


def tool_line(schema):
    f = schema['function']
    params = f.get('parameters') or {}
    defs = params.get('$defs') or {}
    desc = '\n    '.join((f.get('description') or '').strip().split('\n'))
    return '\n'.join([f"- {f['name']} — {desc}"] + _args(params, defs, '    ', ''))


def j(x):
    return json.dumps(x, ensure_ascii=False)


def _resp(name, content, error):
    c = content if isinstance(content, str) else j(content)
    lines = (c or '').split('\n')
    head = f'\t← TOOL_RESPONSE {name}{" [ERROR]" if error else ""}: {lines[0]}'
    return '\n'.join([head] + ['\t  ' + x for x in lines[1:]])


def system_block(instruction, policy, tools):
    return ('⟦SYSTEM⟧\n<instructions>\n' + instruction.strip() + '\n</instructions>\n<policy>\n' + policy.strip() + '\n</policy>\n\n'
            '[AVAILABLE TOOLS]\n' + '\n'.join(tool_line(t) for t in tools) + '\n\n')


def blocks(messages):
    """tau2 messages -> list of dict(kind 'greeting'|'user'|'assistant', turn, text, calls, msg_index). Tool messages are
    attached to the block of the message that requested them; consecutive user-side messages are one ⟦USER⟧ block."""
    out, turn, names = [], 0, {}
    for i, m in enumerate(messages):
        role = m['role']
        if role == 'tool':
            b = out[-1]
            b['responses'].append(_resp(names.get(m.get('id'), '?'), m.get('content'), m.get('error')))
            b['msg_indices'].append(i)
            continue
        calls = m.get('tool_calls') or []
        for c in calls:
            names[c['id']] = c['name']
        if role == 'assistant' and not out:
            out.append(dict(kind='greeting', text=m.get('content') or '', calls=[], responses=[], msg_indices=[i], turn=0))
            continue
        if role == 'user':
            if out and out[-1]['kind'] == 'user' and not out[-1]['responses'] and False:
                pass
            out.append(dict(kind='user', text=m.get('content') or '', calls=calls, responses=[], msg_indices=[i], turn=None))
            continue
        turn += 1
        out.append(dict(kind='assistant', text=m.get('content') or '', calls=calls, responses=[], msg_indices=[i], turn=turn))
    return out


def render_block(b, with_responses=True):
    if b['kind'] == 'greeting':
        return '⟦ASSISTANT⟧\n' + b['text'].strip()
    head = '⟦USER⟧' if b['kind'] == 'user' else f"⟦ASSISTANT · ход {b['turn']}⟧"
    lines = []
    if b['text'].strip():
        lines.append(b['text'].strip())
    lines += [f"\t→ TOOL_CALL {c['name']}: {j(c['arguments'])}" for c in b['calls']]
    if with_responses:
        lines += b['responses']
    return head + '\n' + '\n'.join(lines)


def render(instruction, policy, tools, messages, k):
    """Row for the assistant block whose turn == k: prompt = everything before it, response = the block (no responses)."""
    bl = blocks(messages)
    idx = next(i for i, b in enumerate(bl) if b['kind'] == 'assistant' and b['turn'] == k)
    prompt = system_block(instruction, policy, tools) + '\n\n'.join(render_block(b) for b in bl[:idx])
    return prompt, render_block(bl[idx], with_responses=False), bl, idx
