"""Code-owned candidate addresses, backed by the unchanged original sources."""
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
import pilot as v4
from guardian_truth.source_search.store import digest


def scalar_fields(value, trail=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from scalar_fields(child, trail + (str(key),))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from scalar_fields(child, trail + (str(i),))
    else:
        yield trail, value


def pointer(trail):
    return ''.join('/' + x.replace('~', '~0').replace('/', '~1') for x in trail)


def context(row):
    graph = v4.make_graph(row)
    reg = v4.registry(row, graph)
    fields = {}
    for sid, source in reg['sources'].items():
        if source['kind'] in ('call', 'result') and source['native_json'] is not None:
            for trail, value in scalar_fields(source['native_json']):
                fid = 'F' + str(len(fields)).zfill(4)
                fields[fid] = {'kind': 'FIELD', 'source_id': sid, 'pointer': pointer(trail),
                               'record_keys': list(trail), 'value': value,
                               'native_kind': source['kind'], 'tool': graph.store.sources[sid]['tool'],
                               'is_target': sid == reg['target_id']}
            fid = 'F' + str(len(fields)).zfill(4)
            fields[fid] = {'kind': 'EVENT', 'source_id': sid, 'native_kind': source['kind'],
                           'tool': graph.store.sources[sid]['tool'], 'is_target': sid == reg['target_id']}
    for lid, entry in reg['policy_literals'].items():
        fields['K' + lid[1:].zfill(4)] = {'kind': 'LITERAL', **entry}
    packet = v4.packet(reg)
    packet['candidates'] = {fid: {k: v for k, v in f.items() if k not in ('pointer', 'span')}
                            for fid, f in fields.items()}
    return graph, reg, fields, packet


def relation_id(atom):
    return 'R' + digest(atom)[:16]


def schema_for(schema, reg, fields):
    result = deepcopy(schema.model_json_schema())
    def walk(node):
        if isinstance(node, dict):
            for key, item in node.get('properties', {}).items():
                if key in ('policy_ids', 'immutable_policy_ids'):
                    item['items']['enum'] = [s for s, x in reg['sources'].items() if x['kind'] == 'policy']
                elif key in ('declaration_ids', 'effect_declaration_ids'):
                    item['items']['enum'] = [s for s, x in reg['sources'].items() if x['kind'] == 'declaration']
                elif key in ('target_field', 'evidence_field'):
                    item['enum'] = [s for s, x in fields.items() if x['kind'] == 'FIELD' and
                                    (key != 'target_field' or x['is_target'])]
                elif key in ('lhs', 'rhs'):
                    for option in item.get('anyOf', []):
                        if option.get('type') == 'string':
                            option['enum'] = list(fields)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(result)
    return result
