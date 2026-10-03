"""Construction-based tests; a repaired rule is never whole-response NO_ERROR.

No labels or case/domain names enter generation. Expectations are contracts
conditional on the compiled rule, separate from independent semantic gold.
Unproven ID formats, text paraphrases and causal independence are not invented.
"""
from copy import deepcopy
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import uuid

from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.id_contract import native_target_inventory
from guardian_truth.policy_table.schema import Rule, Condition
from guardian_truth.policy_table.segment import policy_hash, enum_catalog
from guardian_truth.policy_table.evaluate import resolve, same, state_components, state_binding_arguments, condition_value, evaluate_rule

SEED = 20261003


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def replace_body(store, sid, value, *, indent=None, reverse=False):
    source = store.sources[sid]
    event = (store.history_events if source['document'] == 'prompt' else store.target_events)[source['event']]
    if not event.json_valid: raise ValueError('cannot rewrite an unparsed event')
    if reverse and isinstance(value, dict): value = dict(reversed(list(value.items())))
    replacement = json.dumps(value, ensure_ascii=False, indent=indent, allow_nan=False)
    segment = store.text(sid)
    offset = segment.rfind(event.text)
    if offset < 0 or segment[offset:].strip() != event.text: raise ValueError('event body/source mismatch')
    start = source['start'] + offset
    row = dict(store.raw)
    raw = row[source['document']]
    row[source['document']] = raw[:start] + replacement + raw[start + len(event.text):]
    return row


def locations(value, parts, anchors, inherited=None, coordinates=()):
    inherited = dict(inherited or {})
    if isinstance(value, dict): inherited.update(value)
    if not parts:
        overlap = set(anchors) & set(inherited)
        if overlap and not all(same(anchors[k], inherited[k]) for k in overlap): return []
        return [(coordinates, value)]
    head, *tail = parts
    if head == '*' and isinstance(value, list):
        return [entry for index, child in enumerate(value)
            for entry in locations(child, tail, anchors, inherited, coordinates + (index,))]
    if isinstance(value, dict) and head in value:
        return locations(value[head], tail, anchors, inherited, coordinates + (head,))
    return []


def set_at(value, coordinates, replacement):
    result = deepcopy(value)
    if not coordinates: return replacement
    cursor = result
    for part in coordinates[:-1]: cursor = cursor[part]
    cursor[coordinates[-1]] = replacement
    return result


def other(value):
    if type(value) is bool: return not value
    if type(value) in (int, float): return value + 1
    if isinstance(value, str): return value + '__mutation_' + str(SEED)
    return None


def assignments(condition, store, target):
    """Return (desired truth, value) pairs from operator semantics, not labels."""
    if condition.rhs is None: return []  # do not invent nullable output schemas
    rhs = condition.rhs.value if condition.rhs.kind == 'LITERAL' else resolve(store, condition.rhs.path, target).value
    if condition.rhs.kind == 'PATH' and resolve(store, condition.rhs.path, target).status != 'RESOLVED': return []
    op = condition.op
    if op in ('==', '!=') and rhs is not None:
        return [(op == '==', rhs), (op != '==', other(rhs))]
    if op in ('<', '<=', '>', '>=') and type(rhs) in (int, float):
        true = rhs - 1 if op == '<' else rhs + 1 if op == '>' else rhs
        false = rhs + 1 if op in ('<', '<=') else rhs - 1
        return [(True, true), (False, false)]
    if op in ('in', 'not_in') and isinstance(rhs, list) and rhs and rhs[0] is not None:
        outside = other(rhs[0])
        for _ in range(len(rhs) + 1):
            if not any(same(outside, item) for item in rhs): break
            outside = other(outside)
        return [(op == 'in', rhs[0]), (op != 'in', outside)]
    return []


def mutate_condition(store, condition, target, binding_arguments=None):
    effective = condition
    inverse = {'==': '==', '!=': '!=', '<': '>', '<=': '>=', '>': '<', '>=': '<=', 'before': 'after', 'after': 'before'}
    if not condition.lhs.startswith('state.'):
        if condition.rhs is None or condition.rhs.kind != 'PATH' or not condition.rhs.path.startswith('state.') or condition.op not in inverse: return []
        effective = Condition(lhs=condition.rhs.path, op=inverse[condition.op], rhs={'kind': 'PATH', 'path': condition.lhs})
    resolved = resolve(store, effective.lhs, target, binding_arguments=binding_arguments)
    if resolved.status != 'RESOLVED' or len(resolved.source_ids) != 1: return []
    sid = resolved.source_ids[0]
    event = store.history_events[store.sources[sid]['event']]
    components = state_components(effective.lhs)
    if components is None: return []
    _, parts = components
    matches = locations(event.value, parts, target.get('arguments') or {} if binding_arguments is None else binding_arguments)
    if len(matches) != 1: return []
    coordinates, current = matches[0]
    results = []
    for desired, replacement in assignments(effective, store, target):
        if type(replacement) is not type(current): continue
        row = replace_body(store, sid, set_at(event.value, coordinates, replacement))
        mutated = SourceStore(row)
        actual = condition_value(mutated, condition, target, binding_arguments=binding_arguments)[0]
        if actual != ('TRUE' if desired else 'FALSE'): continue
        results.append((desired, row, {'source_id_before': sid, 'path': effective.lhs,
            'coordinates': list(coordinates), 'old_value': current, 'new_value': replacement}))
    return results


def rule_pairs(store, table):
    for item in table.rules:
        if item['status'] != 'DECISIVE': continue
        rule = Rule.model_validate(item['rule'])
        if rule.trigger.kind != 'TOOL_CALL': continue  # no guessed speech acts
        for target in native_target_inventory(store):
            if not store.sources[target['source_id']]['json_valid'] or not isinstance(target.get('arguments'), dict): continue
            if target['tool'] != rule.trigger.tool: continue
            binding_arguments = state_binding_arguments(rule, target)
            for index, condition in enumerate(rule.conditions):
                variants = []
                for truth, row, change in mutate_condition(store, condition, target, binding_arguments):
                    # All other necessary conditions must be unambiguously true.
                    amended = SourceStore(row)
                    if any(condition_value(amended, c, target, binding_arguments=binding_arguments)[0] != 'TRUE'
                           for j, c in enumerate(rule.conditions) if j != index): continue
                    result = evaluate_rule(amended, rule, target)
                    expected = ('NO_FINDING' if truth else 'ERROR') if rule.modality == 'REQUIRES' else ('ERROR' if truth else 'NO_FINDING')
                    if rule.modality not in ('REQUIRES', 'FORBIDS') or result['status'] != expected: continue
                    variants.append({'row': row, 'kind': 'STATE_CONDITION', 'rule_id': rule.rule_id,
                        'target_source_id': target['source_id'], 'expected_rule_status': expected, 'change': change})
                if {v['expected_rule_status'] for v in variants} == {'ERROR', 'NO_FINDING'}:
                    yield variants
            # Exception toggles only qualify when all necessary facts prove a
            # violation in the FALSE branch. Other unresolved exceptions reject it.
            for group_index, group in enumerate(rule.exceptions):
                for index, condition in enumerate(group):
                    variants = []
                    for truth, row, change in mutate_condition(store, condition, target, binding_arguments):
                        amended = SourceStore(row)
                        if any(condition_value(amended, c, target, binding_arguments=binding_arguments)[0] != 'TRUE'
                               for j, c in enumerate(group) if j != index): continue
                        expected = 'NO_FINDING' if truth else 'ERROR'
                        if evaluate_rule(amended, rule, target)['status'] != expected: continue
                        variants.append({'row': row, 'kind': 'STATE_CONDITION', 'subkind': 'STATE_EXCEPTION', 'rule_id': rule.rule_id,
                            'target_source_id': target['source_id'], 'expected_rule_status': expected,
                            'change': {**change, 'exception_group': group_index}})
                    if {v['expected_rule_status'] for v in variants} == {'ERROR', 'NO_FINDING'}:
                        yield variants


def rendering_controls(store):
    # JSON key order and whitespace leave typed arguments, values, chronology
    # and all original policy/text unchanged. No paraphrase or guessed reordering.
    for sid, source in store.sources.items():
        if source['kind'] not in ('call', 'result'): continue
        event = (store.history_events if source['document'] == 'prompt' else store.target_events)[source['event']]
        if not event.json_valid or not isinstance(event.value, dict) or not event.value: continue
        row = replace_body(store, sid, event.value, indent=2, reverse=True)
        changed = SourceStore(row)
        before = [(e.role, e.kind, e.name, e.value if e.json_valid else e.text) for e in store.history_events + store.target_events]
        after = [(e.role, e.kind, e.name, e.value if e.json_valid else e.text) for e in changed.history_events + changed.target_events]
        if before != after: raise ValueError('rendering changed parsed conversation')
        if row == store.raw: continue
        yield {'row': row, 'kind': 'NEGATIVE_CONTROL', 'subkind': 'NATIVE_RENDER' if source['document'] == 'response' else 'SOURCE_RENDER',
            'expected_relation': 'SAME_BASE_DECISION', 'change': {'source_id_before': sid, 'construction': 'SAME_TYPED_NATIVE_EVENTS'}}


def identifier_mutations(store):
    catalog = enum_catalog([store])
    for target in native_target_inventory(store):
        if not store.sources[target['source_id']]['json_valid'] or not isinstance(target.get('arguments'), dict): continue
        fields = catalog['tools'].get(target['tool'], {}).get('arguments', {})
        for name, value in target['arguments'].items():
            field = fields.get(name) or {}
            # UUID is an explicit standard format, never an argument-name guess.
            if field.get('type') != 'string' or field.get('format') != 'uuid': continue
            try: uuid.UUID(value)
            except (ValueError, TypeError, AttributeError): continue
            replacement = str(uuid.uuid5(uuid.NAMESPACE_OID, encoded([SEED, store.source_sha256, target['source_id'], name])))
            if replacement in store.raw['prompt'] or replacement in store.raw['response']: continue
            arguments = {**target['arguments'], name: replacement}
            yield {'row': replace_body(store, target['source_id'], arguments), 'kind': 'ARG_IDENTIFIER',
                'target_source_id': target['source_id'], 'expected_audit_status': 'ERROR',
                'whole_case_label': 1, 'whole_case_label_basis': 'A3_EXPLICIT_IDENTIFIER_GROUNDING_CONTRACT',
                'change': {'path': 'args.' + name, 'old_value': value, 'new_value': replacement, 'declared_format': 'uuid'}}


def known_answer_mutations(store, frames):
    for frame in frames:
        if frame.get('status') != 'SOURCE_VALIDATED_REQUEST_FRAME': continue
        if frame.get('source_sha256') != store.source_sha256: continue
        sid = frame.get('target_source_id'); source = store.sources.get(sid)
        if not source or source['document'] != 'response' or source['kind'] != 'text' or source['role'] != 'assistant': continue
        if frame.get('act') not in ('ASK_CLARIFY', 'ASK_USER_ACTION'): continue
        if not isinstance(frame.get('asked_field'), str) or 'asked_value' not in frame: continue
        if frame['asked_value'] is None or frame['asked_value'] == '': continue
        users = [s for s in store.sources.values() if s['document'] == 'prompt' and s['role'] == 'user' and s['kind'] == 'text']
        if not users: continue
        user = users[-1]
        addition = encoded({**frame.get('entity_arguments', {}), frame['asked_field']: frame['asked_value']})
        raw = store.raw['prompt']
        row = {**store.raw, 'prompt': raw[:user['end']] + '\n' + addition + raw[user['end']:]}
        yield {'row': row, 'kind': 'KNOWN_ANSWER', 'target_source_id': sid,
            'expected_audit_status': 'ERROR', 'whole_case_label': 1,
            'whole_case_label_basis': 'CONDITIONAL_ON_SOURCE_VALIDATED_REQUEST_FRAME_SEMANTICS',
            'change': {'latest_user_source_id_before': user['id'], 'added_typed_answer': addition,
                'request_frame_sha256': hashlib.sha256(encoded(frame).encode()).hexdigest()}}


def generate(rows, tables, *, question_frames=None, seed=SEED, per_kind_per_policy=8):
    rng = random.Random(seed)
    pools, unavailable = {}, []
    for row in rows:
        store = SourceStore(row); key = policy_hash(store)
        table = tables.get(key)
        if table is None: unavailable.append({'case_id': row.get('id'), 'reason': 'policy_not_compiled'})
        candidates = [(candidate,) for candidate in rendering_controls(store)]
        candidates += [(candidate,) for candidate in identifier_mutations(store)]
        candidates += [(candidate,) for candidate in known_answer_mutations(store, (question_frames or {}).get(row.get('id'), []))]
        if table is not None: candidates += list(rule_pairs(store, table))
        for pair in candidates:
            for candidate in pair:
                candidate.update(base_case_id=row.get('id'), base_source_sha256=store.source_sha256,
                    policy_sha256=key, pair_group=hashlib.sha256(encoded([store.source_sha256, candidate.get('rule_id'), candidate.get('target_source_id'),
                        candidate['change'].get('path'), candidate['change'].get('exception_group'), candidate['kind']]).encode()).hexdigest())
            pool = pools.setdefault((key, pair[0]['kind']), [])
            pool.append(pair)
    selected, expectations, seen = [], [], set()
    for (key, kind), pairs in sorted(pools.items()):
        rng.shuffle(pairs)
        accepted = 0
        for pair in pairs:
            values = [(c, SourceStore(c['row']).source_sha256) for c in pair]
            if any((key, kind, digest) in seen for _, digest in values): continue
            if accepted + len(values) > per_kind_per_policy: continue
            for candidate, digest in values:
                seen.add((key, kind, digest)); accepted += 1
                mid = 'mutation_' + hashlib.sha256(encoded([key, kind, candidate['base_case_id'], digest, candidate.get('rule_id')]).encode()).hexdigest()[:20]
                selected.append({'id': mid, **candidate['row']})
                expectation = {k: v for k, v in candidate.items() if k != 'row'}
                expectation.update(id=mid, mutated_source_sha256=digest,
                    whole_case_label=candidate.get('whole_case_label'),
                    expectation_scope='COMPILED_RULE_CONTRACT' if 'rule_id' in candidate else
                        'SEMANTIC_INVARIANCE' if candidate['kind'] == 'NEGATIVE_CONTROL' else 'A3_FACT_CONTRACT')
                if candidate.get('expected_rule_status') == 'ERROR':
                    expectation['whole_case_label'] = 1
                    expectation['whole_case_label_basis'] = 'CONDITIONAL_ON_COMPILED_RULE_BEING_FAITHFUL_TO_SOURCE_POLICY'
                expectations.append(expectation)
            if accepted == per_kind_per_policy: break
    counts = Counter((e['policy_sha256'], e['kind']) for e in expectations)
    keys = sorted({policy_hash(SourceStore(row)) for row in rows})
    expected_kinds = ['ARG_IDENTIFIER', 'STATE_CONDITION', 'KNOWN_ANSWER', 'NEGATIVE_CONTROL']
    gaps = [{'policy_sha256': key, 'kind': kind, 'available': counts[(key, kind)],
        'requested': per_kind_per_policy} for key in keys for kind in expected_kinds if counts[(key, kind)] != per_kind_per_policy]
    limitations = [
        'No ID mutation without an explicit identifier format/constraint in the input schema.',
        'No already-known-question mutation without a validated asked-value/entity frame.',
        'No text paraphrase or event shuffle without a construction proof of semantic/causal invariance.',
        'A rule-local NO_FINDING is never whole-response NO_ERROR.',
        'Three compilation votes are not independent semantic gold.']
    summary = {'status': 'READY_CONTRACT_SUITE_NOT_INDEPENDENT_SEMANTIC_GOLD' if not unavailable and not gaps and len(selected) >= 120 else 'PREPARED_INCOMPLETE_NOT_FULL_BENCHMARK',
        'seed': seed, 'mutants': len(selected), 'policies': len(keys), 'per_kind_per_policy': per_kind_per_policy,
        'counts': [{'policy_sha256': key, 'kind': kind, 'count': count} for (key, kind), count in sorted(counts.items())],
        'eligibility_gaps': gaps, 'unavailable': unavailable, 'limitations': limitations, 'api_calls': 0}
    return selected, expectations, summary


def save(directory, inputs, expectations, summary):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    for filename, values in (('inputs.jsonl', inputs), ('expectations.jsonl', expectations)):
        path = directory / filename
        if path.exists(): raise FileExistsError('never overwrite a frozen mutation candidate')
        path.write_text(''.join(encoded(value) + '\n' for value in values), encoding='utf-8')
    summary['sha256'] = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in ('inputs.jsonl', 'expectations.jsonl')}
    (directory / 'manifest.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
