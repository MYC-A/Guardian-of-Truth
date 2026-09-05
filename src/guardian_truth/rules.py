"""A bounded, declarative policy interpreter. No prose inference or execution."""

from dataclasses import dataclass, field
from datetime import date
import re

from .parsing import decode_json
from .provenance import lineage, value_key
from .types import Event, EvidenceGraph, Finding, Source


OPEN, CLOSE = '[GUARDIAN_RULES]', '[/GUARDIAN_RULES]'
MAX_BYTES, MAX_RULES, MAX_NODES, MAX_DEPTH = 65536, 128, 2048, 24
UNKNOWN = object()
COMPARISONS = {'eq', 'ne', 'lt', 'le', 'gt', 'ge', 'in', 'not_in', 'date_lt', 'date_le', 'date_gt', 'date_ge'}


@dataclass
class Value:
    value: object = UNKNOWN
    sources: list[Source] = field(default_factory=list)


def _source_valid(source):
    return isinstance(source, Source) and source.document in ('prompt', 'response') and 0 <= source.start < source.end


def _path_valid(path):
    return isinstance(path, list) and 0 < len(path) <= MAX_DEPTH and all(
        isinstance(x, str) and bool(x) or type(x) is int and x >= 0 for x in path)


def _keys(value, required, optional=()):
    return isinstance(value, dict) and set(required) <= value.keys() and value.keys() <= set(required) | set(optional)


def _bounded_json(value):
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > MAX_DEPTH * 3 or nodes > MAX_NODES * 8:
            return False
        if isinstance(item, (dict, list)):
            pending.extend((child, depth + 1) for child in (item.values() if isinstance(item, dict) else item))
    return True


def _validate_operand(value):
    if not isinstance(value, dict) or len(value) != 1:
        return False
    key, payload = next(iter(value.items()))
    if key == 'literal':
        return True
    if key in ('arg', 'context'):
        return _path_valid(payload)
    if key != 'fact' or not _keys(payload, ('tool', 'role', 'field', 'entity'), ('container',)):
        return False
    return (isinstance(payload['tool'], str) and bool(payload['tool'])
            and payload['role'] in ('assistant', 'user')
            and isinstance(payload['field'], str) and bool(payload['field'])
            and isinstance(payload['entity'], dict) and bool(payload['entity'])
            and all(isinstance(k, str) and bool(k) and isinstance(v, dict) and len(v) == 1
                    and next(iter(v)) in ('arg', 'context', 'literal') and _validate_operand(v)
                    for k, v in payload['entity'].items())
            and ('container' not in payload or isinstance(payload['container'], list)
                 and all(isinstance(k, str) for k in payload['container'])))


def _validate_expr(expr, budget, depth=0):
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_DEPTH:
        return False
    if type(expr) is bool:
        return True
    if not isinstance(expr, dict) or len(expr) != 1:
        return False
    op, payload = next(iter(expr.items()))
    if op in ('all', 'any'):
        return isinstance(payload, list) and bool(payload) and all(_validate_expr(v, budget, depth + 1) for v in payload)
    if op == 'not':
        return _validate_expr(payload, budget, depth + 1)
    return op in COMPARISONS and isinstance(payload, list) and len(payload) == 2 and all(_validate_operand(v) for v in payload)


def _parse_policy(history):
    blocks = [event for event in history if event.role == 'system' and event.kind == 'text'
              and (OPEN in event.text or CLOSE in event.text)]
    if not blocks:
        return None, None, ['rules:no_supported_system_policy']
    if len(blocks) != 1:
        return None, None, ['rules:ambiguous_policy_blocks']
    event = blocks[0]
    if event.text.count(OPEN) != 1 or event.text.count(CLOSE) != 1:
        return None, None, ['rules:ambiguous_or_incomplete_policy_block']
    begin, end = event.text.index(OPEN), event.text.index(CLOSE)
    if end < begin or len(event.text[begin:end]) > MAX_BYTES or not _source_valid(event.source) or event.source.document != 'prompt':
        return None, None, ['rules:invalid_policy_source_or_bounds']
    source = Source('prompt', event.source.start + begin, event.source.start + end + len(CLOSE))
    if source.end > event.source.end:
        return None, None, ['rules:invalid_policy_source_or_bounds']
    policy, valid = decode_json(event.text[begin + len(OPEN):end])
    if not valid or not _bounded_json(policy) or not _keys(policy, ('version', 'rules'), ('context',)) or type(policy['version']) is not int or policy['version'] != 1:
        return None, None, ['rules:unsupported_or_invalid_policy']
    if not isinstance(policy.get('context', {}), dict) or not isinstance(policy['rules'], list) or not 0 < len(policy['rules']) <= MAX_RULES:
        return None, None, ['rules:unsupported_or_invalid_policy']
    seen, budget = set(), [MAX_NODES]
    for rule in policy['rules']:
        if (not _keys(rule, ('id', 'tool', 'require'), ('when', 'except'))
                or not isinstance(rule['id'], str) or not rule['id'] or rule['id'] in seen
                or not isinstance(rule['tool'], str) or not rule['tool']
                or not all(_validate_expr(rule[key], budget) for key in ('require', 'when', 'except') if key in rule)):
            return None, None, ['rules:unsupported_or_invalid_policy']
        seen.add(rule['id'])
    return policy, source, []


def _read_path(value, path):
    for key in path:
        if isinstance(value, dict) and isinstance(key, str) and key in value:
            value = value[key]
        elif isinstance(value, list) and type(key) is int and key < len(value):
            value = value[key]
        else:
            return UNKNOWN
    return value


def _unique_sources(values):
    return list(dict.fromkeys(source for value in values for source in value.sources))


class _Evaluator:
    def __init__(self, history, call, graph, context, policy_source, prior_calls):
        self.history, self.call, self.graph = history, call, graph
        self.context, self.policy_source, self.prior_calls = context, policy_source, prior_calls

    def operand(self, expression):
        op, value = next(iter(expression.items()))
        if op == 'literal':
            return Value(value, [self.policy_source])
        if op == 'context':
            return Value(_read_path(self.context, value), [self.policy_source])
        if op == 'arg':
            return Value(_read_path(self.call.value, value), [self.call.source])
        return self.fact(value)

    def fact(self, selector):
        # Calls are intentions. Without an explicit supported transition model,
        # their effects and ordering cannot refresh or preserve a prior snapshot.
        if self.prior_calls:
            return Value()
        bindings = {key: self.operand(value) for key, value in selector['entity'].items()}
        if any(v.value is UNKNOWN or type(v.value) not in (str, int) for v in bindings.values()):
            return Value()

        def scope_matches(fact):
            scope = {e.field: e.value for e in fact.entities}
            return all(key in scope and value_key(scope[key]) == value_key(value.value) for key, value in bindings.items())

        scoped = [f for f in self.graph.facts if f.tool == selector['tool'] and f.role == selector['role'] and scope_matches(f)]
        matches = [f for f in scoped if f.field == selector['field'] and
                   ('container' not in selector or [k for k in f.path[:-1] if isinstance(k, str)] == selector['container'])]
        if not matches or any(not f.versioned for f in matches):
            return Value()
        keys = {lineage(f) for f in matches}
        if len(keys) != 1:
            return Value()
        latest_event = max(f.event for f in matches)
        latest = [f for f in matches if f.event == latest_event]
        # A newer partial observation does not establish that an omitted value
        # persists. Different scopes/containers are not one update timeline.
        selected_key = next(iter(keys))
        if any(f.event > latest_event and f.versioned and lineage(f) is not None
               and lineage(f)[:3] == selected_key[:3]
               for f in scoped):
            return Value()
        if any(e.kind == 'result' and e.name == selector['tool'] and e.role == selector['role']
               and not e.json_valid for e in self.history[latest_event + 1:]):
            return Value()
        if len({value_key(f.value) for f in latest}) != 1:
            return Value()
        for fact in latest:
            if not 0 <= fact.event < len(self.history) or not fact.sources or not all(_source_valid(s) for s in fact.sources):
                return Value()
            event = self.history[fact.event]
            observed = _read_path(event.value, fact.path)
            if (event.kind != 'result' or not event.json_valid or event.name != fact.tool
                    or event.role != fact.role or event.source not in fact.sources
                    or observed is UNKNOWN or value_key(observed) != value_key(fact.value)):
                return Value()
        return Value(latest[0].value, _unique_sources(list(bindings.values())) +
                     list(dict.fromkeys(s for f in latest for s in f.sources)))

    def expression(self, expression):
        if type(expression) is bool:
            return Value(expression, [self.policy_source])
        op, payload = next(iter(expression.items()))
        if op == 'not':
            child = self.expression(payload)
            return Value(UNKNOWN if child.value is UNKNOWN else not child.value, child.sources)
        if op in ('all', 'any'):
            children = [self.expression(child) for child in payload]
            decisive = False if op == 'all' else True
            decisive_children = [v for v in children if v.value is decisive]
            if decisive_children:
                return Value(decisive, _unique_sources(decisive_children))
            return Value(UNKNOWN if any(v.value is UNKNOWN for v in children) else not decisive, _unique_sources(children))
        left, right = [self.operand(operand) for operand in payload]
        sources = _unique_sources([left, right])
        a, b = left.value, right.value
        if a is UNKNOWN or b is UNKNOWN:
            return Value(UNKNOWN, sources)
        if op in ('eq', 'ne'):
            equal = value_key(a) == value_key(b)
            return Value(equal if op == 'eq' else not equal, sources)
        if op in ('in', 'not_in'):
            if not isinstance(b, list):
                return Value(UNKNOWN, sources)
            found = any(value_key(a) == value_key(item) for item in b)
            return Value(found if op == 'in' else not found, sources)
        if op.startswith('date_'):
            if not all(isinstance(v, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', v) for v in (a, b)):
                return Value(UNKNOWN, sources)
            try:
                a, b = date.fromisoformat(a), date.fromisoformat(b)
            except ValueError:
                return Value(UNKNOWN, sources)
            op = op[5:]
        elif type(a) is not type(b) or type(a) not in (str, int, float):
            return Value(UNKNOWN, sources)
        result = {'lt': lambda: a < b, 'le': lambda: a <= b, 'gt': lambda: a > b, 'ge': lambda: a >= b}[op]()
        return Value(result, sources)


def check_rules(history: list[Event], candidate: list[Event], graph: EvidenceGraph) -> tuple[list[Finding], list[str]]:
    """Return proven declarative precondition violations and unresolved issues.

    A passing rule establishes only that rule's predicate, never global safety.
    Candidate tool results and model-authored policy blocks are not evidence.
    """
    policy, policy_source, issues = _parse_policy(history)
    if policy is None:
        return [], issues
    findings, prior_calls = [], False
    for index, call in enumerate(candidate):
        if call.kind != 'call' or call.role != 'assistant':
            continue
        applicable = [rule for rule in policy['rules'] if rule['tool'] == call.name]
        if not applicable:
            issues.append(f'rules:uncovered_call:{index}')
        for rule in applicable:
            label = f"{rule['id']}:{index}"
            if not call.json_valid or not isinstance(call.value, dict) or not _source_valid(call.source):
                issues.append(f'rules:invalid_call_or_source:{label}')
                continue
            evaluator = _Evaluator(history, call, graph, policy.get('context', {}), policy_source, prior_calls)
            when = evaluator.expression(rule.get('when', True))
            exception = evaluator.expression(rule.get('except', False))
            if when.value is False or exception.value is True:
                continue
            if when.value is UNKNOWN or exception.value is UNKNOWN:
                issues.append(f'rules:unknown_applicability:{label}')
                continue
            requirement = evaluator.expression(rule['require'])
            if requirement.value is UNKNOWN:
                issues.append(f'rules:unknown_precondition:{label}')
            elif requirement.value is False:
                sources = list(dict.fromkeys([policy_source, call.source] + _unique_sources([when, exception, requirement])))
                findings.append(Finding('rule_precondition_violation',
                                        f"Call to {call.name!r} violates explicit rule {rule['id']!r}.", sources))
        prior_calls = True
    return findings, sorted(set(issues))
