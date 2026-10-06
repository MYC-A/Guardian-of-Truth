"""Repaired confirmation binding (contract 3). Explicit state over the timeline:
proposal (last SUBSTANTIVE assistant prose before the call: states values / asks / mentions the call's argument values)
-> scoped consent (a user affirmation after that proposal: starts affirmative, is not a question, has no 'but/only if'
condition, no retraction) -> revision (a later user turn that retracts or changes details voids the consent).
Courtesy turns ('Thank you', 'Great') neither create nor reset consent. Identifiers compare by exact alphanumeric
identity (BK-1 != BK-10). A policy sentence that NEGATES the need for confirmation is not a trigger."""
from __future__ import annotations

import re

from ..verification import confirm as C, derived as D
from ..verification.common import norm_ws
from . import numeric as N

NEG_REQ = re.compile(r"\b(?:does not|doesn't|do not|don't|need not|needn't|no need|not required|never require\w*|without)\b[^.;]{0,40}confirm|"
                     r"не требу\w*[^.;]{0,30}подтвер|без (?:\w+ )?подтвер|не нужно[^.;]{0,30}подтвер", re.I)
CONDITION = re.compile(r"(?<!\w)(?:but|however|only if|unless|although|except|но|однако|только если|если|хотя|кроме)(?!\w)", re.I)
COURTESY = re.compile(r"^\W*(?:thanks?(?: you)?|thank you(?: very much)?|great|perfect|awesome|cool|got it|noted|ok(?:ay)?|спасибо|отлично|супер|понял\w*|ясно|хорошо)\W*$", re.I)


def requires_confirmation(tool, packet, system=''):
    if not tool:
        return None
    pat = re.compile(r'(?<![\w])`?' + re.escape(tool) + r'`?(?![\w])')
    for s in packet['normative_sources']:
        for x in C.sentences(s['text']):
            if pat.search(x) and C.CONFIRM.search(x) and not NEG_REQ.search(x):
                return dict(source_id=s['source_id'], sentence=norm_ws(x)[:400], in_packet=True)
    for x in C.sentences(system):
        if pat.search(x) and C.CONFIRM.search(x) and 'TOOL_CALL' not in x and not NEG_REQ.search(x):
            return dict(source_id=f'pc_{tool}', sentence=norm_ws(x)[:400], in_packet=False)
    return None


def trigger(packet, row=None):
    out, system = [], C.system_text(row) if row is not None else ''
    for t in packet['current_targets']:
        if t.get('kind') == 'call':
            r = requires_confirmation(t.get('tool'), packet, system)
            if r:
                out.append(dict(target_id=t['source_id'], tool=t['tool'], **r))
    return out


def is_affirmation(text):
    t = norm_ws(text)
    return (bool(C.AFFIRM.search(t)) and not C.RETRACT.search(t) and not t.rstrip().endswith('?') and not CONDITION.search(t))


def is_courtesy(text):
    return bool(COURTESY.match(norm_ws(text)))


def _arg_values(args):
    out = set()
    for v in (args or {}).values():
        if isinstance(v, (str, int, float)) and not isinstance(v, bool) and len(str(v)) >= 3:
            out.add(str(v).lower())
    return out


def substantive(text, args):
    t = (text or '').strip()
    if not t or is_courtesy(t):
        return False
    low = t.lower()
    return bool(re.search(r'\d', t) or '?' in t or C.CONFIRM.search(t) or any(v in low for v in _arg_values(args)))


def binding(row, target_index):
    st, ev = C.timeline(row, target_index)
    call = st.target_events[target_index]
    args = call.value if isinstance(call.value, dict) else None
    prop = None
    for k in range(len(ev) - 1, -1, -1):
        sid, e = ev[k]
        if e.role == 'assistant' and e.kind == 'text' and substantive(e.text, args):
            prop = k
            break
    if prop is None:
        return dict(status='NO_PROPOSAL', proposal=None, users_after=[], affirmation=None)
    users = [(sid, e) for sid, e in ev[prop + 1:] if e.role == 'user' and e.kind == 'text' and e.text.strip()]
    aff, state = None, 'NO_AFFIRMATION'
    for sid, e in users:
        if is_affirmation(e.text):
            aff, state = (sid, e), 'AFFIRMED'
        elif is_courtesy(e.text):
            continue
        elif aff is not None and (C.RETRACT.search(e.text) or re.search(r'\d', e.text) or '?' in e.text):
            aff, state = None, 'REVISED_AFTER_CONSENT'
    return dict(status='AFFIRMED' if aff else state, proposal=C._rec(*ev[prop]), users_after=[C._rec(*u) for u in users],
                affirmation=C._rec(*aff) if aff else None, call=C._rec(f't{target_index}', call), call_args=args)


def compare(executed, proposed, now=None):
    """V4 compare with exact identifier identity: alphanumeric forms must be EQUAL (no substring)."""
    if isinstance(executed, (dict, list)) or executed is None or not str(proposed).strip():
        return 'UNCOMPARABLE'
    ex, pr = str(executed).strip(), str(proposed).strip()
    de, dp = D.parse_date(ex, now), D.parse_date(pr, now)
    if de and dp:
        te, tp = C.TIME.findall(ex), C.TIME.findall(pr)
        return 'MISMATCH' if de != dp or (te and tp and set(te) != set(tp)) else 'MATCH'
    if (isinstance(executed, (int, float)) and not isinstance(executed, bool)) or re.fullmatch(r'-?\d+(?:[.,]\d+)?', ex):
        v = N.to_dec(pr)
        if v is None:
            return 'UNCOMPARABLE'
        return 'MATCH' if N.eq(v, N.to_dec(ex.replace(',', '.'))) else 'MISMATCH'
    a, b = ex.lower(), pr.lower()
    if re.search(r'\d', a) or re.search(r'\d', b):
        if not (re.search(r'\d', a) and re.search(r'\d', b)):
            return 'UNCOMPARABLE'
        na, nb = re.sub(r'[\W_]', '', a), re.sub(r'[\W_]', '', b)
        if na == nb:
            return 'MATCH'
        ida = set(re.findall(r'[a-z]*\d[\w-]*', a))
        idb = set(re.findall(r'[a-z]*\d[\w-]*', b))
        norm = lambda s: {re.sub(r'[\W_]', '', x) for x in s}
        return 'MATCH' if norm(ida) & norm(idb) and (norm(ida) <= norm(idb) or norm(idb) <= norm(ida)) else 'MISMATCH'
    if a == b:
        return 'MATCH'
    return C.compare(executed, proposed, now)
