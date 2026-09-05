"""Conservative structural provenance; no semantic aliases or world-state claims.

Edges describe observed equality, scope and chronological succession. They do not
prove authorization, ownership, freshness or that an argument must copy a value.
"""

import json
from collections import defaultdict

from .types import ArgumentTrace, EntityKey, Event, EvidenceGraph, FactNode


def value_key(value):
    # Keep bool, int, float and string distinct; never normalize opaque IDs.
    return (type(value).__name__, json.dumps(value, ensure_ascii=False, sort_keys=True))


def identities(value):
    if not isinstance(value, dict):
        return {}
    keys = {key: item for key, item in value.items()
            if (key.endswith('_id') or key.endswith('_number'))
            and type(item) in (str, int) and item != ''}
    # Keep explicit temporal selectors from the request too: search results may
    # omit the date even though the same flight number repeats on different days.
    for key in ('date', 'start_date', 'end_date', 'as_of'):
        if isinstance(value.get(key), str):
            keys[key] = value[key]
    return keys


def has_entity(scope):
    return any(key.endswith('_id') or key.endswith('_number') for key in scope)


def scoped_leaves(value, inherited=None, path=(), stable=True):
    scope = dict(inherited or {})
    if isinstance(value, dict):
        scope.update(identities(value))
        for key, item in value.items():
            yield from scoped_leaves(item, scope, (*path, key), stable)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            # An array index is not an entity ID. Anonymous siblings cannot form
            # one timeline, even when a parent has an ID.
            anchored = has_entity(identities(item))
            yield from scoped_leaves(item, scope, (*path, index), stable and anchored)
    else:
        field_name = next((key for key in reversed(path) if isinstance(key, str)), '$')
        yield list(path), field_name, value, scope, stable and has_entity(scope)


def entity_list(scope):
    return [EntityKey(key, value) for key, value in sorted(scope.items())]


def scope_key(entities):
    return tuple((e.field, value_key(e.value)) for e in entities)


def lineage(fact):
    if not fact.versioned:
        return None
    container = tuple(key for key in fact.path[:-1] if isinstance(key, str))
    return fact.role, fact.tool, container, fact.field, scope_key(fact.entities)


def scope_relation(argument_scope, fact):
    known = {e.field: e.value for e in fact.entities}
    shared = argument_scope.keys() & known.keys()
    if any(value_key(argument_scope[k]) != value_key(known[k]) for k in shared):
        return 'conflict'
    return 'overlap' if has_entity(shared) else 'unscoped'


def build_graph(history: list[Event], candidate: list[Event], max_links: int = 32) -> EvidenceGraph:
    if max_links < 1:
        raise ValueError('max_links must be positive')
    graph = EvidenceGraph()
    pending = defaultdict(list)
    latest = {}
    for index, event in enumerate(history):
        pair_key = (event.role, event.name)
        if event.kind == 'call':
            pending[pair_key].append(event)
            continue
        if event.kind != 'result':
            continue
        calls = pending.pop(pair_key, [])
        scope, sources = {}, [event.source]
        if len(calls) > 1:
            graph.issues.append('ambiguous_call_result_pair')
        elif len(calls) == 1 and calls[0].json_valid:
            request_scope = identities(calls[0].value)
            result_scope = identities(event.value)
            conflict = any(value_key(v) != value_key(result_scope[k])
                           for k, v in request_scope.items() if k in result_scope)
            if conflict:
                graph.issues.append('request_result_identity_conflict')
            else:
                scope = request_scope
                if scope:
                    sources.append(calls[0].source)
        if not event.json_valid:
            graph.issues.append('unparsed_result_not_indexed')
            continue
        snapshot = defaultdict(list)
        for path, name, value, entities, stable in scoped_leaves(event.value, scope):
            fact = FactNode(f'f{len(graph.facts)}', index, event.name or '', event.role,
                            path, name, value, entity_list(entities), list(sources), stable)
            key = lineage(fact)
            if key is not None:
                fact.previous = list(latest.get(key, []))
                snapshot[key].append(fact.id)
            graph.facts.append(fact)
        # Duplicate identities inside one result are simultaneous alternatives,
        # not updates to each other.
        latest.update(snapshot)

    by_field = defaultdict(list)
    by_id = {fact.id: fact for fact in graph.facts}
    for fact in graph.facts:
        by_field[fact.field].append(fact)
    for index, event in enumerate(candidate):
        if event.role != 'assistant' or event.kind != 'call' or not event.json_valid:
            continue
        if not isinstance(event.value, dict):
            continue
        for path, name, value, entities, _ in scoped_leaves(event.value):
            support, alternatives, unscoped, conflicts = [], [], [], []
            for fact in by_field[name]:
                relation = scope_relation(entities, fact)
                equal = value_key(value) == value_key(fact.value)
                if relation == 'overlap':
                    (support if equal else alternatives).append(fact.id)
                elif equal:
                    (conflicts if relation == 'conflict' else unscoped).append(fact.id)
            if support:
                recent_equal, recent_different, uncertain = False, False, False
                for fact_id in support:
                    key = lineage(by_id[fact_id])
                    if key is None:
                        uncertain = True
                        continue
                    for recent_id in latest[key]:
                        if value_key(by_id[recent_id].value) == value_key(value):
                            recent_equal = True
                        else:
                            recent_different = True
                            alternatives.append(recent_id)
                if recent_equal and recent_different:
                    status = 'ambiguous_history'
                elif recent_different and not uncertain:
                    status = 'older_observation_match'
                else:
                    status = 'observed_match'
            elif unscoped:
                status = 'unscoped_match'
                support = unscoped
            elif conflicts:
                status = 'scope_conflict'
            elif alternatives:
                status = 'different_observed_value'
            else:
                status = 'not_observed'
            alternatives = list(dict.fromkeys(alternatives + conflicts))
            # Keep recent observations first when limiting the exported links.
            support.sort(key=lambda key: by_id[key].event, reverse=True)
            alternatives.sort(key=lambda key: by_id[key].event, reverse=True)
            graph.arguments.append(ArgumentTrace(
                index, path, value, entity_list(entities), event.source, status,
                support[:max_links], alternatives[:max_links],
                len(support) > max_links or len(alternatives) > max_links))
    graph.issues = sorted(set(graph.issues))
    return graph
