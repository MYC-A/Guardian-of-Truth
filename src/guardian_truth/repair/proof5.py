"""Repaired typed proof executor (contracts 2-4). Same plan format and operation menu as V4 proof.py, with:
* lazy operations (ADD never evaluates a/b), exact Decimal arithmetic, stated-precision equality;
* datetimes with seconds and timezone (aware vs naive -> UNRESOLVED);
* strict leaf support (evidence.support) and duplicate detection by ATOMIC LEAF IDENTITY (source_id + JSON pointer, or
  source_id + character offset of the value), not by quote text;
* membership: an operand quoting a JSON array is the COMPLETE set (closure COMPLETE); any conclusion 'value not in
  set' needs a complete set; compliance orientation (MEMBER_OF vs NOT_MEMBER_OF) follows the policy wording when the
  wording is unambiguous; value/member roles are swapped when the model put the move's value in 'member';
* entity binding: for entity-attribute relations a move leaf and a non-move leaf whose objects carry the same
  identifier key with different values are about different entities -> UNRESOLVED (ENTITY_CONFLICT);
* applicability is a separate receipt (an exception/condition clause in the rule is never bound by a plan).
Returns the V4 result fields plus `receipt` (contract statuses)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
import re

from ..verification import derived as D
from ..verification.common import MD, norm_ws
from ..verification.proof import SIG, DATE_ROLES, _order
from . import evidence as E, numeric as N, sourcejson as J

ENTITY_OPS = {'EQ', 'NE', 'LATEST_VALUE_EQ', 'MEMBER_OF', 'NOT_MEMBER_OF'}
POS_SET = re.compile(r'\bonly\b[^.;]{0,120}\b(?:includ\w*|contain\w*|listed|among|in (?:the|its|their)\b|one of|allowed|permitted|eligible|supported)|'
                     r'\bmust (?:be|match) (?:one of|in|among|listed)|\b(?:list|set)\b[^.;]{0,40}\bincludes\b|'
                     r'только[^.;]{0,120}(?:входит|включа\w*|в списке|из списка|разреш\w*)', re.I)
NEG_SET = re.compile(r'\bmust not (?:be )?(?:in|one of|among|listed)|\b(?:excluded|blocked|blacklist\w*|forbidden|prohibited|banned)\b|'
                     r'\bcannot be (?:in|one of)|не (?:должн\w* )?(?:входить|быть в)|запрещ\w*|исключ\w*', re.I)
EXC = re.compile(r'\b(?:except|unless|other than|excluding|with the exception|only if|provided that|if and only if|if|whenever|'
                 r'only when|in case|as long as)\b|кроме|за исключением|если|в случае|при условии|пока', re.I)


def orientation(policy_text):
    p, n = bool(POS_SET.search(policy_text or '')), bool(NEG_SET.search(policy_text or ''))
    return 'MEMBER_OF' if p and not n else 'NOT_MEMBER_OF' if n and not p else None


def applicability(policy_text):
    return 'EXCEPTION_OR_CONDITION_UNBOUND' if EXC.search(policy_text or '') else 'APPLICABLE'


def _norm_str(s):
    return norm_ws(str(s)).strip(' "\'«»“”`').lower()


def _typed(x, typ, now):
    """Value of a JSON leaf or raw string as `typ`."""
    if typ == 'number':
        return N.to_dec(x) if not isinstance(x, (list, dict)) else None
    if typ == 'date':
        return D.parse_date(str(x), now) if isinstance(x, (str, int)) else None
    if typ == 'datetime':
        return N.parse_datetime(str(x)) if isinstance(x, str) else None
    if typ == 'weekday':
        return D.parse_weekday(str(x)) if isinstance(x, str) else None
    if typ == 'string':
        return _norm_str(x) if isinstance(x, (str, int, float)) and not isinstance(x, bool) else None
    return None


def _offset(quote, src):
    """Character offset of the quote in the source (whitespace/markdown-insensitive), else None."""
    q = norm_ws(MD.sub('', quote or '')).strip(' "\'')
    if not q:
        return None
    pat = r'\s+'.join(re.escape(w) for w in q.split(' '))
    m = re.search(pat, src or '', re.I)
    return m.start() if m else None


def _parent_ids(src, ptr):
    par = ptr.rsplit('/', 1)[0] if ptr else ''
    try:
        return J.id_fields(J.get(src, par) if par else J.payload(src))
    except (KeyError, IndexError, ValueError, TypeError):
        return {}


def _resolve_json(quote, src, typ, want, now):
    """A verbatim quote on a JSON source names ONE leaf: the unique scalar leaf with the wanted value whose path keys
    occur in the quote. -> (pointer, value) or None. Gives JSON-addressed and verbatim views of one fact the same atom id."""
    q = (quote or '').lower()
    hits = []
    for ptr, node in J.nodes(J.payload(src)):
        if isinstance(node, (dict, list)) or not ptr:
            continue
        v = _typed(node, typ, now)
        if v is None or want is None or not (N.eq(v, want) if typ == 'number' else v == want):
            continue
        keys = [k.replace('~1', '/').replace('~0', '~').lower() for k in ptr.split('/')[1:] if not k.isdigit()]
        if keys and any(k in q for k in keys):
            hits.append((ptr, v))
    return hits[0] if len(hits) == 1 else None


def parse_leaf(o, texts, now=None):
    """-> (list of (value, identity, meta), None) or (None, NOTE). A member operand quoting an array yields every
    element (meta closure='ARRAY'; an empty array yields one marker with meta empty=True); every other operand yields
    exactly one value. Identities are code-owned atoms: (source_id, JSON pointer) for any leaf of a JSON source — also
    when the quote is verbatim text — so one fact has one id; an ARRAY_SUM term owns the whole array pointer."""
    sid, quote, typ, role = o.get('source_id'), o.get('quote') or '', o.get('type'), o.get('role')
    src = texts.get(sid)
    if src is None:
        return None, 'SOURCE_MISSING'
    sup = E.support(quote, src, decisive=True)
    if sup['status'] != 'SUPPORTED':
        return None, 'QUOTE_NOT_SUPPORTED:' + sup['how']
    want = _typed(o.get('value'), typ, now) if typ != 'number' else N.to_dec(o.get('value'))
    if sup['how'] == 'JSON_ADDRESSED':
        a = sup['address']
        if role == 'member':
            arrays = [(p, v) for p, v in a['values'].items() if isinstance(v, list)]
            if len(arrays) == 1 and all(not isinstance(x, (list, dict)) for x in arrays[0][1]):
                p, arr = arrays[0]
                ids = _parent_ids(src, p)
                if not arr:
                    return [(None, (sid, p), dict(closure='ARRAY', array=(sid, p), empty=True, ids=ids))], None
                vals = [(_typed(x, typ, now), (sid, f'{p}/{i}'), dict(closure='ARRAY', array=(sid, p), ids=ids)) for i, x in enumerate(arr)]
                if any(v is None for v, _, _ in vals):
                    return None, 'VALUE_NOT_PARSED'
                return vals, None
        cands = [(p, _typed(v, typ, now)) for p, v in a['values'].items() if not isinstance(v, (list, dict))]
        cands = [(p, v) for p, v in cands if v is not None]
        if want is None and typ != 'string':
            return None, 'VALUE_NOT_PARSED'
        hit = [(p, v) for p, v in cands if (N.eq(v, want) if typ == 'number' else v == want)]
        if not hit and role == 'term' and typ == 'number' and want is not None:
            # amendment A2: a SUM term may be the exact total of ONE addressed array of numbers (empty array -> 0);
            # the term owns the whole array pointer, so any element or other view of it overlaps (DUPLICATE_LEAF)
            arrays = [(p, v) for p, v in a['values'].items() if isinstance(v, list)]
            if len(arrays) == 1 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in arrays[0][1]):
                p, arr = arrays[0]
                tot = sum((N.to_dec(x) for x in arr), N.to_dec(0))
                if N.eq(tot, want):
                    return [(tot, (sid, p), dict(closure='ARRAY_SUM', n=len(arr), ids=_parent_ids(src, p)))], None
        if len(hit) != 1:
            return None, 'VALUE_NOT_IN_QUOTE' if not hit else 'VALUE_AMBIGUOUS_IN_QUOTE'
        p, v = hit[0]
        par = J.get(src, a['parent']) if a['parent'] else J.payload(src)
        return [(v, (sid, p), dict(ids=J.id_fields(par), ambiguous=a['ambiguous']))], None
    if J.payload(src) is not None:
        if role == 'member' and typ != 'number':
            pass                                           # prose member lists of a JSON source: handled below as text
        else:
            r = _resolve_json(quote, src, typ, want, now)
            if r is None:
                return None, 'VERBATIM_ON_JSON_UNRESOLVED'
            p, v = r
            return [(v, (sid, p), dict(ids=_parent_ids(src, p)))], None
    # prose / verbatim quote
    base = _offset(quote, src)
    q = MD.sub('', quote)
    if typ == 'number':
        if want is None:
            return None, 'VALUE_NOT_PARSED'
        hits = [(v, s) for v, s, _ in N.numbers(q) if v == want]
        if not hits:
            return None, 'VALUE_NOT_IN_QUOTE'
        ident = (sid, base + hits[0][1]) if base is not None and len(hits) == 1 else (sid, 'value', str(want))
        return [(want, ident, {})], None
    if typ == 'date':
        if want is None:
            return None, 'VALUE_NOT_PARSED'
        if want not in {x for x, _ in D.dates(q, now)}:
            return None, 'VALUE_NOT_IN_QUOTE'
        return [(want, (sid, base, 'date', want.isoformat()), {})], None
    if typ == 'datetime':
        if want is None:
            return None, 'VALUE_NOT_PARSED'
        if want not in {x for x, _, _ in N.datetimes(q)}:
            return None, 'VALUE_NOT_IN_QUOTE'
        return [(want, (sid, base, 'dt', want.isoformat()), {})], None
    if typ == 'weekday':
        if want is None:
            return None, 'VALUE_NOT_PARSED'
        if want not in D.weekdays(q):
            return None, 'VALUE_NOT_IN_QUOTE'
        return [(want, (sid, base, 'wd', want), {})], None
    if typ == 'string':
        if not want:
            return None, 'VALUE_NOT_PARSED'
        if want not in _norm_str(q):
            return None, 'VALUE_NOT_IN_QUOTE'
        return [(want, (sid, base, 's', want), {})], None
    return None, 'BAD_TYPE'


def _same_kind(a, b):
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return True
    if isinstance(a, dt.datetime) and isinstance(b, dt.datetime):
        return N.comparable(a, b)
    return type(a) is type(b)


def _f(x):
    if isinstance(x, (dt.date, dt.datetime)):
        return x.isoformat()
    if isinstance(x, Decimal):
        return N.fmt(x)
    return str(x)


def _veq(a, b):
    return a == b if not isinstance(a, Decimal) else N.eq(a, b)


def execute(plan, texts, target_ids, now=None, policy_text=''):
    rc = dict(schema_valid=False, source_supported=None, binding_status=None, applicability_status=applicability(policy_text),
              closure_status='NA', execution_status='UNRESOLVED', orientation='MODEL')

    def out(status, **kw):
        rc['execution_status'] = status
        return dict(status=status, receipt=rc, **kw)
    op = plan.get('operation')
    if op not in SIG:
        return out('UNRESOLVED', note='UNKNOWN_OPERATION')
    ops = [dict(o) for o in plan.get('operands') or []]
    pt = plan.get('target_ids') or []
    if not pt or any(t not in target_ids for t in pt):
        return out('UNRESOLVED', note='BAD_TARGET_IDS')
    if op in ('MEMBER_OF', 'NOT_MEMBER_OF'):
        vs = [o for o in ops if o.get('role') == 'value']
        ms = [o for o in ops if o.get('role') == 'member']
        if len(vs) == 1 and len(ms) == 1 and vs[0].get('source_id') not in target_ids and ms[0].get('source_id') in target_ids:
            vs[0]['role'], ms[0]['role'] = 'member', 'value'
            rc['binding_status'] = 'ROLE_SWAPPED'
        o2 = orientation(policy_text)
        if o2 and o2 != op:
            op, rc['orientation'] = o2, 'REORIENTED_FROM_POLICY'
    single, repeated, ntype = SIG[op]
    by = {}
    for o in ops:
        by.setdefault(o.get('role'), []).append(o)
    if set(by) - set(single) - set(repeated):
        return out('UNRESOLVED', note='UNEXPECTED_ROLE')
    if any(len(by.get(r, [])) != 1 for r in single) or any(not by.get(r) for r in repeated):
        return out('UNRESOLVED', note='OPERANDS_MISSING')
    for o in ops:
        if ntype and o.get('type') != ntype:
            return out('UNRESOLVED', note='WRONG_TYPE', role=o.get('role'))
        if o.get('role') in DATE_ROLES and o.get('type') not in ('date', 'datetime'):
            return out('UNRESOLVED', note='WRONG_TYPE', role=o.get('role'))
    rc['schema_valid'] = True
    if not any(o.get('source_id') in target_ids for o in ops):
        rc['binding_status'] = 'NO_TARGET_OPERAND'
        return out('UNRESOLVED', note='NO_TARGET_OPERAND')
    vals, leaves, seen, arrays = {}, [], {}, {}
    for o in ops:
        got, err = parse_leaf(o, texts, now)
        if err:
            rc['source_supported'] = False
            return out('UNRESOLVED', note=err, role=o.get('role'), source_id=o.get('source_id'))
        for v, ident, meta in got:
            arrays.setdefault(o.get('role'), set()).add(meta.get('array'))
            if meta.get('empty'):
                vals.setdefault(o.get('role'), [])
                continue
            if o.get('role') != 'member' and any(_overlap(ident, x) for x in seen):
                rc['source_supported'], rc['binding_status'] = True, 'DUPLICATE_LEAF'
                return out('UNRESOLVED', note='DUPLICATE_LEAF', identity=list(map(str, ident)))
            seen[ident] = o.get('role')
            vals.setdefault(o.get('role'), []).append((v, o, meta))
            leaves.append(dict(role=o.get('role'), source_id=o.get('source_id'), value=_f(v), type=o.get('type'),
                               leaf=str(ident[1]) if len(ident) == 2 else None))
    rc['source_supported'] = True
    # entity binding for EVERY operation (numeric LE/SUM too, ENTITY_OPS kept for compatibility)
    if op:
        tgt = [m.get('ids') or {} for r in vals for v, o, m in vals[r] if o.get('source_id') in target_ids]
        oth = [m.get('ids') or {} for r in vals for v, o, m in vals[r] if o.get('source_id') not in target_ids]
        if any(k in b and str(a[k]) != str(b[k]) for a in tgt for b in oth for k in a):
            rc['binding_status'] = 'ENTITY_CONFLICT'
            return out('UNRESOLVED', note='ENTITY_CONFLICT', leaves=leaves)
    rc['binding_status'] = rc['binding_status'] or 'BOUND'
    if op in ('MEMBER_OF', 'NOT_MEMBER_OF'):
        arrs = arrays.get('member', set())
        rc['closure_status'] = 'COMPLETE' if len(arrs) == 1 and None not in arrs else 'PARTIAL'
    if any(not vals.get(r) for r in single):
        return out('UNRESOLVED', note='EMPTY_OPERAND', leaves=leaves)
    one = {r: vals[r][0][0] for r in single}
    many = {r: [v for v, _, _ in vals[r]] for r in repeated}
    try:
        holds, detail = _run(op, one, many, vals)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError, InvalidOperation) as ex:
        return out('UNRESOLVED', note=f'EXEC_ERROR:{type(ex).__name__}', leaves=leaves)
    if holds is None:
        return out('UNRESOLVED', note=detail, leaves=leaves)
    if op in ('MEMBER_OF', 'NOT_MEMBER_OF') and rc['closure_status'] != 'COMPLETE':
        inside = holds if op == 'MEMBER_OF' else not holds
        if not inside:                                     # 'not in the set' needs the complete set
            return out('UNRESOLVED', note='MEMBERSHIP_SET_INCOMPLETE', leaves=leaves, detail=detail)
    return out('HOLDS' if holds else 'VIOLATED', detail=detail, leaves=leaves, operation=op)


def _overlap(a, b):
    """Two atom ids denote overlapping facts: same id, or one JSON pointer contains the other (array vs its element)."""
    if a == b:
        return True
    if len(a) == 2 and len(b) == 2 and a[0] == b[0] and isinstance(a[1], str) and isinstance(b[1], str) \
            and a[1].startswith('/') and b[1].startswith('/'):
        return a[1].startswith(b[1] + '/') or b[1].startswith(a[1] + '/')
    return False


def _run(op, one, many, vals):
    from ..verification.proof import CMP
    if op in CMP:
        a, b = one['left'], one['right']
        if not _same_kind(a, b) or (isinstance(a, str) and op not in ('EQ', 'NE')):
            return None, 'INCOMPARABLE_TYPES'
        if op in ('EQ', 'NE'):
            e = _veq(a, b)
            return (e if op == 'EQ' else not e), f'{_f(a)} {op} {_f(b)}'
        return CMP[op](a, b), f'{_f(a)} {op} {_f(b)}'
    if op.startswith('SUM_COMPARE_'):
        s = sum(many['term'], Decimal(0))
        k = op.rsplit('_', 1)[1]
        return CMP[k](s, one['bound']), ' + '.join(_f(x) for x in many['term']) + f' = {_f(s)}; {_f(s)} {k} {_f(one["bound"])} required'
    if op == 'SUM':
        s = sum(many['term'], Decimal(0))
        return N.stated_equal(s, one['result']), ' + '.join(_f(x) for x in many['term']) + f' = {_f(s)} (stated {_f(one["result"])})'
    if op in ('ADD', 'SUB', 'MUL', 'DIV'):
        a, b = one['left'], one['right']
        if op == 'DIV' and b == 0:
            return None, 'DIVISION_BY_ZERO'
        c = a + b if op == 'ADD' else a - b if op == 'SUB' else a * b if op == 'MUL' else a / b
        sym = {'ADD': '+', 'SUB': '-', 'MUL': '*', 'DIV': '/'}[op]
        return N.stated_equal(c, one['result']), f'{_f(a)} {sym} {_f(b)} = {_f(c)} (stated {_f(one["result"])})'
    if op in ('DATE_DIFF_DAYS', 'DATE_DIFF_NIGHTS'):
        a, b, r = one['start'], one['end'], one['result']
        if not isinstance(r, Decimal):
            return None, 'WRONG_TYPE'
        a, b = (a.date() if isinstance(a, dt.datetime) else a), (b.date() if isinstance(b, dt.datetime) else b)
        n = (b - a).days
        return N.eq(n, r), f'{_f(a)} -> {_f(b)} = {n} {"nights" if op.endswith("NIGHTS") else "days"} (stated {_f(r)})'
    if op == 'WEEKDAY_OF':
        d, w = one['date'], one['result']
        if not isinstance(w, int) or isinstance(w, bool):
            return None, 'WRONG_TYPE'
        return d.weekday() == w, f'{_f(d)} is {D.WEEKDAYS[d.weekday()][1]} (stated {D.WEEKDAYS[w][1]})'
    if op in ('ADD_DAYS', 'ADD_BUSINESS_DAYS', 'NEXT_BUSINESS_DAY'):
        d, r = one['date'], one['result']
        d = d.date() if isinstance(d, dt.datetime) else d
        r = r.date() if isinstance(r, dt.datetime) else r
        if not isinstance(r, dt.date):
            return None, 'WRONG_TYPE'
        if op == 'NEXT_BUSINESS_DAY':
            c = D.next_business_day(d)
        else:
            n = one['n']
            if not isinstance(n, Decimal) or n != n.to_integral_value() or not 0 <= n <= 366:
                return None, 'BAD_N'
            c = d + dt.timedelta(days=int(n)) if op == 'ADD_DAYS' else D.add_business_days(d, int(n))
        return c == r, f'{op}({_f(d)}{", " + _f(one["n"]) if "n" in one else ""}) = {_f(c)} (stated {_f(r)})'
    if op in ('BEFORE', 'AFTER'):
        a, b = one['left'], one['right']
        if not isinstance(a, (dt.date, dt.datetime)) or not isinstance(b, (dt.date, dt.datetime)):
            return None, 'WRONG_TYPE'
        if type(a) is not type(b):
            a, b = (a.date() if isinstance(a, dt.datetime) else a), (b.date() if isinstance(b, dt.datetime) else b)
        elif isinstance(a, dt.datetime) and not N.comparable(a, b):
            return None, 'TIMEZONE_INCOMPARABLE'
        return (a < b) if op == 'BEFORE' else (a > b), f'{_f(a)} {op} {_f(b)}'
    if op == 'LATEST_VALUE_EQ':
        obs = sorted(vals['observed'], key=lambda vo: _order(vo[1].get('source_id')))
        if any(_order(o.get('source_id')) < 0 or o.get('source_id', '').startswith('t') for _, o, _ in obs):
            return None, 'OBSERVED_NOT_IN_HISTORY'
        latest, src = obs[-1][0], obs[-1][1].get('source_id')
        v = one['value']
        if not _same_kind(v, latest):
            return None, 'INCOMPARABLE_TYPES'
        return _veq(v, latest), f'latest observed value ({src}) = {_f(latest)}; used {_f(v)}'
    if op in ('MEMBER_OF', 'NOT_MEMBER_OF'):
        v, mem = one['value'], many['member']
        if not all(_same_kind(v, m) for m in mem):
            return None, 'INCOMPARABLE_TYPES'
        inside = any(_veq(v, m) for m in mem)
        return inside if op == 'MEMBER_OF' else not inside, f'{_f(v)} {"in" if inside else "not in"} {{' + ', '.join(_f(m) for m in mem) + '}'
    return None, 'UNKNOWN_OPERATION'


def certificate(res):
    """Full mechanical certificate (contract 5): every receipt status is the strongest one."""
    r = res.get('receipt') or {}
    return (res.get('status') == 'VIOLATED' and r.get('schema_valid') and r.get('source_supported')
            and r.get('binding_status') in ('BOUND', 'ROLE_SWAPPED') and r.get('applicability_status') == 'APPLICABLE'
            and r.get('closure_status') in ('NA', 'COMPLETE'))
