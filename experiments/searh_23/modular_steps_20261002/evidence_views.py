"""Read-only source graph; chronology edges never certify latest-state truth."""
from dataclasses import asdict
import json
from modular_common import sha
from guardian_truth.parsing import parse_events
from guardian_truth.provenance import build_graph, identities


def graph_for(row):
    from structural_v02 import parse_case_v02
    history = parse_events(row['prompt'], 'prompt')
    target = parse_events(row['response'], 'response')
    native = build_graph(history, target, max_links=256)
    ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
    user_text = '\n'.join(e.text for e in history if e.role == 'user')
    focus_text = row['response'] + '\n' + user_text
    scope = {json.dumps(e.value, sort_keys=True) for f in native.facts for e in f.entities
             if str(e.value) and str(e.value) in focus_text}
    facts = [asdict(f) for f in native.facts if not scope or any(json.dumps(e.value, sort_keys=True) in scope for e in f.entities)]
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
                         'target_entity_selection': 'literal identity occurrences, never semantic aliases',
                         'selection_scope_ambiguous': not bool(scope)},
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
        if op in ('observations', 'grounds'):
            result = {'facts': facts, 'current_state_semantics': 'NOT_INFERRED'}
        elif op == 'changes':
            ids = {f['id'] for f in facts}
            result = {'facts': facts, 'edges': [e for e in self.graph['edges'] if e['from'] in ids and e['to'] in ids]}
        elif op == 'requirements':
            result = {'policy': self.graph['policy'], 'coverage': 'FULL_RAW_POLICY_NOT_COMPILED'}
        else:
            result = {'catalog': self.graph['catalog'], 'authorization': 'UNVERIFIED_REQUIRES_POLICY'}
        return {'status': 'OK', 'data': result, 'remaining': self.remaining}
