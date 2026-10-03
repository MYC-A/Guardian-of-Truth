"""Source-preserving inventory. Segmentation is not semantic completeness."""
import hashlib
import re
from guardian_truth.parsing import parse_catalog


def system_text(store):
    return '\n'.join(e.text for e in store.history_events if e.role == 'system')


def policy_hash(store):
    return hashlib.sha256(re.sub(r'\s+', ' ', system_text(store)).strip().encode('utf-8')).hexdigest()


def clauses(store):
    # Numbered/list/headed paragraphs preserve shared antecedents. Full blocks
    # are retained as parent context instead of independently formalized cuts.
    result = []
    for sid, source in store.sources.items():
        if source['document'] != 'prompt' or source['role'] != 'system': continue
        text = store.text(sid)
        catalog = parse_catalog(store.history_events, store.raw['prompt'])
        end = len(text)
        if catalog.source and source['start'] <= catalog.source.start < source['end']:
            end = catalog.source.start - source['start']
        boundaries = [0] + [m.start() for m in re.finditer(r'(?m)^(?:#{1,6} |\d+[.)] |[-*] )', text[:end]) if m.start() > 0] + [end]
        for left, right in zip(boundaries, boundaries[1:]):
            if not text[left:right].strip(): continue
            result.append({'id': 'clause_' + str(len(result)), 'source_id': sid,
                'document': 'prompt', 'start': source['start'] + left, 'end': source['start'] + right,
                'text': text[left:right], 'parent_source_id': sid})
    return result


def scalar_type(value):
    if value is None: return 'null'
    if type(value) is bool: return 'boolean'
    if type(value) in (int, float): return 'number'
    if isinstance(value, str): return 'string'
    if isinstance(value, list): return 'array'
    return 'object'


def leaves(value, prefix=()):
    # Containers are real paths too: comparing a list/object must not depend
    # on the incidental presence of at least one scalar child.
    yield prefix, value
    if isinstance(value, dict):
        for key, child in value.items(): yield from leaves(child, prefix + (key,))
    elif isinstance(value, list):
        for child in value: yield from leaves(child, prefix + ('*',))


def pointer(parts):
    return '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in parts) if parts else ''


def enum_catalog(stores):
    tools, paths, witnesses, arg_witnesses, array_item_types = {}, {}, {}, {}, {}
    for store in stores:
        catalog = parse_catalog(store.history_events, store.raw['prompt'])
        for name, tool in catalog.tools.items():
            tools.setdefault(name, {'arguments': {}})
            for field in tool.fields:
                declaration = store.raw['prompt'][field.source.start:field.source.end]
                declared_format = re.search(r'\[format:\s*([^\]\s]+)\s*\]', declaration)
                tools[name]['arguments'][field.name] = {'type': field.kind, 'enum': field.enum,
                    'required': field.required, 'format': declared_format[1] if declared_format else None}
                path = 'args.' + field.name
                paths.setdefault(path, set()).add('number' if field.kind in ('integer', 'number') else field.kind)
        for sid, source in store.sources.items():
            if source['kind'] != 'call': continue
            event = (store.history_events if source['document'] == 'prompt' else store.target_events)[source['event']]
            if not event.json_valid or not isinstance(event.value, dict): continue
            for key in event.value:
                path = 'args.' + key
                if path in paths:
                    witnesses.setdefault(path, [{'source_sha256': store.source_sha256, 'source_id': sid}])
                    arg_witnesses.setdefault(event.name, {}).setdefault(key, [{'source_sha256': store.source_sha256, 'source_id': sid}])
        for index, event in enumerate(store.history_events):
            if event.kind != 'result' or not event.json_valid: continue
            for parts, value in leaves(event.value):
                path = 'state.' + event.name + '.' + pointer(parts)
                paths.setdefault(path, set()).add(scalar_type(value))
                if isinstance(value, list):
                    array_item_types.setdefault(path, set()).update(scalar_type(item) for item in value)
                witnesses.setdefault(path, [{'source_sha256': store.source_sha256, 'source_id': 'h' + str(index)}])
    paths['user.confirmation_of_trigger'] = {'boolean'}
    paths['ctx.current_datetime'] = {'string'}
    return {'tools': tools, 'paths': {k: sorted(v) for k, v in sorted(paths.items())},
        'path_witnesses': witnesses, 'arg_witnesses': arg_witnesses,
        'array_item_types': {k: sorted(v) for k, v in sorted(array_item_types.items())}}
