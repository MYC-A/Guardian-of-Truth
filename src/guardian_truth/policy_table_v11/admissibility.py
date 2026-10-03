"""Bounded admissibility verdict, enforcement modes and machine-readable audit trace.

Soundness trap: requiring a closed proof that every precondition *holds* leaves
real (open) dialogues in UNKNOWN. This layer instead checks *admissibility*:
a step is ADMISSIBLE when no bounded invariant is violated (schema, provenance
of identifiers, decisive policy atoms, dates). Unresolved atoms are reported as
residual risk rather than blocking the verdict. UNKNOWN is reserved for steps
the deterministic layer cannot inspect (unparseable call, missing catalog,
unverified prose channel), and enforcement modes map it to ALLOW/REJECT/REVIEW.
"""
from dataclasses import dataclass
import hashlib
import json
import re
import time
from guardian_truth.parsing import parse_catalog
from guardian_truth.policy_table.segment import policy_hash
from .router import route_step, PROSE, EMPTY
from .witness import contains_value
from .invariants import call_invariants
from .policy_clauses import turn_shape_violations

ADMISSIBLE, VIOLATION, UNKNOWN = 'ADMISSIBLE', 'VIOLATION', 'UNKNOWN'
ALLOW, REJECT, REVIEW = 'ALLOW', 'REJECT', 'REVIEW'
STRICT, BALANCED, PERMISSIVE = 'STRICT', 'BALANCED', 'PERMISSIVE'
VERSION = 'guardian-admissibility/1'
_WRITE_VERB = re.compile(r'^(?:cancel|delete|remove|refund|transfer|pay|charge|book|update|modify|change|'
                         r'send|issue|approve|close|create|apply|unlock|log|submit|exchange|return)', re.I)


@dataclass(frozen=True)
class EnforcementPolicy:
    """Maps a verdict to a gate decision. ``tool_risk`` overrides the default
    heuristic (write verbs are HIGH risk, reads LOW)."""
    mode: str = BALANCED
    tool_risk: dict | None = None

    def risk(self, tool):
        if self.tool_risk and tool in self.tool_risk: return self.tool_risk[tool]
        return 'HIGH' if tool and _WRITE_VERB.match(tool) else 'LOW'

    def decide(self, verdict, tools, provenance_ok):
        if verdict == VIOLATION: return REJECT
        if verdict == ADMISSIBLE: return ALLOW
        high = any(self.risk(t) == 'HIGH' for t in tools)
        if self.mode == STRICT or high and self.mode == BALANCED: return REJECT if high or self.mode == STRICT else REVIEW
        if self.mode == PERMISSIVE and provenance_ok: return ALLOW  # logged to audit for later labelling
        return REVIEW


def _leaves(value, path=''):
    if isinstance(value, dict):
        for k, v in value.items(): yield from _leaves(v, f'{path}.{k}' if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value): yield from _leaves(v, f'{path}[{i}]')
    else: yield path, value


def _identifier(key, value):
    leaf = key.rsplit('.', 1)[-1].split('[')[0]
    return isinstance(value, str) and (leaf == 'id' or leaf.endswith('_id')) and len(value) >= 3


def schema_violations(spec, arguments):
    """Declared-schema invariants: unknown/missing required fields, enum, scalar type."""
    out = []
    def walk(fields, value, prefix):
        if not isinstance(value, dict):
            out.append({'code': 'ARGUMENT_NOT_OBJECT', 'argument': prefix or '$'}); return
        by_name = {f.name: f for f in fields}
        for name in value:
            if name not in by_name: out.append({'code': 'UNDECLARED_ARGUMENT', 'argument': prefix + name})
        for f in fields:
            if f.name not in value:
                if f.required: out.append({'code': 'MISSING_REQUIRED_ARGUMENT', 'argument': prefix + f.name})
                continue
            v = value[f.name]
            if f.enum and isinstance(v, str) and v not in f.enum:
                out.append({'code': 'ENUM_VIOLATION', 'argument': prefix + f.name, 'value': v, 'allowed': f.enum})
            kind = (f.kind or '').lower()
            bad = (kind == 'integer' and (isinstance(v, bool) or not isinstance(v, int)) or
                   kind == 'number' and (isinstance(v, bool) or not isinstance(v, (int, float))) or
                   kind == 'string' and not isinstance(v, str) or kind == 'boolean' and not isinstance(v, bool) or
                   kind == 'array' and not isinstance(v, list))
            if bad and v is not None: out.append({'code': 'TYPE_VIOLATION', 'argument': prefix + f.name, 'expected': kind, 'value': v})
            if f.children and isinstance(v, list):
                for i, item in enumerate(v): walk(f.children, item, f'{prefix}{f.name}[{i}].')
            elif f.children and isinstance(v, dict): walk(f.children, v, prefix + f.name + '.')
    walk(spec.fields, arguments, '')
    return out


_CONTACT = re.compile(r'(?:^|_)(?:zip|zipcode|zip_code|postal_code|postcode|email|e_mail|phone|phone_number)$', re.I)
_INLINE_RESULT = re.compile(r'←\s*TOOL_RESPONSE')


def _contact(key, value):
    leaf = key.rsplit('.', 1)[-1].split('[')[0]
    return isinstance(value, str) and len(value.strip()) >= 3 and bool(_CONTACT.search(leaf))


def _contact_grounded(corpus, value):
    value = value.strip()
    if '@' in value: return contains_value(corpus.lower(), value.lower())
    digits = re.sub(r'\D', '', value)
    if len(digits) >= 7 and len(digits) >= len(value.replace(' ', '')) - 4:  # phone-like: formatting may differ
        return any(re.sub(r'\D', '', m) .endswith(digits) or digits.endswith(re.sub(r'\D', '', m))
                   for m in re.findall(r'\+?\d[\d\s().-]{5,}\d', corpus) if len(re.sub(r'\D', '', m)) >= 7)
    return contains_value(corpus, value) or contains_value(corpus.lower(), value.lower())


def provenance_violations(store, call_index, arguments):
    """Identifier provenance: every ID-like argument must occur in prior context
    (user/system text or earlier tool results). Assistant prose alone is not a source.
    Contact fields (zip, email, phone) must occur as a standalone token: a zip carved
    out of an e-mail address or another identifier is a fabricated value."""
    prior = [e.text for e in store.history_events if e.role in ('user', 'system') or e.kind == 'result']
    prior += [e.text[m.start():] for e in store.history_events if e.kind == 'call'
              for m in [_INLINE_RESULT.search(e.text or '')] if m]
    prior += [e.text for e in store.target_events[:call_index] if e.kind == 'result']
    corpus = '\n'.join(prior)
    out = [{'code': 'UNGROUNDED_IDENTIFIER', 'argument': k, 'value': v}
           for k, v in _leaves(arguments) if _identifier(k, v) and not contains_value(corpus, v)]
    out += [{'code': 'UNGROUNDED_CONTACT_VALUE', 'argument': k, 'value': v}
            for k, v in _leaves(arguments) if _contact(k, v) and not _contact_grounded(corpus, v)]
    return out


def assess(store, *, table=None, enforcement=EnforcementPolicy(), audit_graph=True):
    """Return a verdict, gate decision and audit trace for the step in ``store``."""
    started = time.perf_counter()
    route = route_step(store)
    catalog = parse_catalog(store.history_events, store.raw['prompt'])
    violations, unresolved, inspected, tools, notes = [], [], [], [], []
    for sid in route.malformed_call_source_ids:
        violations.append({'code': 'MALFORMED_TOOL_CALL', 'source_id': sid})
    for sid in route.call_source_ids:
        index = int(sid[1:]); event = store.target_events[index]; tools.append(event.name)
        spec = catalog.tools.get(event.name)
        if spec is None:
            if catalog.tools: violations.append({'code': 'UNDECLARED_TOOL', 'tool': event.name, 'source_id': sid})
            else: unresolved.append({'code': 'CATALOG_UNAVAILABLE', 'source_id': sid})
            continue
        for v in schema_violations(spec, event.value) if spec.schema_understood else []:
            violations.append({**v, 'tool': event.name, 'source_id': sid,
                               'schema_span': [spec.source.start, spec.source.end]})
        for v in provenance_violations(store, index, event.value):
            violations.append({**v, 'tool': event.name, 'source_id': sid})
        for v in call_invariants(store.history_events, event.name, event.value):
            violations.append({**v, 'tool': event.name, 'source_id': sid})
        inspected.append(sid)
    for v in turn_shape_violations(store, route):
        violations.append(v)
    policy = None
    if table is not None and route.call_source_ids:
        from .evaluate import evaluate_table
        from .schema import Atom
        try:
            policy = evaluate_table(store, table)
            clauses = {c['id']: c['text'] for c in table['policy']['clauses']}
            for f in policy['findings']:
                record = {'code': 'POLICY_ATOM_VIOLATION', 'atom_id': f['atom_id'], 'clause_ids': f['clause_ids'],
                          'clause_quotes': {c: clauses.get(c) for c in f['clause_ids']},
                          'source_id': f['target_source_id'], 'evidence': f['evaluated']}
                (violations if f['status'] == 'DECISIVE' else notes).append(record)
            for t in policy['trace']:
                if t['value'] == 'UNRESOLVED' and not t['suppressed']:
                    unresolved.append({'code': 'ATOM_UNRESOLVED', 'atom_id': t['atom_id'], 'clause_ids': t['clause_ids'],
                                       'source_id': t['target_source_id']})
        except ValueError as exc:  # Wrong policy hash or tampered table: never silently trusted.
            unresolved.append({'code': 'POLICY_TABLE_REJECTED', 'reason': str(exc)})
    provenance_ok = not any(v['code'] == 'UNGROUNDED_IDENTIFIER' for v in violations)
    if violations: verdict = VIOLATION
    elif route.kind in (PROSE, EMPTY) or not inspected or any(u['code'] in ('CATALOG_UNAVAILABLE', 'POLICY_TABLE_REJECTED') for u in unresolved):
        verdict = UNKNOWN
    else: verdict = ADMISSIBLE  # bounded admissibility: residual unresolved atoms are reported, not blocking
    if route.prose_source_ids and verdict == ADMISSIBLE:
        notes.append({'code': 'PROSE_CHANNEL_UNVERIFIED', 'source_ids': list(route.prose_source_ids)})
    decision = enforcement.decide(verdict, tools, provenance_ok)
    elapsed_ms = (time.perf_counter() - started) * 1000
    trace = {'schema_version': VERSION, 'policy_sha256': policy_hash(store), 'source_sha256': store.source_sha256,
             'route': route.kind, 'channels': list(route.channels), 'verdict': verdict, 'decision': decision,
             'enforcement_mode': enforcement.mode, 'risk': {t: enforcement.risk(t) for t in tools},
             'violations': violations, 'unresolved': unresolved, 'notes': notes, 'inspected_calls': inspected,
             'latency_ms': round(elapsed_ms, 3)}
    if audit_graph:
        trace['graph_snapshot'] = [{'source_id': ('h' + str(i)), 'role': e.role, 'kind': e.kind, 'tool': e.name,
                                    'sha256': hashlib.sha256(e.text.encode()).hexdigest()[:16]}
                                   for i, e in enumerate(store.history_events)]
    trace['trace_id'] = hashlib.sha256(json.dumps({k: trace[k] for k in ('source_sha256', 'verdict', 'violations')},
                                                  sort_keys=True, default=str).encode()).hexdigest()[:20]
    return trace


def audit_jsonl(trace):
    return json.dumps(trace, ensure_ascii=False, sort_keys=True, default=str)
