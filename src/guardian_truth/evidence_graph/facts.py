"""Typed native facts with unique receipts and explicit same-record joins.

This checks the proposed factual comparison. Its mapping to an NL requirement
and the completeness of the selected joins remain model hypotheses.
"""
from guardian_truth.parsing import decode_json
from guardian_truth.policy_table.evaluate import same
from guardian_truth.policy_table_v11.provenance import observations
from guardian_truth.policy_table_v11.witness import timeline


def pointer(value, path):
    if not isinstance(path, str) or (path and not path.startswith('/')):
        raise ValueError('INVALID_JSON_POINTER')
    ancestors = []
    parts = path[1:].split('/') if path else []
    for raw in parts:
        key = raw.replace('~1', '/').replace('~0', '~')
        if '~' in raw.replace('~0', '').replace('~1', ''):
            raise ValueError('INVALID_JSON_POINTER_ESCAPE')
        if isinstance(value, dict):
            ancestors.append(value)
            if key not in value:
                raise ValueError('SOURCE_PATH_MISSING')
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and str(int(key)) == key and int(key) < len(value):
            value = value[int(key)]
        else:
            raise ValueError('SOURCE_PATH_MISSING_OR_WRONG_CONTAINER')
    if isinstance(value, dict):
        ancestors.append(value)
    return value, ancestors


def native_operand(graph, target_id, operand, bindings, reads, compared_fields):
    sid = operand['source_id']
    target = graph.targets[target_id]
    if sid not in graph._allowed_prior(target_id):
        raise ValueError('FACT_AFTER_TARGET_OR_SOURCE_NOT_NATIVE')
    source = graph.store.sources.get(sid)
    if not source or source['role'] != 'assistant' or source['kind'] not in ('call', 'result'):
        raise ValueError('FACT_NOT_NATIVE_ASSISTANT_CALL_OR_RESULT')
    events = graph.store.history_events if source['document'] == 'prompt' else graph.store.target_events
    event = events[source['event']]
    if not event.json_valid:
        raise ValueError('NATIVE_JSON_INVALID')
    call_args = {}
    if source['kind'] == 'result':
        receipts = list(observations(timeline(graph.store, target), source['tool']))
        selected = [r for r in receipts if r.result_sid == sid]
        if len(selected) != 1 or not selected[0].valid:
            raise ValueError('RESULT_WITHOUT_UNIQUE_VALID_PRIOR_CALL')
        def possibly_same_entity(receipt):
            if receipt.call is None or not isinstance(receipt.call.value, dict):
                return True
            for b in bindings:
                wanted, _ = pointer(target['arguments'], b['target_pointer'])
                names = {b['source_pointer'].split('/')[-1], b['target_pointer'].split('/')[-1]}
                for name in names:
                    name = name.replace('~1', '/').replace('~0', '~')
                    if name in receipt.call.value and not same(receipt.call.value[name], wanted):
                        return False
            return True
        relevant = [r for r in receipts if possibly_same_entity(r)]
        if not relevant or relevant[-1].result_sid != sid:
            raise ValueError('OBSERVATION_SUPERSEDED_BY_LATER_RESULT')
        call_args = selected[0].call.value
        if target['arguments'] and not bindings:
            raise ValueError('OBSERVATION_ENTITY_JOIN_UNSPECIFIED')
    elif not isinstance(event.value, dict):
        raise ValueError('CALL_ARGUMENTS_NOT_OBJECT')
    value, lineage = pointer(event.value, operand['pointer'])
    for binding in bindings if sid != target_id else []:
        wanted, _ = pointer(target['arguments'], binding['target_pointer'])
        observed, ancestors = pointer(event.value, binding['source_pointer'])
        if not same(wanted, observed):
            raise ValueError('ENTITY_JOIN_MISMATCH')
        key = binding['source_pointer'].split('/')[-1].replace('~1', '/').replace('~0', '~')
        target_key = binding['target_pointer'].split('/')[-1].replace('~1', '/').replace('~0', '~')
        # Do not let a matching child overwrite a contradictory parent identity.
        if any(key in ancestor and not same(ancestor[key], wanted) for ancestor in ancestors):
            raise ValueError('PARENT_ENTITY_CONTRADICTION')
        if any(k in call_args and not same(call_args[k], wanted) for k in {key, target_key}):
            raise ValueError('READ_CALL_ENTITY_CONTRADICTION')
        # Binding must concern this selected record, not a conveniently matching sibling.
        selected_parts = operand['pointer'].split('/')[1:]
        binding_parts = binding['source_pointer'].split('/')[1:-1]
        if selected_parts[:len(binding_parts)] != binding_parts:
            raise ValueError('JOIN_OUTSIDE_SELECTED_RECORD_LINEAGE')
    if sid != target_id:
        # An omitted join cannot conceal an explicit contradictory parent field.
        # Compared fields can legitimately differ (old state versus new value).
        for field, wanted in target['arguments'].items():
            if field not in compared_fields and not isinstance(wanted, (dict, list)):
                if any(field in layer and not same(layer[field], wanted) for layer in lineage):
                    raise ValueError('COMMON_PARENT_FIELD_CONTRADICTION')
    reads.append({'source_id': sid, 'pointer': operand['pointer'], 'value': value,
        'document': source['document'], 'start': source['start'], 'end': source['end'],
        'read_by_code': 'FULL_NATIVE_JSON_RECORD',
        'bindings_checked': bindings})
    return value


def compare(graph, target_id, check):
    reads = []
    compared_fields = {o['pointer'].split('/')[-1].replace('~1', '/').replace('~0', '~')
                       for o in (check['lhs'], check['rhs']) if o['kind'] == 'NATIVE_JSON'}
    def operand(o):
        if o['kind'] == 'NATIVE_JSON':
            return native_operand(graph, target_id, o, check['bindings'], reads, compared_fields)
        span = graph.resolve(o['literal_span'])
        if graph.refs[o['source_id']]['role'] != 'system':
            raise ValueError('COMPARISON_CONSTANT_NOT_POLICY_SOURCE')
        value, valid = decode_json(span['text'])
        if not valid or isinstance(value, (dict, list)):
            raise ValueError('POLICY_LITERAL_NOT_EXACT_JSON_SCALAR')
        return value
    try:
        graph._assert_integrity()
        left, right = operand(check['lhs']), operand(check['rhs'])
        operator = check['operator']
        if operator in ('==', '!='):
            equal = same(left, right)
            result = equal if operator == '==' else not equal
        else:
            if type(left) not in (int, float) or type(right) not in (int, float):
                raise ValueError('ORDER_COMPARISON_NEEDS_NUMBERS')
            result = {'<': left < right, '<=': left <= right, '>': left > right, '>=': left >= right}[operator]
        return {'value': 'TRUE' if result else 'FALSE', 'left': left, 'right': right,
                'assurance': 'CODE_CHECKED_NATIVE_FACT_NOT_POLICY_MEANING', 'cause': None,
                'code_source_reads': reads}
    except (ValueError, TypeError, KeyError) as error:
        return {'value': 'UNKNOWN', 'cause': str(error),
                'assurance': 'UNRESOLVED_NATIVE_FACT', 'code_source_reads': reads}
