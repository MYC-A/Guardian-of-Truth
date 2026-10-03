"""Offline peer-change review: synthetic contrasts and saved pilot replies, no API/gold."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import sys
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--source-root', type=Path, required=True)
parser.add_argument('--archive', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.source_root / 'src'))
from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.id_contract import native_target_inventory
from guardian_truth.policy_table.segment import policy_hash
from guardian_truth.policy_table_v11.witness import explicit_confirmation, contains_value
from guardian_truth.policy_table_v11.evaluate import evaluate_atom
from guardian_truth.policy_table_v11.schema import Atom
from guardian_truth.policy_table_v11.compile import admit, canonical


def source(extra='', response=None):
    return SourceStore({'prompt': '⟦SYSTEM⟧\nBefore any modification obtain explicit confirmation for the action and amount. '
        "Any modification requires record status 'open' and the target item enabled.\n"
        '[AVAILABLE TOOLS]\n- apply_a — modify a record\n    record_id: string!\n    account_id: string\n    item_id: string\n    amount: number!\n'
        '- inspect_b — inspect records\n    record_id: string\n⟦USER⟧\nRecord X.\n' + extra,
        'response': response or '→ TOOL_CALL apply_a: {"record_id":"X","amount":2}'})


CONFIRMED = '⟦ASSISTANT⟧\nConfirm applying amount 2 to X?\n⟦USER⟧\nYes\n'
CALL = '→ TOOL_CALL apply_a: {"record_id":"X","amount":2}'
cases = []
def confirmation(name, extra, response, expected, justification):
    s = source(extra, response)
    value = explicit_confirmation(s, native_target_inventory(s)[0])
    actual = (value.status, value.value)
    cases.append({'id': name, 'expected': list(expected), 'actual': list(actual),
        'pass': actual == expected, 'reason': value.reason, 'justification': justification,
        'fixture': s.raw})


confirmation('restatement_keeps_yes', CONFIRMED, '⟦ASSISTANT⟧\nI will now apply amount 2 to X.\n' + CALL,
    ('RESOLVED', True), 'Restating the exact confirmed action does not erase consent.')
confirmation('courtesy_no_problem', '⟦ASSISTANT⟧\nConfirm applying amount 2 to X?\n⟦USER⟧\nNo problem, go ahead\n', None,
    ('RESOLVED', True), 'No problem is not a refusal.')
confirmation('courtesy_ru', '⟦ASSISTANT⟧\nПодтвердите действие для X?\n⟦USER⟧\nНет возражений, подтверждаю\n', None,
    ('RESOLVED', True), 'Нет возражений is not a refusal.')
confirmation('joined_ID_right', '⟦ASSISTANT⟧\nConfirm applying amount 2 to X-1?\n⟦USER⟧\nYes\n', None,
    ('UNRESOLVED', None), 'X-1 is another identifier, not X.')
confirmation('action_request_not_refusal', '⟦ASSISTANT⟧\nShall I cancel X?\n⟦USER⟧\nCancel it\n', None,
    ('UNRESOLVED', None), 'Cancel it requests an action; it is not a refusal. Actual target action differs.')
confirmation('no_reply_after_new_question', '⟦ASSISTANT⟧\nRecord X has amount 1. What next?\n⟦USER⟧\nChange it to 2.\n'
    '⟦ASSISTANT⟧\nDo you confirm applying amount 2 to X?\n', None,
    ('RESOLVED', False), 'A fresh explicit confirmation request received no reply.')
confirmation('explicit_no', '⟦ASSISTANT⟧\nConfirm applying amount 2 to X?\n⟦USER⟧\nNo, thanks\n', None,
    ('RESOLVED', False), 'Clear explicit refusal.')
confirmation('wrong_question_affirmed', '⟦ASSISTANT⟧\nIs record X the one you want to inspect?\n⟦USER⟧\nYes\n', None,
    ('UNRESOLVED', None), 'Yes confirms inspection identity, not modification.')
confirmation('wrong_question_refused', '⟦ASSISTANT⟧\nIs record X already closed?\n⟦USER⟧\nNo\n', None,
    ('UNRESOLVED', None), 'No denies an attribute, not permission to modify.')
confirmation('wrong_question_unanswered', '⟦ASSISTANT⟧\nIs record X already closed?\n', None,
    ('UNRESOLVED', None), 'Unanswered factual question is not proof of missing action approval.')
confirmation('changed_amount_on_same_ID', CONFIRMED, '→ TOOL_CALL apply_a: {"record_id":"X","amount":999}',
    ('UNRESOLVED', None), 'Amount 2 approval does not approve amount 999 on the same ID.')
confirmation('joined_ID_left', '⟦ASSISTANT⟧\nConfirm applying amount 2 to P.X?\n⟦USER⟧\nYes\n', None,
    ('UNRESOLVED', None), 'P.X is another identifier; the right boundary protection must be symmetric.')
confirmation('joined_ID_left_slash', '⟦ASSISTANT⟧\nConfirm applying amount 2 to group/X?\n⟦USER⟧\nYes\n', None,
    ('UNRESOLVED', None), 'group/X is not standalone X.')
confirmation('changed_amount_description_after_yes', CONFIRMED,
    '⟦ASSISTANT⟧\nI will now apply amount 999 to X.\n→ TOOL_CALL apply_a: {"record_id":"X","amount":999}',
    ('UNRESOLVED', None), 'Later narration changes the confirmed amount 2 to 999; it is not restating the same action.')


def state_case(name, extra, response, expr, expected):
    s = source(extra, response); target = native_target_inventory(s)[0]
    atom = Atom.model_validate({'modality': 'REQUIRES', 'condition': expr, 'clause_ids': ['clause_0'], 'exceptions': []})
    result = evaluate_atom(s, atom, target)
    from guardian_truth.policy_table.segment import clauses
    from guardian_truth.policy_table_v11.catalog import normalize_catalog
    policy = {'policy_sha256': policy_hash(s), 'clauses': clauses(s), 'catalog': normalize_catalog([s])}
    admission = admit({'atoms': [atom.model_dump(exclude_none=True)]}, policy, {'kind': 'TOOL_CALL', 'tool': target['tool']})
    cases.append({'id': name, 'expected': expected, 'actual': result['value'], 'pass': result['value'] == expected,
        'result': result, 'admitted': bool(admission['atoms']), 'admission_reasons': admission['discarded'], 'fixture': s.raw})

def compare(path, value, **kw):
    return {'kind': 'COMPARE', 'lhs': path, 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': value}, **kw}

READ = '⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: {"record_id":"X","status":"open"}\n'
state_case('scalar_secondary_ID_no_longer_blocks_read', READ,
    '→ TOOL_CALL apply_a: {"record_id":"X","account_id":"P","amount":2}', compare('state.inspect_b./status', 'open'), 'TRUE')
state_case('scalar_other_record_remains_unknown', READ,
    '→ TOOL_CALL apply_a: {"record_id":"Y","account_id":"P","amount":2}', compare('state.inspect_b./status', 'open'), 'UNRESOLVED')
state_case('collection_TARGET_other_parent_leaks', '⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {}\n← TOOL_RESPONSE inspect_b: '
    '{"record_id":"Y","items":{"I":{"item_id":"I","enabled":false}}}\n',
    '→ TOOL_CALL apply_a: {"record_id":"X","item_id":"I","amount":2}',
    compare('state.inspect_b./items/{key}/enabled', True, quantifier='TARGET', binding={'argument': 'item_id', 'record_field': '$key'}),
    'UNRESOLVED')


root = args.source_root / 'outputs/searh_23/v11/preparation'
pilot = 'da31c80eff47a6cda99c1029c08d18f1a719616fdfcfd836b60ca33ee4ce806a'
policy = json.loads((root / (pilot + '.json')).read_text(encoding='utf-8'))
by_model, discarded, envelope_failures, transport_failures = defaultdict(set), defaultdict(Counter), defaultdict(list), defaultdict(list)
responses = Counter(); valid = Counter()
with zipfile.ZipFile(args.archive) as archive:
    for name in archive.namelist():
        if not name.startswith('replies/'): continue
        record = json.loads(archive.read(name)); model = record['config']['model']; responses[model] += 1
        new = admit(record['response'], policy, record['trigger']); valid[model] += new['valid_response']
        for a in new['atoms']: by_model[model].add(canonical(pilot, record['trigger'], Atom.model_validate(a)))
        for rejection in new['discarded']: discarded[model][rejection['reason']] += 1
        if not new['valid_response']: envelope_failures[model].append({'tool': record['trigger']['tool'],
            'response_type': type(record['response']).__name__, 'response_keys': list(record['response']) if isinstance(record['response'], dict) else None,
            'transport_status': record['reply']['status']})
        if record['reply']['status'] != 'OK': transport_failures[model].append({'tool': record['trigger']['tool'], 'reason': record['reply'].get('reason')})
models = sorted(responses)
overlap = [{'a': a, 'b': b, 'shared': len(by_model[a] & by_model[b])} for i, a in enumerate(models) for b in models[i + 1:]]
sys.path.insert(0, str(args.source_root / 'experiments/searh_23/v11'))
import measure
metric_probes = {}
if hasattr(measure, 'measure_mutations'):
    metric_probes['empty_table_mutant_summary'] = measure.measure_mutations({})['summary']
    metric_probes['frozen_positive_mutants'] = sum(m['status'] == 'POSITIVE' for m in
        json.loads(measure.MUTATIONS.read_text(encoding='utf-8'))['mutants'])
    expected = Atom.model_validate({'modality': 'REQUIRES', 'condition': compare('state.inspect_b./status', 'open'),
        'clause_ids': ['clause_0'], 'exceptions': []})
    wrong = Atom.model_validate({'modality': 'REQUIRES', 'condition': compare('state.inspect_b./status', 'blocked'),
        'clause_ids': ['clause_0'], 'exceptions': []})
    s = source(READ); from guardian_truth.policy_table.segment import clauses
    from guardian_truth.policy_table_v11.catalog import normalize_catalog
    p = {'policy_sha256': policy_hash(s), 'clauses': clauses(s), 'catalog': normalize_catalog([s])}
    requirement_spec = {'id': 'fixture', 'atom': expected.model_dump(exclude_none=True)}
    metric_probes['wrong_constant_matches_mechanism'] = measure.mechanism(wrong, requirement_spec, p, 'apply_a')
result = {'source_root': str(args.source_root), 'api_calls_for_review': 0, 'gold_opened': False,
    'synthetic': cases, 'synthetic_passed': sum(c['pass'] for c in cases), 'synthetic_total': len(cases),
    'saved_pilot_re_admission': [{'model': m, 'responses': responses[m], 'valid': valid[m], 'atoms': len(by_model[m]),
        'discarded': dict(discarded[m]), 'envelope_failures': envelope_failures[m], 'transport_failures': transport_failures[m]} for m in models],
    'pairwise_overlap': overlap, 'metric_probes': metric_probes,
    'limitation': 'Only saved two-model pilot replies. No new inference or public46 quality measurement.'}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in result.items() if k != 'synthetic'}, ensure_ascii=False))
