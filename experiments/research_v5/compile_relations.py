"""Build Formula paths in code, then reuse native facts and three-valued logic."""
from copy import copy, deepcopy
from types import SimpleNamespace
from experiments.research_v5.contracts import AtomicReply
from experiments.research_v5.atomic_relations import context, relation_id
from guardian_truth.evidence_graph.facts import compare, native_operand
from guardian_truth.evidence_graph.logic import evaluate_requirement, conjunction, disjunction, negate
from guardian_truth.evidence_graph.schema import Formula
from guardian_truth.policy_table_v11.provenance import observations
from guardian_truth.policy_table_v11.witness import timeline


class ReadHorizon:
    """Explicit research query horizon; original graph and source metadata unchanged."""
    def __init__(self, graph, tid):
        self.original = graph
        self.refs = graph.refs
        self.store = copy(graph.store)
        self.store.sources = dict(graph.store.sources)
        self.store.sources['@query_horizon'] = {'document': 'response', 'event': len(graph.store.target_events)}
        self.targets = {tid: {**graph.targets[tid], 'source_id': '@query_horizon'}}

    def _assert_integrity(self):
        self.original._assert_integrity()

    def _allowed_prior(self, tid):
        return [s for s, _ in timeline(self.store, self.targets[tid])] + [tid]

    def resolve(self, span):
        return self.original.resolve(span)


def validate(data, reg, fields):
    reply = AtomicReply.model_validate(data).model_dump()
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('policy_ids', 'immutable_policy_ids', 'declaration_ids', 'effect_declaration_ids'):
                    wanted = 'policy' if key in ('policy_ids', 'immutable_policy_ids') else 'declaration'
                    if any(s not in reg['sources'] or reg['sources'][s]['kind'] != wanted for s in item):
                        raise ValueError('WRONG_SOURCE_ROLE:' + key)
                if key in ('lhs', 'rhs', 'target_field', 'evidence_field') and item is not None and item not in fields:
                    raise ValueError('UNKNOWN_CANDIDATE_ID')
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(reply)
    return reply


def check_atom(atom, graph, reg, fields):
    tid = reg['target_id']
    if atom['unresolved'] or atom['operator'] == 'UNRESOLVED' or atom['lhs'] is None:
        return {'value': 'UNKNOWN', 'cause': 'UNRESOLVED_SEMANTIC_SLOT', 'code_source_reads': []}
    lhs = fields[atom['lhs']]
    reads = []
    try:
        if lhs['kind'] not in ('FIELD', 'EVENT'):
            raise ValueError('LHS_NOT_NATIVE')
        if atom['timing'] == 'TARGET_ARGUMENT' and not lhs['is_target']:
            raise ValueError('TARGET_ARGUMENT_NOT_TARGET')
        bindings = []
        for join in atom['joins']:
            target, evidence = fields[join['target_field']], fields[join['evidence_field']]
            if target['kind'] != 'FIELD' or not target['is_target'] or evidence['kind'] != 'FIELD' or evidence['source_id'] != lhs['source_id']:
                raise ValueError('JOIN_CANDIDATE_WRONG_RECORD_OR_TARGET')
            bindings.append({'target_pointer': target['pointer'], 'source_pointer': evidence['pointer']})
        view = graph
        sid = lhs['source_id']
        if sid not in graph._allowed_prior(tid):
            if atom['timing'] == 'IMMUTABLE_STATE' and atom['immutable_policy_ids']:
                view = ReadHorizon(graph, tid)
            elif atom['timing'] == 'RESULT_OF_TARGET':
                view = ReadHorizon(graph, tid)
                receipts = list(observations(timeline(view.store, view.targets[tid]), lhs['tool']))
                selected = [r for r in receipts if r.result_sid == sid and r.valid and r.call_sid == tid]
                if len(selected) != 1:
                    raise ValueError('RESULT_NOT_UNIQUE_TARGET_RECEIPT')
            else:
                raise ValueError('FUTURE_EVIDENCE_NOT_AUTHORIZATION_OR_MUTABLE_STATE')
        if atom['operator'] == 'OCCURRED':
            source = graph.store.sources[sid]
            if lhs['kind'] != 'EVENT' or source['kind'] != 'call' or source['role'] != 'assistant' or not source['json_valid']:
                raise ValueError('NOT_NATIVE_CALL_OCCURRENCE')
            if sid != tid and not bindings and graph.targets[tid]['arguments']:
                raise ValueError('OCCURRENCE_ENTITY_JOIN_UNSPECIFIED')
            # Native argument lineage is still checked for selected joins.
            native_operand(view, tid, {'source_id': sid, 'pointer': ''}, bindings, reads, set())
            value = 'TRUE'
        elif atom['operator'] in ('IS_TRUE', 'IS_FALSE'):
            if lhs['kind'] != 'FIELD':
                raise ValueError('BOOLEAN_TEST_NEEDS_FIELD')
            value = native_operand(view, tid, {'source_id': sid, 'pointer': lhs['pointer']}, bindings, reads, set())
            if type(value) is not bool:
                raise ValueError('BOOLEAN_TEST_NEEDS_BOOL_NOT_NUMBER_OR_STRING')
            value = 'TRUE' if value == (atom['operator'] == 'IS_TRUE') else 'FALSE'
        else:
            rhs = fields.get(atom['rhs'])
            if lhs['kind'] != 'FIELD' or rhs is None or rhs['kind'] == 'EVENT':
                raise ValueError('COMPARISON_NEEDS_TWO_SCALAR_OPERANDS')
            def operand(field):
                if field['kind'] == 'LITERAL':
                    return {'kind': 'SOURCE_LITERAL', 'source_id': field['span']['source_id'],
                            'literal_span': field['span'], 'pointer': None}
                return {'kind': 'NATIVE_JSON', 'source_id': field['source_id'], 'pointer': field['pointer'], 'literal_span': None}
            checked = compare(view, tid, {'lhs': operand(lhs), 'rhs': operand(rhs),
                              'operator': {'EQ': '==', 'NE': '!=', 'LT': '<', 'LE': '<=', 'GT': '>', 'GE': '>='}[atom['operator']],
                              'bindings': bindings})
            return checked
        return {'value': value, 'cause': None, 'code_source_reads': reads,
                'assurance': 'NATIVE_FACT_CHECKED_UNDER_MODEL_SEMANTIC_MAPPING',
                'read_horizon': 'MODEL_SELECTED_IMMUTABILITY_OR_TARGET_RECEIPT' if view is not graph else 'ORIGINAL_PREFIX'}
    except (ValueError, KeyError, TypeError) as e:
        return {'value': 'UNKNOWN', 'cause': str(e), 'code_source_reads': reads}


def execute(row, data, *, violation_query=False):
    graph, reg, fields, _ = context(row)
    reply = validate(data, reg, fields)
    tid = reg['target_id']
    if tid not in graph.targets:
        # Querying prior receipts for a prose target: no inferred business arguments.
        graph.targets[tid] = {'source_id': tid, 'arguments': {}, 'tool': None}
        graph._source_signature = graph._signature()
    traces, results = [], []
    for index, rule in enumerate(reply['rules']):
        witnesses = {}
        def formula(groups, path, source_ids):
            def node(op, children, ids, label):
                return {'op': op, 'label': label, 'spans': [reg['sources'][s]['span'] for s in ids], 'children': children}
            def atom_node(atom, leaf_path):
                rid = relation_id(atom)
                check = check_atom(atom, graph, reg, fields)
                fact_path = leaf_path + '.0' if atom['negated'] else leaf_path
                witnesses[fact_path] = {'value': check['value'], 'reason': check['cause'] or 'Checked native values', 'relation_id': rid}
                traces.append({'rule_index': index, 'relation_id': rid, 'path_assigned_by_code': fact_path, 'proposal': atom, **check})
                leaf = node('ATOM', [], atom['policy_ids'], atom['meaning'])
                return node('NOT', [leaf], atom['policy_ids'], atom['meaning']) if atom['negated'] else leaf
            def group_node(group, group_path):
                atoms = group['all_of']
                if len(atoms) == 1:
                    return atom_node(atoms[0], group_path)
                return node('AND', [atom_node(a, group_path + '.' + str(i)) for i, a in enumerate(atoms)], source_ids, 'Code-built conjunction')
            if len(groups) == 1:
                return group_node(groups[0], path)
            return node('OR', [group_node(g, path + '.' + str(i)) for i, g in enumerate(groups)], source_ids, 'Code-built disjunction')
        condition = formula(rule['condition_any_of'], 'condition', rule['policy_ids'])
        exemptions = [formula(e['any_of'], 'exception.' + str(i), e['policy_ids']) for i, e in enumerate(rule['exceptions'])]
        for f in [condition, *exemptions]:
            Formula.model_validate(f)
        requirement = {'condition': condition, 'guard': None, 'exceptions': exemptions,
                       'modality': rule['modality'], 'open_questions': rule['unresolved']}
        evaluated = evaluate_requirement(requirement, witnesses)
        if rule['applies'] == 'NO':
            status = 'NOT_TRIGGERED'
        elif rule['applies'] == 'UNRESOLVED':
            status = 'UNKNOWN'
        else:
            status = evaluated['status']
        query_value = conjunction([negate(evaluated['exception']),
                      negate(evaluated['condition']) if rule['modality'] == 'REQUIRE' else evaluated['condition']])
        if violation_query and rule['applies'] == 'YES' and not rule['unresolved'] and rule['modality'] != 'PERMIT':
            status = {'TRUE': 'VIOLATED', 'FALSE': 'SATISFIED', 'UNKNOWN': 'UNKNOWN'}[query_value]
        results.append({'rule_id': 'N' + str(index).zfill(4), 'rule': rule, 'condition_formula': condition,
                        'exceptions_formula': exemptions, 'witnesses': witnesses, 'status': status,
                        'legacy_evaluation': evaluated, 'violation_query': query_value})
    gaps = list(reply['open_questions'])
    if reply['effect'] == 'UNKNOWN':
        gaps.append('UNKNOWN_TOOL_EFFECT')
    if reply['coverage'] != 'COMPLETE_OPINION':
        gaps.append('COVERAGE_UNRESOLVED')
    if reply['effect'] == 'UNKNOWN':
        verdict = 'UNKNOWN'
    elif any(r['status'] == 'VIOLATED' for r in results):
        verdict = 'ERROR'
    elif gaps or any(r['status'] == 'UNKNOWN' for r in results):
        verdict = 'UNKNOWN'
    else:
        verdict = 'NO_ERROR'
    graph._assert_integrity()
    return {'verdict': verdict, 'rules': results, 'relations': traces, 'open_questions': gaps,
            'semantic_completeness_proven': False, 'mode': 'SHADOW_MODEL_MEANING',
            'violation_query_ablation': violation_query}
