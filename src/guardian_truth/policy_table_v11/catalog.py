"""Schema paths, declaration witnesses and generic collection-key normalization."""
from collections import defaultdict
import json
import re
from guardian_truth.parsing import parse_catalog
from guardian_truth.policy_table.segment import scalar_type, pointer


def tool_role(name, declaration):
    # Descriptive classification, not a proof of effects. Unknown is retained.
    words = re.findall(r'[a-z]+', (name + ' ' + declaration.split('\n')[0]).lower())
    writes = {'update', 'modify', 'change', 'add', 'remove', 'delete', 'create',
              'cancel', 'send', 'submit', 'process', 'transfer', 'exchange', 'book',
              'reserve', 'issue', 'apply', 'set', 'pay', 'write', 'perform', 'execute'}
    reads = {'get', 'read', 'list', 'search', 'find', 'lookup', 'check', 'calculate',
             'retrieve', 'inspect', 'query', 'verify', 'discover'}
    if set(words) & writes: return 'WRITE_OR_EFFECT'
    if set(words) & reads: return 'READ'
    return 'UNKNOWN'


def shape(value):
    if isinstance(value, dict):
        return ('object', tuple(sorted((k, shape(v)) for k, v in value.items()
                                      if not re.search(r'\d{4}', k))))
    if isinstance(value, list): return ('array', tuple(sorted({repr(shape(v)) for v in value})))
    return scalar_type(value)


def intrinsic_key(key, child):
    return bool(re.search(r'\d{4}', key)) or (isinstance(child, dict) and any(
        (field == 'id' or field.endswith('_id')) and str(value) == key
        for field, value in child.items() if isinstance(value, (str, int)) and type(value) is not bool))


def normalize_catalog(stores):
    tools, observed, nodes = {}, [], defaultdict(list)
    for store in stores:
        declared = parse_catalog(store.history_events, store.raw['prompt'])
        for name, spec in declared.tools.items():
            declaration = store.raw['prompt'][spec.source.start:spec.source.end]
            tools[name] = {'declaration': declaration, 'role': tool_role(name, declaration),
                'arguments': {f.name: {'type': 'number' if f.kind in ('integer', 'number') else f.kind,
                    'enum': f.enum, 'required': f.required,
                    'witness': {'kind': 'DECLARATION', 'source_sha256': store.source_sha256,
                                'start': f.source.start, 'end': f.source.end}}
                    for f in spec.fields}}
        for i, event in enumerate(store.history_events):
            if event.kind == 'result' and event.json_valid and event.name in tools:
                # Read and unknown declarations supply observations, never effects inferred from a call.
                if tools[event.name]['role'] != 'WRITE_OR_EFFECT':
                    observed.append((event.name, event.value,
                        {'source_sha256': store.source_sha256, 'source_id': 'h' + str(i)}))

    def collect(name, value, parts, record_id):
        if isinstance(value, dict):
            nodes[name, parts].append((record_id, value))
            for key, child in value.items():
                collect(name, child, parts + ('{key}' if intrinsic_key(key, child) else key,), record_id)
        elif isinstance(value, list):
            for child in value: collect(name, child, parts + ('*',), record_id)
    for i, (name, value, _) in enumerate(observed): collect(name, value, (), i)
    dynamic = defaultdict(set)
    for location, values in nodes.items():
        by_shape = defaultdict(lambda: defaultdict(set))
        for record_id, value in values:
            for key, child in value.items():
                by_shape[repr(shape(child))][key].add(record_id)
        for keys in by_shape.values():
            # Different keys on different observations, not two fixed fields of one object.
            if len(keys) >= 2 and len(set.union(*keys.values())) >= 2:
                all_records = set.union(*keys.values())
                # A stable field of the same shape is evidence for a record,
                # not a homogeneous dynamic map. Keep those namespaces literal.
                if not any(seen == all_records for seen in keys.values()):
                    dynamic[location].update(keys)

    paths, witnesses, collection_fields, item_types = defaultdict(set), {}, defaultdict(set), defaultdict(set)
    def walk(name, value, parts, witness, raw_parts=()):
        path = 'state.' + name + '.' + pointer(parts)
        # Scalar leaves and collections are the evaluator's field slots.
        # Nonempty intermediate objects are namespaces, not scalar conditions.
        if not isinstance(value, dict) or not value:
            paths[path].add(scalar_type(value)); witnesses.setdefault(path, witness)
        if isinstance(value, list):
            item_types[path].update(scalar_type(v) for v in value)
            for child in value:
                if isinstance(child, dict): collection_fields['state.' + name + '.' + pointer(parts + ('*',))].update(child)
                walk(name, child, parts + ('*',), witness, raw_parts + ('*',))
        if isinstance(value, dict):
            for key, child in value.items():
                collapsed = intrinsic_key(key, child) or key in dynamic[name, raw_parts]
                part = '{key}' if collapsed else key
                if collapsed:
                    root = 'state.' + name + '.' + pointer(parts + ('{key}',))
                    collection_fields[root].add('$key')
                    if isinstance(child, dict): collection_fields[root].update(child)
                walk(name, child, parts + (part,), witness,
                     raw_parts + ('{key}' if intrinsic_key(key, child) else key,))
    for name, value, witness in observed: walk(name, value, (), witness)
    for name, spec in tools.items():
        for field, item in spec['arguments'].items():
            paths['args.' + field].add(item['type'])
            witnesses.setdefault('args.' + field, item['witness'])
    paths['ctx.current_datetime'].add('string')
    paths['user.explicit_confirmation'].add('boolean')
    witnesses['ctx.current_datetime'] = {'kind': 'CODE_WITNESS', 'resolver': 'current_datetime'}
    witnesses['user.explicit_confirmation'] = {'kind': 'CODE_WITNESS', 'resolver': 'explicit_confirmation'}
    return {'tools': tools, 'paths': {p: sorted(t) for p, t in sorted(paths.items())},
        'path_witnesses': witnesses,
        'collection_fields': {p: sorted(f) for p, f in sorted(collection_fields.items())},
        'array_item_types': {p: sorted(t) for p, t in item_types.items()},
        'object_namespace_policy': 'Nonempty objects are namespaces; scalar leaves, arrays and empty objects retained.'}


def compact_catalog(catalog, trigger):
    arguments = catalog['tools'].get(trigger.get('tool'), {}).get('arguments', {})
    return {p: t for p, t in catalog['paths'].items() if not p.startswith('args.') or p[5:] in arguments}
