"""P: observed value provenance, separate from semantic/entity correctness.

FOUND is exact occurrence, never correct entity binding. NOT_FOUND only describes
a completely read input. Decisive absence additionally requires explicit caller
provenance_universe_closed, or a norm explicitly bounded to this input.

Only full clauses in the documented no-invent/user-origin grammar can decide.
Field names match exactly modulo underscores/spaces; optional tool scope matches
an explicit identifier. Other scopes, negation, source alternatives and inherited
guards remain hypotheses. This bounded compiler is not an arbitrary NL compiler.
"""
from __future__ import annotations

import json
import re

from .common import catalog, complete, coverage, parse_call, parse_result

REF_NAME = re.compile(r'(^|_)(id|ids|identifier)$', re.I)
REF_DESC = re.compile(r'\b(id|ids|identifier|identifiers)\b', re.I)
GENERATED = re.compile(r'\b(generate[sd]?|create[sd]?|chosen|custom|arbitrary)\b|\bnew (?:unique )?(?:id|identifier|password)\b', re.I)
EXAMPLE = re.compile(r'(such as|e\.g\.|for example|for instance|например|example:?)[^.\n;]{0,60}$', re.I)
CONTRACT = re.compile(r"[^.\n]*\b(?:(?:not|never|don't|do not)\s+(?:make up|invent|fabricate|guess)\b[^.\n]*"
                      r"|must (?:come|be obtained|be taken) (?:directly )?from\b[^.\n]*"
                      r"|only (?:use )?(?:values|ids|identifiers) (?:provided|returned)(?: verbatim)? by\b[^.\n]*)[.\n]?", re.I)
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
    # Field identity is exact modulo presentation. A stem such as "order" is
    # useful for retrieval, but is not the field "order_id".
    return {field.lower(), field.replace('_', ' ').lower()}


USER_REQUIREMENT = re.compile(
    r'(?P<subject>.+?)\s+must (?:come|be obtained|be taken) (?:directly )?from the user'
    r'(?P<window> in this (?:input|conversation))?[.!]?$', re.I)
NO_INVENT = re.compile(
    r'(?:you|the agent|the assistant)\s+(?:(?:must|should|shall) not|may not|cannot|can not|'
    r"do not|don't|must never|should never)\s+(?:make up|invent|fabricate|guess)\s+"
    r'(?P<object>.+?)[.!]?$', re.I)
SOURCE_ONLY = re.compile(
    r'(?:you (?:must|should|shall) )?only use (?P<object>values|ids|identifiers) '
    r'(?:provided|returned)(?P<verbatim> verbatim)? by the user or the tools'
    r'(?P<window> in this (?:input|conversation))?[.!]?$', re.I)
GENERIC_OBJECT = re.compile(
    r'(?:any |the )?(?:ids?|identifiers?|values?|arguments?|parameters?|inputs?|information|data|details|knowledge)'
    r'(?:\s+or\s+(?:knowledge|information|procedures))*'
    r'(?:\s+not provided by the user or the tools(?: in this (?:input|conversation))?)?'
    r'(?:,\s*or give subjective recommendations or comments)?', re.I)
CONTEXT_GUARD = re.compile(
    r'\b(if|when|unless|except|excluding|provided that|only for|only when|does not apply|not applicable|'
    r'for .+ users|for .+ operations|for .+ tools|otherwise|however|alternatively|instead)\b', re.I)
GENERAL_HEADING = re.compile(r'(?:general )?(?:policy|rules|interaction rules|provenance rules|provenance requirements)', re.I)


def _context_gaps(text, line_index):
    """Conservative surrounding-scope check, never an NL applicability proof.

    All preceding headings are retained (including nested headings), and the
    containing paragraph is checked for guards. Unsupported context is exposed.
    """
    lines = text.splitlines()
    headings = [line.strip() for line in lines[:line_index] if line.strip().endswith(':') or line.lstrip().startswith('#')]
    lo = line_index
    while lo > 0 and lines[lo - 1].strip():
        lo -= 1
    hi = line_index + 1
    while hi < len(lines) and lines[hi].strip():
        hi += 1
    if any(h.endswith(':') and not GENERAL_HEADING.fullmatch(h.rstrip(':').lstrip('# ').strip()) for h in headings):
        return ['unsupported inherited heading scope']
    surrounding = headings + lines[lo:line_index] + lines[line_index + 1:hi]
    references = [line for line in lines if re.search(r'\b(?:this|the) (?:requirement|rule|restriction)\b', line, re.I)]
    if references:
        return ['unparsed cross-reference to requirement/rule/restriction']
    if any(CONTEXT_GUARD.search(x) for x in surrounding):
        return ['unsupported surrounding condition/exception']
    # The compiler owns only a complete bounded block, not an arbitrary clause
    # detached from unparsed modifiers. This avoids an endless exception-word
    # denylist ("exempt", "waived", "superseded", ... all remain unparsed).
    clauses = re.split(r'(?<=[.!])\s+|\n', '\n'.join(lines[lo:hi]))
    for clause in clauses:
        clean = clause.strip()
        if not clean or GENERAL_HEADING.fullmatch(clean.rstrip(':').lstrip('# ').strip()):
            continue
        if _compile_contract(clean) is None:
            return ['unparsed policy-block clause; applicability unresolved']
    return []


def _compile_contract(q):
    """Bounded English grammar. Anything else remains a search hypothesis.

    The *entire* clause must parse: an embedded or negated requirement, scoped
    refund clause or an OR-source clause cannot acquire unconditional authority.
    Explicit tool scopes are exact declaration identifiers, never verb guesses.
    """
    q = re.sub(r'^\s*(?:[-*]\s+|\d+\.\s+)', '', q).strip()
    m = USER_REQUIREMENT.fullmatch(q)
    if m:
        subject = re.sub(r'^(?:the |a |an )', '', m['subject'], flags=re.I).strip()
        tool = None
        scope = re.fullmatch(r'(.+?)\s+(?:of|given to|passed to)\s+([\w.\-]+)', subject, re.I)
        if scope:
            subject, tool = scope.groups()
        # A small adjective is allowed only as presentation of a field, never
        # arbitrary descriptive prose that could conceal conditions or roles.
        subject = re.sub(r'^new\s+', '', subject, flags=re.I)
        parts = re.split(r'\s*,\s*|\s+and\s+', subject)
        if all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?: [A-Za-z_][A-Za-z0-9_]*)*', x) for x in parts):
            # Embedded logical prose is explicitly outside this grammar.
            if any(re.search(r'\b(not|true|that|if|for|unless|except|or|when)\b', x, re.I) for x in parts):
                return None
            return dict(grammar='user-origin-v1', fields=[x.lower() for x in parts], tool=tool,
                        generic=False, user_only=True, input_bound=bool(m['window']), source_only=False,
                        exact_source_required=True)
    m = SOURCE_ONLY.fullmatch(q)
    if m:
        return dict(grammar='source-only-v1', fields=[], tool=None, generic=True, user_only=False,
                    input_bound=bool(m['window']), source_only=True, object_kind=m['object'].lower(),
                    exact_source_required=bool(m['verbatim']))
    m = NO_INVENT.fullmatch(q)
    if m and GENERIC_OBJECT.fullmatch(m['object']):
        return dict(grammar='no-invent-v1', fields=[], tool=None, generic=True, user_only=False,
                    input_bound=bool(re.search(r'\bin this (input|conversation)\b', m['object'], re.I)),
                    source_only=False, exact_source_required=False)
    return None


def _unparsed_context_sources(sources):
    """Code authority is bounded to documents wholly covered by this grammar.

    An unparsed sibling paragraph/document may qualify a rule without using an
    expected exception word. It must be resolved semantically, never ignored.
    """
    unchecked = []
    for source in sources:
        for clause in re.split(r'(?<=[.!])\s+|\n', source['text']):
            clean = clause.strip()
            if not clean or GENERAL_HEADING.fullmatch(clean.rstrip(':').lstrip('# ').strip()):
                continue
            if _compile_contract(clean) is None:
                unchecked.append(source['source_id'])
                break
    return unchecked


def contracts(p):
    """Every explicit provenance-contract sentence of the current input, quoted, with its scope: the fields it names, or
    GENERIC when it speaks of ids/values/arguments in general."""
    out = []
    unchecked_sources = _unparsed_context_sources(p['normative_sources'])
    for s in p['normative_sources'] + p['declarations']:
        for m in CONTRACT.finditer(s['text']):
            q = m.group(0).strip()
            parsed = _compile_contract(q)
            line = s['text'][:m.start()].count('\n')
            gaps = _context_gaps(s['text'], line)
            if unchecked_sources:
                gaps.append('unparsed normative context; semantic applicability unresolved')
            out.append(dict(basis='BOUNDED_CONTRACT' if parsed else 'LEXICAL_CANDIDATE',
                            source_id=s['source_id'], quote=q,
                            user_only=parsed['user_only'] if parsed else bool(FROM_USER.search(q)),
                            binding=parsed, binding_status='SUPPORTED_GRAMMAR' if parsed and not gaps else 'UNRESOLVED',
                            unparsed_context_source_ids=unchecked_sources,
                            gaps=gaps if parsed else ['unsupported contract grammar'] + gaps))
    return out


def applies(con, field, tool=None):
    """-> 'NAMED' if the contract sentence names this field, 'GENERIC' if it is about ids/values/information in general,
    else None. A sentence whose grammatical subject is a specific other thing ("The recipient must come from the user")
    covers only what it names."""
    binding = con.get('binding')
    if binding and con.get('binding_status') == 'SUPPORTED_GRAMMAR':
        if binding['tool'] is not None and binding['tool'] != tool:
            return None
        if binding['generic']:
            return 'GENERIC'
        return 'NAMED' if _names(field).intersection(binding['fields']) else None
    # Retrieval can preserve an unresolved candidate; it cannot promote it.
    return 'UNRESOLVED' if any(_token_in(n, con['quote'].lower()) for n in _names(field)) or GENERIC.search(con['quote']) else None


def contract(p):
    c = contracts(p)
    return c[0] if c else None


def check(p):
    cat, out, records = catalog(p), [], []
    cons = contracts(p)
    for t in p['current_targets']:
        if t['kind'] != 'call' or t.get('role') != 'assistant':
            continue
        tool, args = parse_call(t)
        if not isinstance(args, dict):
            continue
        fields = (cat.get(tool) or {}).get('fields') or {}
        for name, v in args.items():
            vals = [v] if isinstance(v, str) else [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
            fk = field_kind(fields.get(name), name)
            scoped = [(c, applies(c, name, tool)) for c in cons]
            scoped = [(c, a) for c, a in scoped if a]
            for val in vals:
                pr = provenance(p, val, name)
                rec = dict(target_id=t['source_id'], tool=tool, field=name, value=val, field_kind=fk, **pr)
                records.append(rec)
                from_user = any(f['kind'] == 'user' for f in pr['found'])
                # (a) user-only contract that NAMES this field: any field kind, value must occur in a user message
                user_named = [c for c, a in scoped if a == 'NAMED' and c['user_only']]
                # (b) reference field: NOT_FOUND, or a generic/named user-only contract and not from the user
                user_ref = [c for c, a in scoped if a in ('NAMED', 'GENERIC') and c['user_only']]
                source_ref = [c for c, a in scoped if a == 'GENERIC' and (c.get('binding') or {}).get('source_only')
                              and (fk == 'REFERENCE' or (c['binding'].get('object_kind') == 'values'))]
                con = None
                if user_named and pr['status'] != 'UNKNOWN_INCOMPLETE' and not from_user:
                    con = user_named[0]
                elif source_ref and pr['status'] != 'UNKNOWN_INCOMPLETE' and not any(
                        f['kind'] in ('user', 'tool_result') for f in pr['found']):
                    con = source_ref[0]
                elif fk == 'REFERENCE' and pr['status'] == 'NOT_FOUND':
                    con = next((c for c, a in scoped if a in ('NAMED', 'GENERIC')), scoped[0][0] if scoped else False)
                elif pr['status'] == 'NOT_FOUND':
                    con = next((c for c, a in scoped if a == 'GENERIC' and (c.get('binding') or {}).get('source_only')
                                and (c.get('binding') or {}).get('object_kind') == 'values'), None)
                elif fk == 'REFERENCE' and user_ref and pr['status'].startswith('FOUND') and not from_user:
                    con = user_ref[0]
                elif pr['status'] != 'UNKNOWN_INCOMPLETE' and not from_user:
                    con = next((c for c, a in scoped if a == 'UNRESOLVED' and c['user_only']
                                and any(_token_in(n, c['quote'].lower()) for n in _names(name))), None)
                if con is None:
                    continue
                intrinsic_bound = bool(con and (con.get('binding') or {}).get('input_bound'))
                closed = coverage(p).get('provenance_universe_closed') is True or intrinsic_bound
                policy_gaps = [gap for gap in coverage(p).get('unread', []) if gap.get('category') == 'POLICY']
                exact_origin_requirement = bool(con and (con.get('binding') or {}).get('exact_source_required'))
                decisive = bool(con and con.get('binding_status') == 'SUPPORTED_GRAMMAR' and exact_origin_requirement
                                and closed and not policy_gaps)
                if con:
                    con = dict(con, closure_status='BOUNDED_BY_NORM' if intrinsic_bound else
                               'CLOSED_BY_CALLER' if closed else 'UNRESOLVED')
                    if policy_gaps:
                        con['applicability_status'] = 'UNRESOLVED_POLICY_COVERAGE'
                    if not exact_origin_requirement:
                        con['provenance_implication'] = 'UNRESOLVED_DERIVATION_VS_INVENTION'
                out.append(dict(layer='P', kind='UNSOURCED_REFERENCE' if fk == 'REFERENCE' else 'NOT_FROM_USER',
                                target_id=t['source_id'], status='MECHANICAL' if decisive else 'HYPOTHESIS',
                                fact=dict(tool=tool, field=name, value=val, provenance=pr['status'],
                                          found_kinds=sorted({f['kind'] for f in pr['found']}), field_kind=fk),
                                norm=con or dict(basis='NONE', text='no provenance contract of this input covers this field'),
                                reason=f'{t["source_id"]} calls {tool} with {name}={json.dumps(val)}: ' +
                                       ('the value appears in no user message, tool result or '
                                        'policy of this completely read input; this observation alone does not establish invention.'
                                        if pr['status'] == 'NOT_FOUND' else
                                        'the value occurs only outside the sources permitted by the source-only contract.'
                                        if con and (con.get('binding') or {}).get('source_only') else
                                        'the value does not occur in any user message, but the contract requires it from the user.')))
    return out, records


def recheck(p, f):
    again = [x for x in check(p)[0] if x['kind'] == f['kind'] and x['target_id'] == f['target_id']
             and x['fact'] == f['fact'] and x['status'] == f['status'] and x['norm'] == f['norm']]
    return bool(again)
