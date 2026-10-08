"""Whole-event exact-value retrieval from originals; never semantic certificates.

This retrieval uses actual current values and is therefore a separate experimental
arm from fixed-source blind binding. Completeness means only that all native
result payloads were scanned for exact typed scalar matches, not that relevant
sources, entity bindings, successful receipts or latest state were established.
"""
from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal, DecimalException

from guardian_truth.parsing import STATUS_PREFIX, parse_events

from .blind import _constant, _no_duplicates, _type, source_index

VERSION = 'native-exact-source-completion-v1'


def _payload(event):
    # Event.text is the native payload body, unlike SourceStore.text (which also
    # includes the original marker). Keep the original framing in retrieved text.
    body = event.text
    if event.kind == 'result' and STATUS_PREFIX.match(body):
        body = body[STATUS_PREFIX.match(body).end():]
    return json.loads(body, object_pairs_hook=_no_duplicates, parse_int=Decimal,
                      parse_float=Decimal, parse_constant=_constant)


def _leaves(value, pointer='', field=None):
    """The nearest enclosing object key is a syntactic field, never a role."""
    if isinstance(value, dict):
        for key, child in value.items():
            path = pointer + '/' + key.replace('~', '~0').replace('/', '~1')
            yield from _leaves(child, path, key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, pointer + '/' + str(index), field)
    else:
        yield pointer, field, value


def _key(value):
    # JSON numbers are exact Decimal, bool never aliases 1, string never a number.
    return _type(value), value


def _native(row, event, ordinal, prefix):
    span = event.source
    text = row[span.document][span.start:span.end]
    return dict(source_id=f'{prefix}{ordinal}', role=event.role, kind=event.kind,
                tool=event.name, event=ordinal, text=text, document=span.document,
                start=span.start, end=span.end, offset_unit='PYTHON_CHARACTER',
                sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                receipt_status=event.status, parser_diagnostics=list(event.diagnostics))


def _lineage(events, ordinal):
    # Explicitly bounded syntactic candidates, not request-id/authenticated pairs.
    start = ordinal
    while start and events[start - 1].kind in ('call', 'result'):
        start -= 1
    result = events[ordinal]
    candidates = [f'h{i}' for i in range(start, ordinal)
                  if events[i].kind == 'call' and events[i].name == result.name
                  and events[i].role == result.role]
    return dict(candidate_call_ids=candidates,
                status='AMBIGUOUS' if len(candidates) > 1 else
                       'POSSIBLE_ONLY' if candidates else 'UNRESOLVED',
                pairing_authenticated=False, scope='PRECEDING_CONTIGUOUS_TOOL_BLOCK_ROLE_AND_NAME')


def complete(row, packet, budget_bytes=12000):
    """Return (deep-copied augmented packet, RETRIEVAL_ONLY receipt).

    Budget charges the UTF-8 bytes of each whole original event added/replaced,
    including markers and whitespace. Existing exact full events cost zero.
    Metadata has separate measured bytes and is not charged to this text budget.
    Results take priority over their possible call lineage. No source is truncated;
    budget-skipped sources and every parse/framing gap remain visible.
    """
    if type(budget_bytes) is not int or budget_bytes < 0:
        raise ValueError('budget_bytes must be a nonnegative integer')
    if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in ('prompt', 'response')):
        raise ValueError('row prompt and response must be strings')
    old_index = source_index(packet)  # reject namespace collisions, do not choose one
    augmented = copy.deepcopy(packet)
    history = parse_events(row['prompt'], 'prompt')
    targets = parse_events(row['response'], 'response')
    native = {f'h{i}': _native(row, event, i, 'h') for i, event in enumerate(history)}
    receipt = dict(version=VERSION, authority='RETRIEVAL_ONLY', sources_added=[], sources_expanded=[],
                   sources_already_full=[], matches=[], lineage=[], gaps=[], unchecked_source_ids=[],
                   budget=dict(limit_bytes=budget_bytes, used_bytes=0, unit='UTF8_ORIGINAL_EVENT_TEXT',
                               metadata_bytes=0), entity_binding='UNRESOLVED',
                   semantic_relevance_complete=False, latest_state_established=False,
                   closure_established=False)
    receipt['input_fingerprints'] = {document: hashlib.sha256(row[document].encode('utf-8')).hexdigest()
                                     for document in ('prompt', 'response')}
    receipt['query_target_ids'] = []
    receipt['scanned_result_ids'] = []
    queries = {}
    for ordinal, event in enumerate(targets):
        if event.kind != 'call' or event.role != 'assistant':
            continue
        if event.diagnostics:
            receipt['gaps'].append(dict(source_id=f't{ordinal}', gap='CURRENT_FRAMING_DIAGNOSTICS',
                                        diagnostics=list(event.diagnostics)))
        try:
            value = _payload(event)
            if not isinstance(value, dict):
                raise ValueError('CURRENT_ARGUMENTS_NOT_OBJECT')
        except (ValueError, TypeError, RecursionError, DecimalException) as exc:
            receipt['gaps'].append(dict(source_id=f't{ordinal}', gap='CURRENT_ARGUMENTS_UNPARSED',
                                        detail=str(exc)))
            continue
        receipt['query_target_ids'].append(f't{ordinal}')
        for path, field, scalar in _leaves(value):
            queries.setdefault(_key(scalar), []).append(dict(target_id=f't{ordinal}', argument_path=path,
                                                              terminal_field=field))

    priorities = {}
    for ordinal, event in enumerate(history):
        if event.kind != 'result':
            continue
        sid = f'h{ordinal}'
        if event.diagnostics:
            receipt['gaps'].append(dict(source_id=sid, gap='RESULT_FRAMING_DIAGNOSTICS',
                                        diagnostics=list(event.diagnostics)))
        try:
            value = _payload(event)
        except (ValueError, TypeError, RecursionError, DecimalException) as exc:
            receipt['gaps'].append(dict(source_id=sid, gap='RESULT_PAYLOAD_UNPARSED', detail=str(exc)))
            continue
        receipt['scanned_result_ids'].append(sid)
        for path, field, scalar in _leaves(value):
            for query in queries.get(_key(scalar), []):
                same_field = field is not None and field == query['terminal_field']
                kind = 'FIELD_AND_VALUE' if same_field else 'VALUE_ONLY'
                receipt['matches'].append(dict(**query, source_id=sid, source_pointer=path,
                                               source_terminal_field=field, value_type=_type(scalar),
                                               match_kind=kind, selected=False,
                                               entity_binding='UNRESOLVED'))
                priorities[sid] = min(priorities.get(sid, 1), 0 if same_field else 1)

    # Reading failures don't convert negative retrieval evidence into an absence proof.
    receipt['exact_typed_match_scan_complete'] = not receipt['gaps']
    selected = {}

    def select(sid):
        if sid in selected:
            return True
        full = native[sid]
        existing = old_index.get(sid)
        if existing and existing['text'] == full['text'] and all(existing.get(k) == full[k]
                                                                for k in ('role', 'kind', 'tool')):
            receipt['sources_already_full'].append(sid)
        else:
            size = len(full['text'].encode('utf-8'))
            if receipt['budget']['used_bytes'] + size > budget_bytes:
                if sid not in receipt['unchecked_source_ids']:
                    receipt['unchecked_source_ids'].append(sid)
                    receipt['gaps'].append(dict(source_id=sid, gap='WHOLE_EVENT_OVER_BUDGET', bytes=size))
                return False
            receipt['budget']['used_bytes'] += size
            receipt['sources_expanded' if existing else 'sources_added'].append(sid)
        selected[sid] = full
        return True

    for sid in sorted(priorities, key=lambda s: (priorities[s], native[s]['event'])):
        if select(sid):
            lineage = dict(source_id=sid, **_lineage(history, native[sid]['event']))
            receipt['lineage'].append(lineage)
    # Matching results are not discarded just because their possible call doesn't fit.
    for lineage in receipt['lineage']:
        lineage['call_sources_selected'] = [sid for sid in lineage['candidate_call_ids'] if select(sid)]
        lineage['call_sources_unchecked'] = [sid for sid in lineage['candidate_call_ids'] if sid not in selected]
    for match in receipt['matches']:
        match['selected'] = match['source_id'] in selected

    # Replace partial sources in their original category; add missing native history.
    for category in ('normative_sources', 'declarations', 'history', 'current_targets'):
        if category in augmented:
            augmented[category] = [copy.deepcopy(selected.get(source['source_id'], source))
                                   for source in augmented[category]]
    augmented.setdefault('history', []).extend(copy.deepcopy(source) for sid, source in selected.items()
                                              if sid not in old_index)
    # Stable native timeline; packet sources not mappable to native events remain visible.
    def order(source):
        sid = source['source_id']
        if sid in native:
            return native[sid]['event'], 0
        event = source.get('event')
        return (event, 1) if type(event) is int else (len(history), 1)
    augmented['history'].sort(key=order)
    source_index(augmented)
    receipt['matched_sources_read_complete'] = all(m['selected'] for m in receipt['matches'])
    receipt['retrieval_complete'] = receipt['exact_typed_match_scan_complete'] and not receipt['unchecked_source_ids']
    receipt['budget']['metadata_bytes'] = sum(len(json.dumps({k: v for k, v in source.items() if k != 'text'},
                                                           ensure_ascii=False).encode('utf-8'))
                                             for source in selected.values())
    receipt['source_fingerprints'] = {sid: source['sha256'] for sid, source in selected.items()}
    return augmented, receipt
