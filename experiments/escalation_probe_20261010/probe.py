"""Escalation / refusal probe (docs/escalation_probe_20261010/PROTOCOL.md).

trigger(prompt, response) -> 'transfer' | 'refusal' | None      (code only)
request_messages(prompt, response) -> chat messages for one probe call
verify(prompt, answer) -> (verified: bool, reason: str)            (code only; abstains on any doubt)
"""
import json
import re

from experiments.contract_lint_20261010.lint import HEADER, canon, paired_history, parse_calls, parse_catalog, schema_findings

TRANSFER = re.compile(r'transfer|escalat', re.I)
REFUSAL = re.compile(
    r'не (?:могу|смогу|имею возможност|в состоянии)|невозможно'
    r'|(?:перевед|передам|передать|перевести|соедин)\w*\s+(?:вас\s+)?(?:на|к|с)\s+(?:\w+\s+)?'
    r'(?:специалист|оператор|сотрудник|человек|агент|менеджер)', re.I)
MIN_QUOTE = 20


def history_text(prompt):
    """Prompt text after the tool catalog (dialogue history). '' if the layout is not recognised."""
    headers = list(HEADER.finditer(prompt))
    if len(headers) != 1:
        return ''
    i = prompt.find('⟦', headers[0].end())
    return prompt[i:] if i >= 0 else ''


def trigger(prompt, response):
    catalog = parse_catalog(prompt)
    calls = [e for e in parse_calls(response or '') if e[0] == 'call']
    if calls:
        if catalog and any(TRANSFER.search(c[1]) and c[1] in catalog for c in calls):
            return 'transfer'
        return None
    return 'refusal' if REFUSAL.search(response or '') else None


SYSTEM = ('You audit one turn of a customer-support agent. You answer only with JSON. Be strict: an empty or '
          'null answer is correct when no available tool can make progress or when the policy requires the hand-off.')

QUESTION = """The text above is the agent's prompt (policy, [AVAILABLE TOOLS], dialogue history). The agent's CURRENT TURN is:
<current_turn>
{turn}
</current_turn>
In this turn the agent hands the user off to a human or says it cannot do something.

Question: is there ONE tool in [AVAILABLE TOOLS] (not a transfer/escalation tool) that the agent could have called NOW
to make progress on the user's latest request, that the agent has NOT already called with the same arguments, and
that the policy allows for this request? Use only facts visible in the history; take every argument value from the
history. If no such tool exists, or the policy requires this hand-off/refusal, set "tool" to null.

Answer JSON only:
{{"user_request": "<short>", "tool": "<name or null>", "arguments": {{...}},
 "history_quote": "<verbatim fragment of the history that supplies the arguments>",
 "policy_quote": "<verbatim fragment of the policy that allows using this tool for this request>",
 "why": "<one sentence>"}}"""


RESP_MAX = 1200          # chars kept per tool response body in the probe prompt
HISTORY_MAX = 30000      # chars of (compressed) history in the probe prompt


def compress_history(hist):
    """Truncate each TOOL_RESPONSE (header line + indented continuation) to RESP_MAX chars; if still longer than
    HISTORY_MAX, drop the oldest blocks except the first one. Verification always uses the full prompt."""
    out, cur, in_resp = [], [], False

    def flush():
        if cur:
            body = '\n'.join(cur)
            out.append(body if len(body) <= RESP_MAX else body[:RESP_MAX] + f' …[truncated {len(body) - RESP_MAX} chars]')
            cur.clear()
    for line in hist.split('\n'):
        s = line.strip()
        if s.startswith('← TOOL_RESPONSE'):
            flush()
            cur.append(line)
            in_resp = True
        elif in_resp and line.startswith('\t  ') and not s.startswith(('→', '←')):
            cur.append(line)
        else:
            flush()
            in_resp = False
            out.append(line)
    flush()
    text = '\n'.join(out)
    if len(text) <= HISTORY_MAX:
        return text
    starts = [i for i in range(len(text)) if text.startswith('⟦', i) and (i == 0 or text[i - 1] == '\n')]
    if len(starts) < 3:
        return text[-HISTORY_MAX:]
    first = text[:starts[1]]
    for st in starts[2:]:
        if len(first) + len(text) - st + 60 <= HISTORY_MAX:
            return first + '\n…[older turns omitted]\n' + text[st:]
    return first + '\n…[older turns omitted]\n' + text[starts[-1]:]


def request_messages(prompt, response):
    hist = history_text(prompt)
    head = prompt[:len(prompt) - len(hist)] if hist else prompt
    body = head + compress_history(hist) if hist else prompt
    return [dict(role='system', content=SYSTEM),
            dict(role='user', content=body + '\n\n' + QUESTION.format(turn=response))]


def _norm(s):
    return ' '.join(str(s).split())


def _scalars(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _scalars(x)
    elif isinstance(v, list):
        for x in v:
            yield from _scalars(x)
    elif v is not None and not isinstance(v, bool):
        yield v


def parse_answer(text):
    text = (text or '').strip()
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def verify(prompt, answer):
    if not isinstance(answer, dict):
        return False, 'unparsed'
    tool, args = answer.get('tool'), answer.get('arguments')
    if tool in (None, '', 'null'):
        return False, 'null'
    catalog = parse_catalog(prompt)
    if not catalog:
        return False, 'catalog_abstain'
    if not isinstance(tool, str) or tool not in catalog:
        return False, 'tool_not_in_catalog'
    if TRANSFER.search(tool):
        return False, 'transfer_tool'
    if not isinstance(args, dict):
        return False, 'args_not_object'
    if not catalog[tool].get('complete', True) or not catalog[tool]['params'] and args:
        return False, 'schema_unknown'
    if schema_findings(tool, args, catalog[tool]):
        return False, 'schema'
    if any(e[0] == 'call' and e[1] == tool and isinstance(e[2], dict) and canon(e[2]) == canon(args)
           for e in paired_history(prompt)):
        return False, 'already_called'
    hist = history_text(prompt)
    if not hist:
        return False, 'history_abstain'
    nh = _norm(hist)
    for v in _scalars(args):
        if _norm(v) not in nh:
            return False, 'arg_not_in_history'
    hq, pq = _norm(answer.get('history_quote', '')), _norm(answer.get('policy_quote', ''))
    if len(hq) < MIN_QUOTE or hq not in nh:
        return False, 'history_quote'
    if len(pq) < MIN_QUOTE or pq not in _norm(prompt[:len(prompt) - len(hist)]):
        return False, 'policy_quote'
    return True, 'verified'
