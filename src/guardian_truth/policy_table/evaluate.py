"""Three-valued rule evaluation. No path/identity ambiguity becomes FALSE."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from .schema import Rule, Table
from .segment import policy_hash, scalar_type


@dataclass(frozen=True)
class Value:
    status: str
    value: object = None
    source_ids: tuple = ()
    reason: str | None = None


UNKNOWN = Value('UNRESOLVED', reason='missing_or_ambiguous_path')


def same(a, b):
    if type(a) is bool or type(b) is bool: return type(a) is type(b) and a == b
    if type(a) in (int, float) and type(b) in (int, float): return Decimal(str(a)) == Decimal(str(b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def select(value, parts, anchors, inherited=None):
    inherited = dict(inherited or {})
    if isinstance(value, dict): inherited.update(value)
    if not parts:
        overlap = set(anchors) & set(inherited)
        if overlap and not all(same(anchors[k], inherited[k]) for k in overlap): return []
        return [(value, inherited)]
    head, *tail = parts
    if head == '*' and isinstance(value, list):
        return [item for child in value for item in select(child, tail, anchors, inherited)]
    if isinstance(value, dict) and head in value: return select(value[head], tail, anchors, inherited)
    return []


def state_value(store, name, parts, target, binding_arguments=None):
    original = target.get('arguments') or {}
    anchors = original if binding_arguments is None else binding_arguments
    if original and not anchors: return UNKNOWN  # comparands alone do not prove entity identity
    results = []
    pending = []
    for index, event in enumerate(store.history_events):
        if event.name != name: continue
        if event.kind == 'call': pending.append(event)
        if event.kind != 'result': continue
        call = pending[0] if len(pending) == 1 else None
        ambiguous = len(pending) > 1
        pending = []
        call_args = call.value if call and call.json_valid and isinstance(call.value, dict) else {}
        overlap = set(anchors) & set(call_args)
        if overlap and not all(same(anchors[k], call_args[k]) for k in overlap): continue
        if not event.json_valid or ambiguous:
            results.append(UNKNOWN); continue
        if not select(event.value, [], anchors, call_args): continue
        containers = select(event.value, parts[:-1], {}, call_args)
        matching_containers = select(event.value, parts[:-1], anchors, call_args)
        if containers and not matching_containers: continue  # explicit other entity, even when the leaf is missing
        selected = select(event.value, parts, anchors, call_args)
        if not selected:
            results.append(UNKNOWN); continue  # latest matching observation lacks path
        # If a relevant entity key exists but does not match, select filtered it.
        # Multiple values/records even with equal values remain ambiguous.
        if len(selected) != 1:
            results.append(UNKNOWN); continue
        value, record = selected[0]
        required_bindings = {k for k, v in anchors.items() if isinstance(v, (str, dict, list))}
        if not required_bindings <= set(record) or (anchors and not (set(anchors) & set(record))):
            results.append(UNKNOWN); continue  # no invented entity binding
        results.append(Value('RESOLVED', value, ('h' + str(index),)))
    return results[-1] if results else UNKNOWN


def resolve(store, path, target, semantic=None, binding_arguments=None):
    if path.startswith('args.'):
        key = path[5:]; args = target.get('arguments') or {}
        return Value('RESOLVED', args[key], (target['source_id'],)) if key in args else UNKNOWN
    if path.startswith('state.'):
        components = state_components(path)
        if components is None: return UNKNOWN
        name, parts = components
        return state_value(store, name, parts, target, binding_arguments)
    semantic = semantic or {}
    value = semantic.get(path)
    if isinstance(value, Value): return value
    return UNKNOWN


def state_components(path):
    suffix = path[6:] if path.startswith('state.') else ''
    if './' in suffix:
        name, pointer = suffix.split('./', 1)
        return name, [p.replace('~1', '/').replace('~0', '~') for p in pointer.split('/')]
    if suffix.endswith('.'): return suffix[:-1], []  # empty JSON Pointer is root
    return None


def condition_value(store, condition, target, semantic=None, binding_arguments=None):
    lhs = resolve(store, condition.lhs, target, semantic, binding_arguments)
    rhs = None if condition.rhs is None else (resolve(store, condition.rhs.path, target, semantic, binding_arguments)
        if condition.rhs.kind == 'PATH' else Value('RESOLVED', condition.rhs.value))
    evidence = {'path': condition.lhs, 'value': lhs.value, 'source_id': lhs.source_ids[0] if lhs.source_ids else None,
        'source_ids': list(lhs.source_ids), 'status': lhs.status}
    if rhs: evidence['rhs'] = {'value': rhs.value, 'source_ids': list(rhs.source_ids), 'status': rhs.status}
    if lhs.status != 'RESOLVED' or (rhs and rhs.status != 'RESOLVED'): return 'UNRESOLVED', evidence
    a, b = lhs.value, rhs.value if rhs else None
    op = condition.op
    try:
        if op == 'exists': truth = a is not None
        elif op == 'not_exists': truth = a is None
        elif op in ('==', '!='):
            explicit_null_test = condition.rhs.kind == 'LITERAL' and condition.rhs.value is None
            if (a is None or b is None) and not explicit_null_test: return 'UNRESOLVED', evidence
            if a is not None and b is not None and scalar_type(a) != scalar_type(b): return 'UNRESOLVED', evidence
            truth = same(a, b) if op == '==' else not same(a, b)
        elif op in ('in', 'not_in'):
            if not isinstance(b, list): return 'UNRESOLVED', evidence
            if b and not any(scalar_type(a) == scalar_type(item) for item in b): return 'UNRESOLVED', evidence
            truth = any(same(a, item) for item in b); truth = truth if op == 'in' else not truth
        elif op in ('before', 'after'):
            if not isinstance(a, str) or not isinstance(b, str): return 'UNRESOLVED', evidence
            a, b = datetime.fromisoformat(a.replace('Z', '+00:00')), datetime.fromisoformat(b.replace('Z', '+00:00'))
            if a.tzinfo is None or b.tzinfo is None: return 'UNRESOLVED', evidence
            truth = a < b if op == 'before' else a > b
        else:
            if type(a) not in (int, float) or type(b) not in (int, float): return 'UNRESOLVED', evidence
            a, b = Decimal(str(a)), Decimal(str(b))
            truth = {'<': a < b, '<=': a <= b, '>': a > b, '>=': a >= b}[op]
    except (ValueError, TypeError): return 'UNRESOLVED', evidence
    return 'TRUE' if truth else 'FALSE', evidence


def state_binding_arguments(rule, target):
    # A value explicitly compared against prior state is a comparand, not a
    # join key. Keep other arguments to establish identity; never infer names.
    comparands = set()
    for c in rule.conditions + [c for group in rule.exceptions for c in group]:
        if c.rhs is None or c.rhs.kind != 'PATH': continue
        if c.lhs.startswith('args.') and c.rhs.path.startswith('state.'):
            comparands.add(c.lhs[5:])
        if c.lhs.startswith('state.') and c.rhs.path.startswith('args.'):
            comparands.add(c.rhs.path[5:])
    return {key: value for key, value in (target.get('arguments') or {}).items() if key not in comparands}


def conjunction(values):
    if 'FALSE' in values: return 'FALSE'
    if 'UNRESOLVED' in values: return 'UNRESOLVED'
    return 'TRUE'


def prior_status(store, name, target):
    anchors = target.get('arguments') or {}
    observed = [e for e in store.history_events if e.kind == 'call' and e.name == name]
    candidates = [e for e in observed if e.role == 'assistant']
    uncertain_actor = any(e.role not in ('assistant', 'user') for e in observed)
    for event in reversed(candidates):
        if not event.json_valid or not isinstance(event.value, dict): continue
        overlap = set(anchors) & set(event.value)
        if anchors and not overlap: continue
        required_bindings = {k for k, v in anchors.items() if isinstance(v, (str, dict, list))}
        if not required_bindings <= set(event.value): continue
        if all(same(anchors[k], event.value[k]) for k in overlap): return 'TRUE'
    # History admission is complete; absence of the required native attempt
    # is established by code. An attempted call does not establish success.
    return 'FALSE' if not candidates and not uncertain_actor else 'UNRESOLVED'


def evaluate_rule(store, rule, target, semantic=None):
    binding_arguments = state_binding_arguments(rule, target)
    pairs = [condition_value(store, c, target, semantic, binding_arguments) for c in rule.conditions]
    values = [v for v, _ in pairs]
    evidence = [e for _, e in pairs]
    exception_values = []
    for group in rule.exceptions:
        group_pairs = [condition_value(store, c, target, semantic, binding_arguments) for c in group]
        evidence.extend(e for _, e in group_pairs)
        exception_values.append(conjunction([v for v, _ in group_pairs]))
    if any(v in ('TRUE', 'UNRESOLVED') for v in exception_values): return {'status': 'NO_FINDING', 'reason': 'exception_true_or_unresolved', 'evaluated': evidence}
    if 'UNRESOLVED' in values: return {'status': 'NO_FINDING', 'reason': 'unresolved_condition', 'evaluated': evidence}
    active = conjunction(values) == 'TRUE'
    if rule.modality == 'FORBIDS': violation = active
    elif rule.modality == 'REQUIRES': violation = not active
    elif rule.modality == 'REQUIRES_PRIOR_CALL':
        prior = prior_status(store, rule.prior_call, target)
        violation = active and prior == 'FALSE'
        evidence.append({'path': 'history.prior_call', 'tool': rule.prior_call, 'value': prior,
            'source_id': 'prompt', 'source_ids': ['prompt'], 'status': 'RESOLVED' if prior != 'UNRESOLVED' else 'UNRESOLVED',
            'basis': 'COMPLETE_NATIVE_CALL_INVENTORY_ATTEMPTS_NOT_SUCCESS'})
    else:
        confirmation = resolve(store, 'user.confirmation_of_trigger', target, semantic)
        violation = active and confirmation.status == 'RESOLVED' and confirmation.value is False
        evidence.append({'path': 'user.confirmation_of_trigger', 'value': confirmation.value, 'source_ids': list(confirmation.source_ids), 'status': confirmation.status})
    return {'status': 'ERROR' if violation else 'NO_FINDING', 'evaluated': evidence}


def evaluate_table(store, table, targets=None, semantic=None):
    from guardian_truth.source_search.id_contract import native_target_inventory
    if table.policy_sha256 != policy_hash(store): raise ValueError('compiled table belongs to another exact system')
    targets = native_target_inventory(store) if targets is None else targets
    findings, trace = [], []
    for item in table.rules:
        if item.get('status') not in ('DECISIVE', 'SHADOW'): raise ValueError('invalid compile agreement status')
        rule = Rule.model_validate(item['rule'])
        from .compile import validate_rule
        validate_rule(rule, table.enum_catalog, [c['id'] for c in table.clauses])
        for target in targets:
            if rule.trigger.kind == 'TOOL_CALL' and target.get('tool') != rule.trigger.tool: continue
            if rule.trigger.kind == 'SPEECH_ACT' and target.get('act') != rule.trigger.act: continue
            result = evaluate_rule(store, rule, target, semantic)
            trace.append({'rule_id': rule.rule_id, 'target_source_id': target['source_id'], 'compile_agreement_status': item['status'], **result})
            if result['status'] == 'ERROR':
                findings.append({'type': 'POLICY_TABLE', 'rule_id': rule.rule_id, 'clause_ids': rule.clause_ids,
                    'target_source_id': target['source_id'], 'evaluated': result['evaluated'],
                    'status': 'CONFIRMED_BY_CODE', 'compile_agreement_status': item['status']})
    return {'findings': findings, 'trace': trace, 'emits_no_error': False}


def load_table(store, directory):
    path = Path(directory) / (policy_hash(store) + '.json')
    if not path.exists(): return None
    table = Table.model_validate_json(path.read_text(encoding='utf-8'))
    if table.policy_sha256 != policy_hash(store): raise ValueError('table cache hash mismatch')
    from .compile import canonical, validate_rule
    from .schema import Compilation
    from collections import Counter
    # Cache files cannot self-assert DECISIVE. Recompute agreement over the
    # preserved samples using the exact frozen compilation inventory.
    support = Counter()
    if len(table.samples) != 3: raise ValueError('cache must preserve three samples')
    for sample in table.samples:
        try: parsed = Compilation.model_validate(sample)
        except ValueError: continue
        seen = set()
        for rule in parsed.rules:
            try: validate_rule(rule, table.enum_catalog, [c['id'] for c in table.clauses])
            except ValueError: continue
            seen.add(canonical(rule))
        support.update(seen)
    for item in table.rules:
        rule = Rule.model_validate(item['rule'])
        key = canonical(rule)
        expected = 3 if item.get('status') == 'DECISIVE' else 2 if item.get('status') == 'SHADOW' else 0
        if expected == 0 or item.get('agreement') != expected or support[key] != expected:
            raise ValueError('cache agreement/status mismatch')
    return table
