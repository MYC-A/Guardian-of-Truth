"""Verify atomic slots, never issue a clean verdict or trust agent rationale."""
from decimal import Decimal
import json
import re
import unicodedata

from guardian_truth.parsing import parse_catalog, unique_object, reject_constant, finite_float
from guardian_truth.policy_table.segment import clauses, enum_catalog
from guardian_truth.policy_table.evaluate import same, select
from guardian_truth.source_search.calculations import literals, calculate, NUMBER_LITERAL
from guardian_truth.source_search.id_contract import native_target_inventory
from guardian_truth.source_search.move_scope import input_packet
from .schema import Audit


INSTRUCTION = '''In addition to the unchanged official assessment, return an
action_audit object under its supplied schema. Answer atomic factual questions,
not whether a supplied accusation is true. Native calls and their arguments
are owned by code. Return exactly one argument slot for each supplied argument.
Copy references only from supplied source IDs; no quotes. NONE means no source.
COPIED cites a prior observed value, USER_STATED cites a user source; COMPUTED
requires sourced numeric operands and a permitted arithmetic operation.
Assistant explanations are claims to investigate, never independent evidence.
Classify target assistant text with the same act distinctions as the act stage:
ASK_CLARIFY/ASK_USER_ACTION request a user action, OFFER_FUTURE/OFFER_ESCALATION
are future or conditional, ASSERT_DONE claims completion, REFUSE is present.
Do not turn a request, check or proposed future action into an executed action.
For a question identify the requested field/value and the source already
containing it, if any. known_path is an exact JSON Pointer into that source.
Supply only entity arguments grounded in the latest user request or target;
an answer for a different entity does not answer this question. Missing,
ambiguous or outdated observations are not proof. A mere occurrence of a word
or number does not establish which field or entity it belongs to.
For a refusal or transfer list source policy clauses describing available
steps and the actual earlier native attempts, or NONE. Never invent an attempt
from an assistant's claim that it followed a procedure. Native effects require
observations; an attempted call alone does not prove success. Do not invent
clauses, source IDs, fields, tools, new verdict categories or confidence scores.
These slots supplement the raw policy and full original dialogue; they do not
replace either. For native calls whose declared effect is routing to another
agent, use native_transfer_steps. This is an effect hypothesis on a parsed
ATTEMPT, not a fabricated text act or proof of completed transfer. No other
native call may become a text act. Policy clause IDs are for permitted_steps
only; judge evidence_ids must use registered h/t/q source IDs. Keep the original
assessment envelope and append action_audit INSIDE assessment. Technical audit
failure does not invalidate a valid judge vote.'''


def instruction():
    return INSTRUCTION + '\nACTION_AUDIT_SCHEMA: ' + json.dumps(Audit.model_json_schema(), ensure_ascii=False)


def input_context(store):
    packet = input_packet(store)
    return {'native_arguments': native_target_inventory(store), 'text_segments': packet['text_segments'],
        'latest_user': packet['latest_user'], 'argument_catalog': enum_catalog([store])['tools'],
        'policy_clauses': [{'id': c['id'], 'text': c['text']} for c in clauses(store)],
        'fact_sources': [sid for sid, s in store.sources.items() if fact_source(store, sid)]}


def fact_source(store, sid):
    s = store.sources.get(sid)
    # The parser's result.role is the requestor, not the tool's speaker.
    # kind=result identifies observations even with an assistant requestor.
    return bool(s and s['document'] == 'prompt' and (s['role'] == 'user' or s['kind'] == 'result'))


def occurs(value, text):
    if value is None: return False
    if type(value) in (int, float):
        return any(Decimal(m[0].replace(',', '')) == Decimal(str(value)) for m in NUMBER_LITERAL.finditer(text))
    if isinstance(value, str):
        value = ' '.join(unicodedata.normalize('NFC', value).split())
        text = ' '.join(unicodedata.normalize('NFC', text).split())
        return bool(value and re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', text))
    if isinstance(value, bool): return bool(re.search(r'(?<!\w)' + str(value).lower() + r'(?!\w)', text.lower()))
    return False


def values(value):
    yield value
    if isinstance(value, dict):
        for child in value.values(): yield from values(child)
    elif isinstance(value, list):
        for child in value: yield from values(child)


def source_contains(store, sid, value):
    if not fact_source(store, sid): return False
    s = store.sources[sid]; event = store.history_events[s['event']]
    if event.json_valid and any(same(value, v) for v in values(event.value)): return True
    return occurs(value, store.text(sid))


def compute(store, item, expected):
    references = []
    for operand in item.operands:
        if not fact_source(store, operand.source_id): return {'status': 'UNKNOWN', 'reason': 'operand_has_no_independent_source'}
        matches = [v for v in literals(store, operand.source_id, 'decimal')
            if Decimal(v['literal'].replace(',', '')) == Decimal(str(operand.value))]
        if len(matches) != 1: return {'status': 'UNKNOWN', 'reason': 'ambiguous_or_missing_operand'}
        references.append({'source_id': matches[0]['source_id'], 'kind': 'decimal'})
    result = calculate(store, item.operation, references)
    if result['status'] == 'COMPUTED':
        result['matches_argument'] = type(expected) in (int, float) and Decimal(result['result']) == Decimal(str(expected))
    return result


def payloads(store, sid):
    source = store.sources[sid]; event = store.history_events[source['event']]
    if event.json_valid: return [event.value]
    text = store.text(sid)
    decoder = json.JSONDecoder(object_pairs_hook=unique_object, parse_constant=reject_constant, parse_float=finite_float)
    result, cursor = [], 0
    while cursor < len(text):
        match = re.search(r'[\[{]', text[cursor:])
        if match is None: break
        left = cursor + match.start()
        try:
            value, end = decoder.raw_decode(text, left); result.append(value); cursor = end
        except ValueError: cursor = left + 1
    return result


def question_fact(store, item):
    if item.act not in ('ASK_CLARIFY', 'ASK_USER_ACTION') or item.already_known_at == 'NONE': return None
    sid = item.already_known_at
    if not fact_source(store, sid): return {'status': 'UNRESOLVED', 'reason': 'answer_source_is_not_user_or_observation'}
    if not item.asked_field or not item.known_path or not item.known_path.startswith('/'):
        return {'status': 'UNRESOLVED', 'reason': 'missing_typed_field_binding'}
    parts = [p.replace('~1', '/').replace('~0', '~') for p in item.known_path[1:].split('/')]
    if parts[-1] != item.asked_field: return {'status': 'UNRESOLVED', 'reason': 'answer_is_another_field'}
    latest = input_packet(store)['latest_user']
    target_text = store.text(item.target_source_id)
    anchor_text = target_text + '\n' + (latest['text'] if latest else '')
    if any(v is None or not occurs(v, anchor_text) for v in item.entity_arguments.values()):
        return {'status': 'UNRESOLVED', 'reason': 'entity_not_grounded_in_current_request'}
    if not item.entity_arguments and (not latest or latest['source_id'] != sid):
        return {'status': 'UNRESOLVED', 'reason': 'past_answer_has_no_current_entity_binding'}
    selected = [pair for data in payloads(store, sid) for pair in select(data, parts, item.entity_arguments)]
    if len(selected) != 1: return {'status': 'UNRESOLVED', 'reason': 'missing_or_ambiguous_answer'}
    value, record = selected[0]
    if value is None or value == '' or not same(value, item.asked_value):
        return {'status': 'UNRESOLVED', 'reason': 'missing_or_mismatched_requested_value'}
    if not set(item.entity_arguments) <= set(record):
        return {'status': 'UNRESOLVED', 'reason': 'answer_entity_keys_not_present'}
    # A newer observation for that tool may invalidate the old answer. Without
    # a typed temporal frame, abstain instead of treating the old value as current.
    source = store.sources[sid]
    if source['kind'] == 'result' and any(e.kind == 'result' and e.name == source['tool']
            for e in store.history_events[source['event'] + 1:]):
        return {'status': 'UNRESOLVED', 'reason': 'newer_observation_not_resolved'}
    return {'status': 'VERIFIED_REQUEST_FRAME_FACT', 'source_id': sid, 'path': item.known_path,
        'value': value, 'entity_arguments': item.entity_arguments,
        'semantic_frame_proven_by_code': False}


def evaluate_audit(store, value, *, judge_findings=(), table_findings=()):
    findings, candidates, trace, issues = [], [], [], []
    try: audit = Audit.model_validate(value)
    except ValueError as exc:
        return {'status': 'INVALID_AUDIT', 'findings': [], 'candidates': [], 'trace': [], 'issues': [str(exc)], 'changes_judge_vote': False}
    calls = {c['source_id']: c for c in native_target_inventory(store)}
    expected = {(sid, arg) for sid, c in calls.items() if isinstance(c['arguments'], dict) for arg in c['arguments']}
    supplied = [(a.target_source_id, a.argument) for a in audit.arguments]
    if len(supplied) != len(set(supplied)) or set(supplied) != expected:
        return {'status': 'INVALID_AUDIT', 'findings': [], 'candidates': [], 'trace': [],
            'issues': ['native_argument_inventory_mismatch'], 'changes_judge_vote': False}
    declared = enum_catalog([store])['tools']
    for item in audit.arguments:
        target = calls[item.target_source_id]; actual = target['arguments'][item.argument]
        field = declared.get(target['tool'], {}).get('arguments', {}).get(item.argument)
        record = {'target_source_id': item.target_source_id, 'argument': item.argument, 'derivation': item.derivation}
        if item.derivation == 'COMPUTED':
            record['calculation'] = compute(store, item, actual)
        elif item.value_source_id != 'NONE':
            valid = source_contains(store, item.value_source_id, actual)
            if item.derivation == 'USER_STATED' and valid: valid = store.sources[item.value_source_id]['role'] == 'user'
            record.update(source_id=item.value_source_id, source_value_verified=valid)
        else:
            free = not field or field['type'] == 'string' and not field.get('enum') and not field.get('format')
            found = occurs(actual, store.raw['prompt']) or any(source_contains(store, sid, actual) for sid in store.sources if fact_source(store, sid))
            record.update(free_text_or_undeclared=free, found_anywhere_in_prior_context=found)
            if item.derivation == 'NONE' and actual is not None and not free and not found:
                findings.append({'type': 'ACTION_AUDIT_ARGUMENT', 'target_source_id': item.target_source_id,
                    'argument': item.argument, 'value': actual, 'status': 'CONFIRMED_BY_CODE',
                    'basis': 'ABSENT_VALUE_UNDER_DECLARED_NON_FREE_ARGUMENT_GROUNDING_CONTRACT'})
        trace.append(record)
    clause_ids = {c['id'] for c in clauses(store)}
    target_acts = []
    all_items = [(item, False) for item in audit.text_acts] + [(item, True) for item in audit.native_transfer_steps]
    for item, is_native_transfer in all_items:
        s = store.sources.get(item.target_source_id)
        expected_kind = 'call' if is_native_transfer else 'text'
        if not s or s['document'] != 'response' or s['kind'] != expected_kind or s['role'] != 'assistant':
            issues.append('text_act_not_assistant_target_text'); continue
        act = 'TRANSFER' if is_native_transfer else item.act
        if not is_native_transfer and act in ('ASK_CLARIFY', 'ASK_USER_ACTION', 'ASK_CONFIRM') and item.performer != 'USER':
            issues.append('request_performer_is_not_user'); continue
        if not is_native_transfer: target_acts.append(item.model_dump())
        known = None if is_native_transfer else question_fact(store, item)
        if known:
            trace.append({'target_source_id': item.target_source_id, 'already_known': known})
            if known['status'] == 'VERIFIED_REQUEST_FRAME_FACT':
                findings.append({'type': 'ACTION_AUDIT_KNOWN_ANSWER', 'target_source_id': item.target_source_id,
                    'source_id': item.already_known_at, 'asked_field': item.asked_field,
                    'status': 'VERIFIED_FACT_CONDITIONAL_ON_MODEL_REQUEST_FRAME', 'fact': known})
        if act not in ('REFUSE', 'TRANSFER'): continue
        for step in item.permitted_steps:
            if step.clause_id not in clause_ids or step.tool not in declared:
                issues.append('permitted_step_not_in_source_catalog'); continue
            if step.attempted_in_history != 'NONE':
                previous = store.sources.get(step.attempted_in_history)
                if not previous or previous['document'] != 'prompt' or previous['role'] != 'assistant' or previous['kind'] != 'call' or previous['tool'] != step.tool:
                    issues.append('attempted_step_not_native_history_call')
                continue
            if any(e.kind == 'call' and e.role == 'assistant' and e.name == step.tool for e in store.history_events):
                issues.append('asserted_absence_but_native_attempt_exists'); continue
            candidate = {'type': 'ACTION_AUDIT_UNTRIED_STEP', 'target_source_id': item.target_source_id,
                'clause_id': step.clause_id, 'tool': step.tool, 'status': 'CANDIDATE_NOT_DECISIVE'}
            candidates.append(candidate)
            confirmed = any(f.get('target_source_id') == item.target_source_id and
                (step.clause_id in f.get('clause_ids', []) or step.clause_id in f.get('evidence_ids', []))
                for f in list(judge_findings) + list(table_findings))
            if confirmed: findings.append({**candidate, 'status': 'CONFIRMED_BY_JUDGE_OR_TABLE'})
    return {'status': 'AUDITED_WITH_ISSUES' if issues else 'AUDITED', 'findings': findings,
        'candidates': candidates, 'trace': trace, 'issues': issues, 'target_acts': target_acts,
        'semantic_frames_proven_by_code': False, 'changes_judge_vote': False}
