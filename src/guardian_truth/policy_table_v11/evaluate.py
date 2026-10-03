"""Atomic three-valued evaluation, same-entity binding, no unknown-to-error conversion."""
from guardian_truth.policy_table.evaluate import (Value, UNKNOWN, same, condition_value,
    conjunction, state_value, state_components)
from guardian_truth.policy_table.schema import Condition, LiteralOperand
from guardian_truth.policy_table.segment import policy_hash
from guardian_truth.source_search.id_contract import native_target_inventory
from guardian_truth.source_search.store import SourceStore
from .schema import Atom, Expression, requirement
from .witness import timeline, explicit_confirmation, current_datetime
from .compile import verify_table, validate_expression


def disjunction(values):
    if 'TRUE' in values: return 'TRUE'
    if 'UNRESOLVED' in values: return 'UNRESOLVED'
    return 'FALSE'


def prefix_store(store, target):
    # Previous events of the current response are prior facts only for later calls.
    events = timeline(store, target)
    copy = object.__new__(SourceStore)
    copy.history_events = [e for _, e in events]
    return copy, { 'h' + str(i): sid for i, (sid, _) in enumerate(events)}


def collection_select(value, parts, quantifier, binding, arguments):
    if not parts: return [Value('RESOLVED', value)]
    head, *tail = parts
    if head in ('*', '{key}'):
        if head == '*' and isinstance(value, list): records = list(enumerate(value))
        elif head == '{key}' and isinstance(value, dict): records = list(value.items())
        else: return [UNKNOWN]
        if not records: return [Value('UNRESOLVED', reason='empty_collection')]
        if quantifier == 'TARGET':
            if binding is None or binding.argument not in arguments: return [UNKNOWN]
            wanted = arguments[binding.argument]
            def identity(key, record):
                if binding.record_field == '$key': return key
                if binding.record_field == '*': return record
                return record.get(binding.record_field) if isinstance(record, dict) else None
            # Scalar argument or an explicitly requested collection of identities.
            wanted = wanted if isinstance(wanted, list) else [wanted]
            selected = []
            for item in wanted:
                matching = [(k, v) for k, v in records if same(identity(k, v), item)]
                if len(matching) != 1: return [Value('UNRESOLVED', reason='TARGET_missing_or_ambiguous_record')]
                selected.extend(matching)
            if not selected: return [UNKNOWN]
            records = selected
        return [result for _, child in records for result in collection_select(child, tail, quantifier, binding, arguments)]
    if isinstance(value, dict) and head in value: return collection_select(value[head], tail, quantifier, binding, arguments)
    return [UNKNOWN]


def anchors(target, expression):
    args = target.get('arguments') or {}
    comparands = set()
    for expr in flatten(expression):
        if expr.kind == 'COMPARE' and expr.rhs and expr.rhs.kind == 'PATH':
            if expr.lhs.startswith('args.') and expr.rhs.path.startswith('state.'): comparands.add(expr.lhs[5:])
            if expr.lhs.startswith('state.') and expr.rhs.path.startswith('args.'): comparands.add(expr.rhs.path[5:])
    eligible = {k: v for k, v in args.items() if k not in comparands}
    identifiers = {k: v for k, v in eligible.items() if k == 'id' or k.endswith('_id')}
    return identifiers or eligible


def observed_anchors(store, name, entity):
    # A read tool records only the identifiers it was called with. Requiring every target
    # identifier (e.g. payment_method_id for a get_order_details record) as a record key makes
    # the state permanently UNRESOLVED. Keep the identifiers the read tool was called with;
    # if none overlap, keep the original anchors (conservative: never weaker than before).
    keys = set()
    for event in store.history_events:
        if event.name == name and event.kind == 'call' and event.json_valid and isinstance(event.value, dict):
            keys |= set(event.value)
    restricted = {k: v for k, v in entity.items() if k in keys}
    return restricted or entity


def flatten(expr):
    yield expr
    for child in expr.items or []: yield from flatten(child)


def resolved_values(store, path, target, expr):
    if path == 'ctx.current_datetime': return [current_datetime(store, target)]
    if path == 'user.explicit_confirmation': return [explicit_confirmation(store, target)]
    if path.startswith('args.'):
        key = path[5:]; arguments = target.get('arguments') or {}
        return [Value('RESOLVED', arguments[key], (target['source_id'],))] if key in arguments else [UNKNOWN]
    components = state_components(path)
    if components is None: return [UNKNOWN]
    name, parts = components
    prior, source_map = prefix_store(store, target)
    entity = anchors(target, expr)
    if '*' not in parts and '{key}' not in parts:
        value = state_value(prior, name, parts, target, observed_anchors(prior, name, entity))
        return [Value(value.status, value.value, tuple(source_map.get(s, s) for s in value.source_ids), value.reason)]
    pending, observations = [], []
    for i, event in enumerate(prior.history_events):
        if event.name != name: continue
        if event.kind == 'call': pending.append(event)
        if event.kind != 'result': continue
        call = pending[0] if len(pending) == 1 else None
        ambiguous = len(pending) > 1; pending = []
        call_args = call.value if call and call.json_valid and isinstance(call.value, dict) else {}
        overlap = set(entity) & set(call_args)
        if overlap and any(not same(entity[k], call_args[k]) for k in overlap): continue
        if ambiguous or not event.json_valid:
            observations.append([Value('UNRESOLVED', source_ids=(source_map['h' + str(i)],), reason='latest_result_invalid_or_unpaired')]); continue
        selected = collection_select(event.value, parts, expr.quantifier, expr.binding, target.get('arguments') or {})
        observations.append([Value(v.status, v.value, (source_map['h' + str(i)],), v.reason) for v in selected])
    return observations[-1] if observations else [UNKNOWN]


def compare(a, b, expr):
    evidence = {'path': expr.lhs, 'value': a.value, 'source_ids': list(a.source_ids), 'status': a.status, 'reason': a.reason}
    if b is not None: evidence['rhs'] = {'value': b.value, 'source_ids': list(b.source_ids), 'status': b.status, 'reason': b.reason}
    if a.status != 'RESOLVED' or b is not None and b.status != 'RESOLVED': return 'UNRESOLVED', evidence
    # Reuse V10's typed Decimal, explicit-null, membership and timezone logic.
    try:
        condition = Condition(lhs='args._lhs', op=expr.op,
            rhs=None if b is None else LiteralOperand(kind='LITERAL', value=b.value))
    except ValueError: return 'UNRESOLVED', evidence
    status, _ = condition_value(None, condition, {'source_id': 'comparison', 'arguments': {'_lhs': a.value}})
    return status, evidence


def prior_call(store, expr, target):
    events = timeline(store, target)
    calls = [(sid, e) for sid, e in events if e.kind == 'call' and e.name == expr.tool]
    uncertain = any(e.role not in ('assistant', 'user') or e.role == 'assistant' and not e.json_valid for _, e in calls)
    candidates = [(sid, e) for sid, e in calls if e.role == 'assistant' and e.json_valid and isinstance(e.value, dict)]
    if expr.binding:
        argument = (target.get('arguments') or {}).get(expr.binding.argument)
        if argument is None: return 'UNRESOLVED', []
        for sid, event in candidates:
            if expr.binding.record_field in event.value and same(argument, event.value[expr.binding.record_field]):
                return 'TRUE', [{'prior_call': expr.tool, 'source_ids': [sid], 'binding': expr.binding.model_dump()}]
        # Complete call inventory proves no bound attempt, unless an unparseable actor/call remains.
        return ('UNRESOLVED' if uncertain else 'FALSE'), [{'prior_call': expr.tool, 'source_ids': [s for s, _ in calls], 'basis': 'COMPLETE_BOUND_ATTEMPT_INVENTORY'}]
    if candidates: return 'TRUE', [{'prior_call': expr.tool, 'source_ids': [candidates[-1][0]], 'basis': 'ATTEMPT_ONLY_UNBOUND_POLICY_REQUIREMENT'}]
    return ('UNRESOLVED' if uncertain else 'FALSE'), [{'prior_call': expr.tool, 'source_ids': [], 'basis': 'COMPLETE_NATIVE_ATTEMPT_INVENTORY'}]


def evaluate_expression(store, expr, target):
    if expr.kind in ('ANY_OF', 'ALL_OF'):
        evaluated = [evaluate_expression(store, child, target) for child in expr.items]
        values = [v for v, _ in evaluated]
        return (disjunction(values) if expr.kind == 'ANY_OF' else conjunction(values)), [e for _, es in evaluated for e in es]
    if expr.kind == 'PRIOR_CALL': return prior_call(store, expr, target)
    if expr.kind == 'CONFIRMATION':
        value = explicit_confirmation(store, target)
        return ('TRUE' if value.value is True else 'FALSE') if value.status == 'RESOLVED' else 'UNRESOLVED', [
            {'path': 'user.explicit_confirmation', 'value': value.value, 'status': value.status,
             'source_ids': list(value.source_ids), 'reason': value.reason}]
    left = resolved_values(store, expr.lhs, target, expr)
    if expr.rhs is None: right = [None]
    elif expr.rhs.kind == 'LITERAL': right = [Value('RESOLVED', expr.rhs.value)]
    else: right = resolved_values(store, expr.rhs.path, target, expr)
    # Two collections need a relational join, not an invented zip/cartesian product.
    if len(left) > 1 and len(right) > 1: return 'UNRESOLVED', [{'reason': 'two_collection_join_unsupported'}]
    evaluated = [compare(a, b, expr) for a in left for b in right]
    values = [v for v, _ in evaluated]
    # Empty collection and missing TARGET remain unknown, including FORBIDS.
    return (disjunction(values) if expr.quantifier == 'ANY' else conjunction(values)), [e for _, e in evaluated]


def evaluate_atom(store, atom, target):
    expr = requirement(atom)
    value, evidence = evaluate_expression(store, expr, target)
    exception_pairs = [evaluate_expression(store, exc, target) for exc in atom.exceptions]
    suppressed = any(v in ('TRUE', 'UNRESOLVED') for v, _ in exception_pairs)
    violation = value == ('TRUE' if atom.modality == 'FORBIDS' else 'FALSE') and not suppressed
    return {'finding': violation, 'value': value, 'evaluated': evidence,
        'exception_values': [v for v, _ in exception_pairs],
        'exception_evidence': [e for _, es in exception_pairs for e in es], 'suppressed': suppressed}


def evaluate_table(store, table, targets=None):
    if policy_hash(store) != table['policy']['policy_sha256']: raise ValueError('wrong_policy')
    verify_table(table)
    targets = native_target_inventory(store) if targets is None else targets
    findings, trace = [], []
    for entry in table['atoms']:
        atom = Atom.model_validate(entry['atom']); trigger = entry['trigger']
        for target in targets:
            if trigger.get('tool') != target.get('tool') or trigger.get('act') != target.get('act'): continue
            result = evaluate_atom(store, atom, target)
            record = {'atom_id': entry['atom_id'], 'status': entry['status'], 'trigger': trigger,
                'target_source_id': target['source_id'], 'clause_ids': atom.clause_ids, **result}
            trace.append(record)
            if result['finding']: findings.append(record)
    return {'findings': findings, 'trace': trace,
        'decisive_error': any(f['status'] == 'DECISIVE' for f in findings), 'emits_no_error': False}
