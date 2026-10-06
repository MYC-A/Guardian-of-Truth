"""Layer P (fixed): argument provenance with field schema, exact case, and an explicit provenance contract.

For each string argument of a current call the layer records provenance (never correctness):
  FOUND            exact, case-sensitive match as a JSON leaf of a tool result, or as a whole token of a user message,
                   or in the policy (declaration examples 'such as ...' do not count); paths/keys of every match kept
  NOT_FOUND        none of the above on a COMPLETE input
  UNKNOWN_INCOMPLETE  input not complete: absence is never evidence
A FOUND value says nothing about binding to the right entity (binding='UNVERIFIED'); a match only under a different key
is flagged FOUND_UNDER_OTHER_KEY.
A finding UNSOURCED_REFERENCE is raised only for a field the catalog schema declares as a reference to an existing
object (name/description is an id/identifier; no 'new'/'generate'/'create' wording; string or array type), with value
NOT_FOUND. Computed values (amounts, counts, free text) and fields whose ids may be newly generated are out of scope.
Status MECHANICAL requires an explicit provenance contract in the current input (policy/declaration sentence forbidding
made-up values or requiring the value to come from the user/tools), quoted, whose scope covers the field: it names the
field, or speaks of ids/values in general; a sentence about another field ("The recipient must come from the user")
does not cover order_id. Otherwise HYPOTHESIS. A user-only contract (".. must come from the user") that names a field
also covers non-reference fields (NOT_FROM_USER): the value must occur in a user message of this input."""
from __future__ import annotations

import json
import re

from .common import catalog, complete, parse_call, parse_result

REF_NAME = re.compile(r'(^|_)(id|ids|identifier)$', re.I)
REF_DESC = re.compile(r'\b(id|ids|identifier|identifiers)\b', re.I)
GENERATED = re.compile(r'\b(new|generate[sd]?|create[sd]?|choose|chosen|custom|arbitrary|any)\b', re.I)
EXAMPLE = re.compile(r'(such as|e\.g\.|for example|for instance|например|example:?)[^.\n;]{0,60}$', re.I)
CONTRACT = re.compile(r"[^.\n]*\b(?:(?:not|never|don't|do not)\s+(?:make up|invent|fabricate|guess)\b[^.\n]*"
                      r"|must (?:come|be obtained|be taken) (?:directly )?from\b[^.\n]*"
                      r"|only (?:use )?(?:values|ids|identifiers) (?:provided|returned) by\b[^.\n]*)[.\n]?", re.I)
FROM_USER = re.compile(r'(directly )?from the user\b(?! or)', re.I)


def _leaves(v, path=''):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from _leaves(x, f'{path}.{k}' if path else str(k))
    elif isinstance(v, list):
        for n, x in enumerate(v):
            yield from _leaves(x, f'{path}[{n}]')
    else:
        yield path, v


def _token_in(val, text):
    return re.search(r'(?<![A-Za-z0-9_])' + re.escape(val) + r'(?![A-Za-z0-9_])', text) is not None


def _norm_hits(val, text):
    for m in re.finditer(r'(?<![A-Za-z0-9_])' + re.escape(val) + r'(?![A-Za-z0-9_])', text):
        if not EXAMPLE.search(text[max(0, m.start() - 80):m.start()]):
            return True
    return False


def _same_key(field, path):
    key = path.split('.')[-1].split('[')[0]
    if key == field:
        return True
    stem = field[:-3] if field.endswith('_id') else field[:-4] if field.endswith('_ids') else None
    return key == 'id' and bool(stem) and stem.split('_')[0] in path     # e.g. payment_methods[0].id for payment_method_id


def provenance(p, val, field):
    """-> dict(status, found=[{source_id, kind, path}], binding='UNVERIFIED')."""
    if not complete(p):
        return dict(status='UNKNOWN_INCOMPLETE', found=[], binding='UNVERIFIED')
    found = []
    for x in p['history']:
        if x.get('kind') == 'result':
            _, pl = parse_result(x)
            if isinstance(pl, (dict, list)):
                for path, leaf in _leaves(pl):
                    if isinstance(leaf, str) and leaf == val:
                        found.append(dict(source_id=x['source_id'], kind='tool_result', path=path))
            elif isinstance(pl, str) and _token_in(val, pl):
                found.append(dict(source_id=x['source_id'], kind='tool_result', path=None))
        elif x.get('role') == 'user' and x.get('kind') == 'text' and _token_in(val, x.get('text') or ''):
            found.append(dict(source_id=x['source_id'], kind='user', path=None))
    for s in p['normative_sources'] + p['declarations']:
        if _norm_hits(val, s['text']):
            found.append(dict(source_id=s['source_id'], kind='policy', path=None))
    if not found:
        return dict(status='NOT_FOUND', found=[], binding='UNVERIFIED')
    res_paths = [f['path'] for f in found if f['kind'] == 'tool_result' and f['path']]
    st = 'FOUND_UNDER_OTHER_KEY' if res_paths and not any(_same_key(field, pth) for pth in res_paths) else 'FOUND'
    return dict(status=st, found=found, binding='UNVERIFIED')


def field_kind(spec, name):
    if spec is None:
        return 'UNKNOWN_SCHEMA'
    if spec['type'] not in ('string', 'array'):
        return 'VALUE'
    if spec.get('enum'):
        return 'ENUM'
    if GENERATED.search(spec.get('desc') or ''):
        return 'MAY_BE_NEW'
    if REF_NAME.search(name) or REF_DESC.search(spec.get('desc') or ''):
        return 'REFERENCE'
    return 'VALUE'


GENERIC = re.compile(r'\b(ids?|identifiers?|values?|arguments?|parameters?|inputs?|information|data|details|knowledge|anything)\b', re.I)
AGENT = re.compile(r'^\s*(you|we|i|the agent|the assistant|agents?)?\s*(should|must|shall|will)?\s*$', re.I)


def _names(field):
    stem = re.sub(r'_(id|ids|identifier)$', '', field)
    return {field, field.replace('_', ' '), stem.replace('_', ' ')}


def contracts(p):
    """Every explicit provenance-contract sentence of the current input, quoted, with its scope: the fields it names, or
    GENERIC when it speaks of ids/values/arguments in general."""
    out = []
    for s in p['normative_sources'] + p['declarations']:
        for m in CONTRACT.finditer(s['text']):
            q = m.group(0).strip()
            out.append(dict(basis='CONTRACT_TEXT', source_id=s['source_id'], quote=q, user_only=bool(FROM_USER.search(q))))
    return out


def applies(con, field):
    """-> 'NAMED' if the contract sentence names this field, 'GENERIC' if it is about ids/values/information in general,
    else None. A sentence whose grammatical subject is a specific other thing ("The recipient must come from the user")
    covers only what it names."""
    q = con['quote']
    if any(re.search(r'(?<![A-Za-z0-9_])' + re.escape(n) + r'(?![A-Za-z0-9_])', q, re.I) for n in _names(field) if len(n) >= 3):
        return 'NAMED'
    subject = re.split(r"\b(?:must|should|shall|do not|don't|never|not|only)\b", q, maxsplit=1, flags=re.I)[0]
    if AGENT.match(subject):                     # "You should not make up any information ..." -> object decides
        return 'GENERIC' if GENERIC.search(q) else None
    return 'GENERIC' if GENERIC.search(subject) else None


def contract(p):
    c = contracts(p)
    return c[0] if c else None


def check(p):
    cat, out, records = catalog(p), [], []
    cons = contracts(p)
    for t in p['current_targets']:
        if t['kind'] != 'call':
            continue
        tool, args = parse_call(t)
        if not isinstance(args, dict):
            continue
        fields = (cat.get(tool) or {}).get('fields') or {}
        for name, v in args.items():
            vals = [v] if isinstance(v, str) else [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
            fk = field_kind(fields.get(name), name)
            scoped = [(c, applies(c, name)) for c in cons]
            scoped = [(c, a) for c, a in scoped if a]
            for val in vals:
                pr = provenance(p, val, name)
                rec = dict(target_id=t['source_id'], tool=tool, field=name, value=val, field_kind=fk, **pr)
                records.append(rec)
                from_user = any(f['kind'] == 'user' for f in pr['found'])
                # (a) user-only contract that NAMES this field: any field kind, value must occur in a user message
                user_named = [c for c, a in scoped if a == 'NAMED' and c['user_only']]
                # (b) reference field: NOT_FOUND, or a generic/named user-only contract and not from the user
                user_ref = [c for c, a in scoped if c['user_only']]
                con = None
                if user_named and pr['status'] != 'UNKNOWN_INCOMPLETE' and not from_user:
                    con = user_named[0]
                elif fk == 'REFERENCE' and pr['status'] == 'NOT_FOUND':
                    con = scoped[0][0] if scoped else False
                elif fk == 'REFERENCE' and user_ref and pr['status'].startswith('FOUND') and not from_user:
                    con = user_ref[0]
                if con is None:
                    continue
                out.append(dict(layer='P', kind='UNSOURCED_REFERENCE' if fk == 'REFERENCE' else 'NOT_FROM_USER',
                                target_id=t['source_id'], status='MECHANICAL' if con else 'HYPOTHESIS',
                                fact=dict(tool=tool, field=name, value=val, provenance=pr['status'],
                                          found_kinds=sorted({f['kind'] for f in pr['found']}), field_kind=fk),
                                norm=con or dict(basis='NONE', text='no provenance contract of this input covers this field'),
                                reason=f'{t["source_id"]} calls {tool} with {name}={json.dumps(val)}: ' +
                                       ('a reference to an existing object that appears in no user message, tool result or '
                                        'policy of this complete input.' if pr['status'] == 'NOT_FOUND' else
                                        'the value does not occur in any user message, but the contract requires it from the user.')))
    return out, records


def recheck(p, f):
    again = [x for x in check(p)[0] if x['kind'] == f['kind'] and x['target_id'] == f['target_id'] and x['fact'] == f['fact']]
    return bool(again)
