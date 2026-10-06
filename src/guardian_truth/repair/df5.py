"""Repaired DF (derived facts) checker. Identical binder request to V4 df4 for the first 10 claims (stored replies
replay), with these flag-gated repairs:
* 'df_scope'   assertion scope: a value the move REJECTS, attributes to someone else, quotes, or negates
               ("I reject the incorrect claim 2 + 2 = 5") is not an assertion of the move -> NOT_ASSERTED.
* 'df_copy'    scoped copy: the claimed value counts as copied only from a tool result the binding itself cites, or a
               result leaf whose object identifier / key words occur in the claim's context (V4: ANY result anywhere).
* 'df_entity'  entity binding: an operand quoting a different identifier of the same shape than the claim -> UNVERIFIED.
* 'df_overflow' claims beyond the first 10 are bound by additional binder calls (offline: UNCHECKED, never dropped).
* 'exec'       exact Decimal arithmetic and stated-precision equality (no 1e-4 relative tolerance)."""
from __future__ import annotations

import ast
import datetime as dt
from decimal import Decimal, InvalidOperation
import operator
import re

from ..verification import derived as D, df, df4
from ..verification.common import call, quote_fragments_ok, request, step_record
from ..verification.proof import leaf_quote_ok, numbers_grounded
from . import evidence as Ev, numeric as N, sourcejson as J

REJECT = re.compile(r"\b(?:incorrect|wrong|mistaken|false|untrue|not (?:correct|right|true|accurate)|reject\w*|erroneous|"
                    r"you (?:said|mentioned|wrote|claimed|stated|suggested)|(?:the|your|their) claim|claim(?:ed|s)? that)\b|"
                    r"неверн\w*|ошибочн\w*|неправильн\w*|некорректн\w*|вы (?:сказали|указали|написали|утверждали)|утвержден\w* о том", re.I)
NEG_BEFORE = re.compile(r"(?:\bnot|n't|\bnever|\binstead of|\brather than|(?<!\w)не|(?<!\w)вместо|(?<!\w)а не)\s*(?:[\w€$£₽.,:]+\s*){0,2}$", re.I)
IDTOK = re.compile(r'(?<![\w#-])#?[A-Z][A-Z0-9]*-?\d[\w-]*|(?<=[a-zA-Zа-яА-Я]{3} )[A-Z](?![\w-])')
QUOTED = re.compile(r'"[^"\n]{1,200}"|«[^»\n]{1,200}»|“[^”\n]{1,200}”')


def _sentence(text, start, end):
    a = max(text.rfind('. ', 0, start), text.rfind('\n', 0, start), text.rfind('! ', 0, start), text.rfind('? ', 0, start))
    bs = [i for i in (text.find('. ', end), text.find('\n', end), text.find('! ', end), text.find('? ', end)) if i >= 0]
    return text[a + 1:(min(bs) if bs else len(text))]


def asserted(text, start, end):
    """-> None if the move asserts the value at text[start:end], else the reason it does not."""
    if REJECT.search(_sentence(text, start, end)):
        return 'REJECTED_OR_ATTRIBUTED'
    if NEG_BEFORE.search(text[max(0, start - 30):start]):
        return 'NEGATED'
    if any(m.start() < start and end <= m.end() for m in QUOTED.finditer(text)):
        return 'QUOTED'
    return None


def id_class(tok):
    m = re.match(r'#?[A-Za-z]*', tok)
    return 'L' if len(tok) == 1 else m.group(0).upper()


def ids(s):
    return {(id_class(t), t.upper()) for t in IDTOK.findall(s or '')}


def entity_conflict(claim_ctx, operand_quote, operand_src):
    """Claim names identifiers of a class, the operand (quote or its JSON object's id fields) names only OTHER
    identifiers of that class -> conflict."""
    c = ids(claim_ctx)
    o = ids(operand_quote)
    a = J.addressed(operand_quote, operand_src) if J.payload(operand_src) is not None else None
    if a:
        par = J.get(operand_src, a['parent']) if a['parent'] else J.payload(operand_src)
        o |= {(id_class(str(v)), str(v).upper()) for v in J.id_fields(par).values() if IDTOK.fullmatch(str(v))}
    for cls in {k for k, _ in c} & {k for k, _ in o}:
        cv, ov = {v for k, v in c if k == cls}, {v for k, v in o if k == cls}
        if not cv & ov:
            return True
    return False


def scoped_copied(claim, results, bound_sources, nd):
    """results: {source_id: text}. The claimed value is copied when it is a value of a cited result, or of a result
    whose object identifier or key words occur in the claim's context."""
    v, ctx = claim['value'], (claim.get('context') or '').lower()
    for sid, t in results.items():
        if claim['kind'] == 'date':
            has = v in {d for d, _ in D.dates(t, nd)}
        else:
            has = v >= 10 and any(N.eq(v, y) for y, _, _ in N.numbers(t))
        if not has:
            continue
        if sid in bound_sources:
            return True
        p = J.payload(t)
        if p is None:
            continue
        for ptr, node in J.nodes(p):
            if not isinstance(node, dict):
                continue
            for k, x in node.items():
                xv = (D.parse_date(str(x), nd) if claim['kind'] == 'date' else N.to_dec(x) if isinstance(x, (int, float, str)) else None)
                if xv is None or (xv != v if claim['kind'] == 'date' else not N.eq(xv, v)):
                    continue
                words = [w for w in re.split(r'[_\W]+', str(k).lower()) if len(w) >= 3]
                idv = [str(i).lower() for i in J.id_fields(node).values()]
                if any(w in ctx for w in words) or any(i and i in ctx for i in idv):
                    return True
    return False


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def dec_arith(expr, values):
    """Exact Decimal evaluation of + - * / over numbers and operand names (V4 used floats)."""
    if not isinstance(expr, str) or not expr.strip() or len(expr) > 200:
        return None
    e = expr.replace('×', '*').replace('−', '-').replace('·', '*').strip()
    try:
        tree = ast.parse(e, mode='eval')
    except SyntaxError:
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return N.to_dec(n.value)
        if isinstance(n, ast.Name):
            if values.get(n.id) is None:
                raise ValueError('unknown operand')
            return N.to_dec(values[n.id])
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        raise ValueError('unsupported')
    try:
        return ev(tree)
    except (ValueError, ZeroDivisionError, TypeError, RecursionError, InvalidOperation):
        return None


def stated_text(s):
    ns = N.numbers(re.sub(r'[€$£₽]', ' ', s or ''))
    return ns[0][0] if len(ns) == 1 else None


def stated(claim):
    """The claimed number as WRITTEN (keeps '278.00' precision), else the parsed value."""
    v = stated_text(claim.get('span'))
    return v if v is not None else claim['value']


def self_checks(tid, text, nd, claims, flags):
    res = df4.self_checks(tid, text, nd, claims)
    out = []
    for r in res:
        if 'exec' in flags and r['check'] == 'INLINE_ARITHMETIC':
            m = next((m for m in list(df4.INLINE.finditer(text)) + list(df4.INLINE_L.finditer(text)) if m[0] == r['claim_quote']), None)
            if m is not None:
                left_is_expr = bool(df4.INLINE.fullmatch(m[0]))
                expr = df4._expr(m[1] if left_is_expr else m[2])
                claimed = stated_text(m[2] if left_is_expr else m[1])
                c = dec_arith(expr, {}) if expr else None
                if c is not None and claimed is not None:
                    r = dict(r, status='MATCH' if N.stated_equal(c, claimed) else 'MISMATCH')
        if 'df_scope' in flags and r['status'] == 'MISMATCH':
            pos = text.find(r['claim_quote'])
            why = asserted(text, pos, pos + len(r['claim_quote'])) if pos >= 0 else None
            if why:
                r = dict(r, status='NOT_ASSERTED', scope=why)
        out.append(r)
    return out


def evaluate(b, claim, texts, nd, tgt_ids, nonmove, results, flags):
    """V4 evaluate_binding with the flag-gated repairs (copy scope, entity binding, Decimal equality)."""
    op = b.get('operation')
    if op == 'NOT_DERIVED':
        return dict(status='SKIP')
    if 'df_scope' in flags:
        why = claim.get('not_asserted')
        if why:
            return dict(status='NOT_ASSERTED', note=why)
    bound = {o.get('source_id') for o in b.get('operands') or []}
    if op != 'WEEKDAY_OF':
        if 'df_copy' in flags:
            if scoped_copied(claim, results, bound, nd):
                return dict(status='SKIP', note='CLAIM_VALUE_COPIED_FROM_BOUND_RESULT')
        elif df4.copied_from_result(claim, list(results.values()), nd):
            return dict(status='SKIP', note='CLAIM_VALUE_IN_TOOL_RESULT')
    if 'df_entity' in flags:
        for o in b.get('operands') or []:
            src = texts.get(o.get('source_id'))
            if src is not None and o.get('source_id') not in tgt_ids and entity_conflict(claim.get('context'), o.get('quote'), src):
                return dict(status='UNVERIFIED', note='ENTITY_CONFLICT', operand=o.get('name'))
    if 'exec' in flags and op == 'ARITHMETIC':
        r = df4.evaluate_binding(dict(b), dict(claim, operand_of_expression=claim.get('operand_of_expression')), texts, nd, tgt_ids, nonmove, ())
        if r.get('status') in ('MATCH', 'MISMATCH'):
            vals = {}
            for name, o in {(o.get('name') or '').strip().lower(): o for o in b.get('operands') or []}.items():
                v, e = df4.operand_value(o, 'number', texts, nd, tgt_ids, nonmove)
                if e:
                    return dict(status='UNVERIFIED', note=e)
                vals[name] = v
            c = dec_arith((b.get('expression') or '').lower(), vals)
            if c is None:
                return dict(status='UNVERIFIED', note='EXPRESSION_NOT_EVALUATED')
            ok = N.stated_equal(c, stated(claim))
            return dict(r, status='MATCH' if ok else 'MISMATCH', computed=float(c))
        return r
    r = df4.evaluate_binding(b, claim, texts, nd, tgt_ids, nonmove, ())
    if 'exec' in flags and op == 'DATE_DIFF' and r.get('status') in ('MATCH', 'MISMATCH'):
        r = dict(r, status='MATCH' if N.eq(r['computed'], claim['value']) else 'MISMATCH')
    return r


def _claims(packet, nd, flags):
    tg = [t for t in packet['current_targets'] if t.get('kind') == 'text']
    checks, claims = [], []
    for t in tg:
        x = t['text'] or ''
        cl = df4.extract(x, nd)
        sc = self_checks(t['source_id'], x, nd, cl, flags)
        checks += sc
        used = {p for c in df4.self_checks(t['source_id'], x, nd, cl) for p in c.get('used', [])}
        spans = [c['span'] for c in df4.self_checks(t['source_id'], x, nd, cl) if c.get('span')]
        for c in cl:
            if c['kind'] == 'weekday' and c['start'] in used:
                continue
            if any(a <= c['start'] < b for a, b in spans):
                continue
            ctx = x[max(0, c['start'] - 60):c['end'] + 40]
            near = x[max(0, c['start'] - 3):c['start']] + '|' + x[c['end']:c['end'] + 3]
            opnd = bool(re.search(r'[×*·+]|\s[−-]\s|\(|\)', near.replace('|', ' ')))
            claims.append(dict(c, target_id=t['source_id'], context=ctx, operand_of_expression=opnd,
                               not_asserted=asserted(x, c['start'], c['end'])))
    return checks, claims


def _bind(client, packet, pk, claims, model, attempt, st, extra, tag):
    user = dict(pk, reference_now=st['now']['value'],
                claims=[dict(claim_id=c['claim_id'], target_id=c['target_id'], kind=c['kind'], value_as_written=c['span'], context=c['context']) for c in claims])
    req = request(model, df4.BINDER, user, df4.schema(packet, [c['claim_id'] for c in claims], [x['source_id'] for x in extra]), 'derived_binding', max_tokens=1800)
    rec, v, _ = call(client, req, attempt, tag)
    return rec, v, step_record(rec, tag, req)


def run(client, packet, model, attempt=0, row=None, flags=frozenset()):
    """-> V4-shaped record with `candidates` (every MISMATCH, move order) and `candidate` (first)."""
    st = dict(tag='df5', flags=sorted(flags))
    now, fb = df4._now(packet, row)
    nd = now[0].date() if now else None
    st['now'] = dict(value=now[0].isoformat(sep=' ', timespec='minutes') if now else None, origin='full_system_fallback' if fb else 'packet' if now else None)
    checks, claims = _claims(packet, nd, flags)
    st['self_checks'] = checks
    cands = [df4._cand(c['target_id'], c['claim_quote'], c, [], c['check'], True, by_code=True) for c in checks if c['status'] == 'MISMATCH']
    head, tail = claims[:10], claims[10:]
    for i, c in enumerate(claims):
        c['claim_id'] = f'c{i + 1}'
    st['claims'] = [dict(claim_id=c['claim_id'], target_id=c['target_id'], kind=c['kind'], span=c['span'], not_asserted=c['not_asserted'],
                         value=c['value'].isoformat() if isinstance(c['value'], dt.date) else df4.WD_EN[c['value']] if c['kind'] == 'weekday' else c['value'])
                    for c in claims]
    st['overflow_claims'] = len(tail)
    if (cands and 'pool' not in flags) or not head:
        st.update(admission='CODE_ONLY', candidates=cands, candidate=cands[0] if cands else None, bindings=[])
        return st
    extra = [fb] if fb else []
    pk = dict(packet, normative_sources=packet['normative_sources'] + extra) if extra else packet
    batches = [head] + ([tail[i:i + 10] for i in range(0, len(tail), 10)] if 'df_overflow' in flags else [])
    tgt_ids = {t['source_id'] for t in packet['current_targets']}
    nonmove = {s['source_id']: s['text'] for k in ('normative_sources', 'history', 'declarations') for s in pk[k]}
    texts = dict(nonmove, **{t['source_id']: t['text'] for t in packet['current_targets']})
    results = {h['source_id']: h['text'] for h in packet['history'] if h.get('kind') == 'result'}
    out, steps, adm = [], [], []
    for bi, batch in enumerate(batches):
        # batch 0 keeps V4's claim ids c1..c10 and request; overflow batches renumber inside their own request
        if bi:
            for j, c in enumerate(batch):
                c['claim_id'] = f'c{j + 1}'
        rec, v, step = _bind(client, packet, pk, batch, model, attempt, st, extra, 'df4_bind' if bi == 0 else f'df5_bind_overflow{bi}')
        steps.append(step)
        if rec.get('content') is None:
            adm.append('NOT_EXECUTED' if (rec.get('transport') or {}).get('status') == 'NOT_EXECUTED_OFFLINE' else 'TRANSPORT_FAILURE')
            continue
        if not v or not isinstance(v.get('bindings'), list):
            adm.append('INVALID_JSON')
            continue
        adm.append('ADMITTED')
        byc = {c['claim_id']: c for c in batch}
        for b in v['bindings']:
            c = byc.get(b.get('claim_id'))
            if c is None:
                continue
            r = evaluate(b, c, texts, nd, tgt_ids, nonmove, results, flags)
            out.append(dict(b, batch=bi, check=r))
            if r['status'] == 'MISMATCH':
                ev = [o['source_id'] for o in b.get('operands') or [] if o.get('source_id') not in tgt_ids]
                cd = df4._cand(c['target_id'], c['context'].strip() if len(c['span']) < 6 else c['span'], r, ev, 'BOUND_' + b['operation'], not r.get('literals'))
                if fb and 'qf_now' in ev:
                    cd['extra_policy'] = [dict(source_id=fb['source_id'], text=fb['text'])]
                cands.append(cd)
    st['step'] = steps[0] if steps else None
    st['overflow_steps'] = steps[1:]
    if tail and 'df_overflow' not in flags:
        adm.append('OVERFLOW_UNCHECKED')
    st.update(admission=adm[0] if adm else 'NO_BINDING', batch_admission=adm, bindings=out, candidates=cands, candidate=cands[0] if cands else None,
              counts={k: sum(x['check']['status'] == k for x in out) for k in ('MATCH', 'MISMATCH', 'UNVERIFIED', 'SKIP', 'NOT_ASSERTED')})
    return st
