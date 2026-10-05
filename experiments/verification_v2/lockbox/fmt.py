"""Rendering helpers for the fresh lockbox (LB1). Output uses the native valid46 markup exactly:
⟦SYSTEM⟧ instructions/policy/[AVAILABLE TOOLS], ⟦ASSISTANT⟧ greeting, ⟦USER⟧ turns,
⟦ASSISTANT · ход N⟧ turns with '\t→ TOOL_CALL name: {json}' / '\t← TOOL_RESPONSE name: ...' lines.
The response is one ⟦ASSISTANT · ход K⟧ block (prose or calls, no tool responses)."""
import json

INSTR = '''<instructions>
You are a customer service agent that helps the user according to the <policy> provided below.
In each turn you can either:
- Send a message to the user.
- Make a tool call.
You cannot do both at the same time.

Try to be helpful and always follow the policy. Always make sure you generate valid JSON only.

Always communicate with the user in Russian. Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear in the system — do not translate or transliterate them.
</instructions>'''


def j(x):
    return json.dumps(x, ensure_ascii=False)


def tool(name, desc, *args):
    """args: (name, kind, required, desc[, enum])"""
    out = [f'- {name} — {desc}']
    for a in args:
        n, k, req, d = a[:4]
        enum = f' [enum: {"|".join(a[4])}]' if len(a) > 4 else ''
        out.append(f'    {n}: {k}{"!" if req else ""}{enum} — {d}')
    if not args:
        out.append('    ')
    return '\n'.join(out)


def U(text):
    return ('U', text)


def A(text):
    return ('A', text)


def C(*calls):
    """calls: (name, args, result) ; result str or json-able"""
    return ('C', calls)


def render(policy, tools, history, response):
    parts = ['⟦SYSTEM⟧\n' + INSTR + '\n<policy>\n' + policy.strip() + '\n</policy>\n\n[AVAILABLE TOOLS]\n' + '\n'.join(tools) + '\n\n',
             '⟦ASSISTANT⟧\nЗдравствуйте! Чем могу помочь?\n\n']
    turn = 0
    for kind, x in history:
        if kind == 'U':
            parts.append('⟦USER⟧\n' + x.strip() + '\n\n')
            continue
        turn += 1
        if kind == 'A':
            parts.append(f'⟦ASSISTANT · ход {turn}⟧\n' + x.strip() + '\n\n')
        else:
            lines = [f'\t→ TOOL_CALL {n}: {j(a)}' for n, a, _ in x]
            lines += [f'\t← TOOL_RESPONSE {n}: {r if isinstance(r, str) else j(r)}' for n, _, r in x]
            parts.append(f'⟦ASSISTANT · ход {turn}⟧\n' + '\n'.join(lines) + '\n\n')
    prompt = ''.join(parts).rstrip('\n')
    turn += 1
    kind, x = response
    if kind == 'A':
        resp = f'⟦ASSISTANT · ход {turn}⟧\n' + x.strip()
    else:
        resp = f'⟦ASSISTANT · ход {turn}⟧\n' + '\n'.join(f'\t→ TOOL_CALL {n}: {j(a)}' for n, a in x)
    return prompt, resp


def R(*calls):
    """response with calls (name, args)"""
    return ('C', calls)


def case(cid, domain, family, label, target, cause, history, response, pair=None, keys=()):
    return dict(id=cid, domain=domain, family=family, label=label, target=target, cause=cause,
                history=history, response=response, pair=pair, keys=list(keys))
