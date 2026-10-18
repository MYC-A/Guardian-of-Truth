"""V3 whole-turn schema and shared production-render path. No label inference."""
import hashlib
import json

from guardian_truth.judge.prompting import build_prompt, render

FIELDS = {'id', 'source', 'source_revision', 'domain', 'family', 'scenario_id',
          'group_id', 'pair_id', 'policy', 'tools', 'history', 'target_turn', 'label',
          'violation_type', 'governing_rule', 'evidence_msg_ids', 'label_origin',
          'is_hard_negative', 'n_tokens', 'license'}
TYPES = {'rule_scope', 'eligibility', 'consent', 'authorization', 'tool_args',
         'unsupported_fact', 'completion_without_result', 'wrong_transfer', 'none'}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def turn_text(turn):
    content = turn.get('content') or ''
    if not isinstance(content, str):
        content = canonical(content)
    parts = [content] if content else []
    for call in turn.get('tool_calls', []):
        function = call.get('function', call)
        arguments = function['arguments']
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        parts.append('\t\u2192 TOOL_CALL ' + function['name'] + ': ' + canonical(arguments))
    if turn.get('role') == 'tool':
        assert turn.get('name'), 'UNBOUND_TOOL_RESULT'
        return '\t\u2190 TOOL_RESPONSE ' + turn['name'] + ': ' + content
    return '\n'.join(parts)


def judge_input(row):
    """Allowlist source content only; exclude label, rationale, type and provenance."""
    system = '<policy>\n' + row['policy'] + '\n</policy>\n[AVAILABLE TOOLS]\n' + canonical(row['tools'])
    prompt = '\u27e6SYSTEM\u27e7\n' + system + '\n'
    for message in row['history']:
        role = 'ASSISTANT' if message['role'] == 'tool' else message['role'].upper()
        prompt += '\u27e6' + role + '\u27e7\n' + turn_text(message) + '\n'
    return dict(id=row['id'], prompt=prompt, response=turn_text(row['target_turn']), hints=[])


def training_text(tok, row, cap=32768):
    request = judge_input(row)
    plain = render(tok, request['prompt'], request['response'], [])
    production, count, trimmed, policy_trimmed = build_prompt(tok, request, cap)
    if trimmed or policy_trimmed or production != plain or count > cap:
        raise ValueError('OVER_CAP_NO_SILENT_TRIMMING')
    return plain, count


def validate(row):
    assert FIELDS <= row.keys(), FIELDS - row.keys()
    assert row['label'] in (0, 1) and row['violation_type'] in TYPES
    assert (row['violation_type'] == 'none') == (row['label'] == 0)
    assert row['target_turn']['role'] == 'assistant'
    assert row['label_origin'] in ('simulator', 'perturbation', 'upstream', 'human')
    assert row['governing_rule'] in row['policy']
    assert row['is_hard_negative'] in (False, True)
    assert not row['is_hard_negative'] or row['label'] == 0
    ids = [m['id'] for m in row['history']]
    assert len(ids) == len(set(ids)) and set(row['evidence_msg_ids']) <= set(ids)
    assert row['group_id'] and row['scenario_id'] and len(row['source_revision']) == 40
    return row


def pair_hash(row):
    r = judge_input(row)
    return hashlib.sha256((r['prompt'] + '\0' + r['response']).encode('utf8', 'surrogatepass')).hexdigest()
