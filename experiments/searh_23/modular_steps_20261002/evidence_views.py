"""Read-only source graph; chronology edges never certify latest-state truth."""
from collections import defaultdict
from dataclasses import asdict
import json
from modular_common import sha
from guardian_truth.parsing import parse_events
from guardian_truth.provenance import build_graph


# Chars that extend a token: an occurrence touching one of these on either
# side is a substring of a longer token, never an exact identifier match
# (E-7 inside E-70, 7 inside 70, 2026-10-02 inside 2026-10-023).
_TOKEN_CHARS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-')


def _occurrence_spans(text, value):
    """Exact standalone-token occurrences of a typed value in text.

    Case-sensitive; opaque IDs are never normalized. Substring hits inside
    longer tokens and decimal continuations (42 inside 42.5) are rejected.
    Returns [(start, end), ...].
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return []
    needle = str(value)
    if not needle:
        return []
    spans, start = [], text.find(needle)
    while start != -1:
        end = start + len(needle)
        prev_ch = text[start - 1] if start > 0 else ''
        next_ch = text[end] if end < len(text) else ''
        ok = not (prev_ch and prev_ch in _TOKEN_CHARS) and not (next_ch and next_ch in _TOKEN_CHARS)
        if ok and needle.isdigit():
            # Decimal continuations bind neither side: 42 inside 42.5,
            # 5 inside 42.5 (string digits behave like numeric tokens).
            if next_ch == '.' and end + 1 < len(text) and text[end + 1].isdigit():
                ok = False
            if prev_ch == '.' and start >= 2 and text[start - 2].isdigit():
                ok = False
        if ok:
            spans.append((start, end))
        start = text.find(needle, start + 1)
    return spans


def _typed_key(entity):
    """Field + runtime type + value: item_id 42 never conflates with payment_id 42
    nor with the string '42'."""
    return (entity.field, type(entity.value).__name__, entity.value)


def _bind_entities(facts, response_text, user_events):
    """Typed exact-match binding of fact entities against the focus text.

    Search regions: the raw target response plus every parsed USER event,
    each mapped to absolute offsets in its original document via the
    parser's Source span. Returns (bindings, rejected_substring,
    ambiguous_values):
    bindings: {typed_key: [{'document','start','end'}, ...]} with spans that
    always satisfy document_text[start:end] == str(value);
    rejected_substring: entities whose value only occurs inside longer tokens;
    ambiguous_values: [{value, type, fields}] — same value bound via several
    different ID fields; selection stays inclusive but coverage flags it.
    """
    regions = [('response', response_text, 0)]
    for event in user_events:
        regions.append(('prompt', event.text, event.source.start))
    entities, seen = {}, set()
    for f in facts:
        for e in f.entities:
            key = _typed_key(e)
            if key not in seen:
                seen.add(key)
                entities[key] = e
    bindings, rejected = {}, []
    for key, e in entities.items():
        spans = []
        for document, text, base in regions:
            spans += [{'document': document, 'start': base + s, 'end': base + t}
                      for s, t in _occurrence_spans(text, e.value)]
        if spans:
            bindings[key] = spans
        else:
            focus_any = any(str(e.value) and str(e.value) in text
                            for _doc, text, _base in regions)
            if focus_any:
                rejected.append({'field': e.field, 'value': e.value})
    by_value = defaultdict(set)
    for field, _typ, value in bindings:
        by_value[(type(value).__name__, value)].add(field)
    ambiguous = [{'value': value, 'type': typ, 'fields': sorted(fields)}
                 for (typ, value), fields in by_value.items() if len(fields) > 1]
    return bindings, rejected, ambiguous


def graph_for(row):
    from structural_v02 import parse_case_v02
    history = parse_events(row['prompt'], 'prompt')
    target = parse_events(row['response'], 'response')
    native = build_graph(history, target, max_links=256)
    ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
    user_events = [e for e in history if e.role == 'user']
    # Typed exact-match binding: (field, type, value) keys with recorded
    # source documents and spans. Substring matches (E-7 inside E-70) and
    # cross-field value conflation are never guessed into the scope.
    bindings, rejected_substring, ambiguous_values = _bind_entities(
        native.facts, row['response'], user_events)
    scope = set(bindings)
    facts = [asdict(f) for f in native.facts if not scope or any(_typed_key(e) in scope for e in f.entities)]
    known = {f['id'] for f in facts}
    edges = [{'from': previous, 'to': f['id'], 'kind': 'PRIOR_OBSERVATION_NOT_SEMANTIC_OVERRIDE',
              'meaning': 'Earlier arrival for the same explicit source scope; version/expiry/error semantics unresolved.'}
             for f in facts for previous in f['previous'] if previous in known]
    for f in facts:
        f['quotes'] = [{'source_id': s['document'], 'start': s['start'], 'end': s['end'],
                        'quote': row[s['document']][s['start']:s['end']]} for s in f.pop('sources')]
        f['epistemic_status'] = 'OBSERVED_PAYLOAD_ONLY_NOT_CURRENT_STATE_OR_EXECUTION'
    return {'module': 'target-linked-source-graph/1', 'facts': facts, 'edges': edges,
            'policy': ctx.policy_text, 'catalog': ctx.system,
            'coverage': {'facts_total': len(native.facts), 'facts_selected': len(facts),
                         'all_policy_text_included': True, 'exception_semantics_verified': False,
                         'target_entity_selection': 'typed (field,type,value) exact-token bindings with recorded spans; substring and cross-field value matches are never guessed',
                         'selection_scope_ambiguous': not bool(scope),
                         'selection_fallback_full_graph': not bool(scope),
                         'typed_bindings': [{'field': field, 'type': typ, 'value': value, 'spans': spans}
                                            for (field, typ, value), spans in sorted(bindings.items(), key=repr)],
                         'rejected_substring_only_matches': sorted(rejected_substring, key=repr),
                         'ambiguous_value_fields': sorted(ambiguous_values, key=repr)},
            'warning': 'Source graph is advisory. Check every policy condition, exception, temporal rule and target claim independently in the full original case.'}


def render(graph, mode):
    """G2 and G2-linear preserve identical fact/citation/edge information."""
    shared = {'facts': graph['facts'], 'edges': graph['edges'], 'policy': graph['policy'],
              'catalog': graph['catalog'], 'coverage': graph['coverage'], 'warning': graph['warning']}
    if mode == 'G2':
        return json.dumps(shared, ensure_ascii=False, sort_keys=True)
    if mode == 'G2-linear':
        lines = ['SOURCE RECORDS — same selected information as graph:']
        for field in ('facts', 'edges'):
            lines += [field + ': ' + json.dumps(item, ensure_ascii=False, sort_keys=True) for item in shared[field]]
        lines += [key + ': ' + json.dumps(shared[key], ensure_ascii=False, sort_keys=True)
                  for key in ('policy', 'catalog', 'coverage', 'warning')]
        return '\n'.join(lines)
    raise ValueError('unknown graph presentation')


def information_hash(graph):
    return sha({k: graph[k] for k in ('facts', 'edges', 'policy', 'catalog', 'coverage', 'warning')})


class GraphAPI:
    """Four bounded queries; never executes tools from the examined trajectory."""
    OPS = ('observations', 'changes', 'grounds', 'requirements', 'available_actions')

    def __init__(self, graph, limit=4):
        self.graph, self.remaining = graph, limit

    def query(self, request):
        if self.remaining <= 0:
            return {'status': 'LIMIT_REACHED'}
        self.remaining -= 1
        if not isinstance(request, dict) or request.get('op') not in self.OPS:
            return {'status': 'INVALID_QUERY'}
        op, entity = request['op'], request.get('entity_id')
        facts = [f for f in self.graph['facts'] if entity is None or any(e['value'] == entity for e in f['entities'])]
        matched_fields = sorted({e['field'] for f in facts for e in f['entities'] if e['value'] == entity}) if entity is not None else []
        ambiguous = entity is not None and len(matched_fields) > 1
        if op in ('observations', 'grounds'):
            result = {'facts': facts, 'current_state_semantics': 'NOT_INFERRED'}
        elif op == 'changes':
            ids = {f['id'] for f in facts}
            result = {'facts': facts, 'edges': [e for e in self.graph['edges'] if e['from'] in ids and e['to'] in ids]}
        elif op == 'requirements':
            result = {'policy': self.graph['policy'], 'coverage': 'FULL_RAW_POLICY_NOT_COMPILED'}
        else:
            result = {'catalog': self.graph['catalog'], 'authorization': 'UNVERIFIED_REQUIRES_POLICY'}
        return {'status': 'OK', 'data': result, 'remaining': self.remaining,
                'matched_entity_fields': matched_fields,
                'ambiguous_entity_value': ambiguous}
