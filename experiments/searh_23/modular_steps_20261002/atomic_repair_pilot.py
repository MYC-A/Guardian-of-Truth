"""Live regression for the §6 extraction/atomization repair (reviewer_repair phase).

Bank: the 6 original atomic-pilot cases (4 of which were INVALID: 3x transport
429, 1x entity-ID shape) PLUS 5 paired tool-call targets (4 clean permitted
calls where the fix must NOT manufacture any accusation + 1 real-error
control). Frozen selection before the run; append-only journal with resume;
gold opened post-run by the scorer only.
"""
import argparse
import json
import time

from modular_common import Budget, BudgetStop, HERE, RESULTS, append, budget_phase, load_input, sha, source_sha, write

IDS = ['dev_implication::00', 'dev_implication::01', 'dev_request_effect::00',
       'dev_request_effect::01', 'dev_refusal_inventory::00', 'dev_refusal_inventory::01',
       # paired tool-call targets: 4 clean + 1 real-error control
       'dev_unless::02', 'dev_negative_scope::02', 'dev_units::00',
       'dev_retry_commit::00', 'dev_necessary::00']
FOLDER = RESULTS / 'atomic_repair_pilot'


def code_identity():
    paths = [HERE / name for name in ('atomic_check_v2.py', 'atomic_repair_pilot.py')]
    return sha({p.name: sha(p.read_text(encoding='utf-8').encode()) for p in paths})


def prepare():
    prepared = {'schema': 'atomic-repair-regression/1', 'status': 'FROZEN_BEFORE_RUN',
        'ids': IDS, 'phase': 'reviewer_repair',
        'original_invalid_ids': ['dev_refusal_inventory::00', 'dev_refusal_inventory::01',
                                 'dev_request_effect::00', 'dev_request_effect::01'],
        'original_invalid_causes': {'dev_refusal_inventory::00': 'transport_429',
                                    'dev_refusal_inventory::01': 'entity_id_shape',
                                    'dev_request_effect::00': 'transport_429',
                                    'dev_request_effect::01': 'transport_429'},
        'clean_paired_tool_calls': ['dev_unless::02', 'dev_negative_scope::02',
                                    'dev_units::00', 'dev_retry_commit::00'],
        'real_error_tool_call_control': ['dev_necessary::00'],
        'code_sha256': code_identity(),
        'forecast': {'calls_per_text_case': '3 (text atoms + requirements + verify)',
                     'calls_per_tool_case': '2 (requirements + verify)',
                     'expected_attempts': 'between 22 and 34 incl. at most one reask per call'},
        'advisory_only': 'atomic path stays ADVISORY; no automatic promotion to decisions'}
    rows = load_input('dev', IDS)
    prepared['source_sha256'] = {r['id']: source_sha(r) for r in rows}
    selection = FOLDER / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('atomic_repair_freeze_changed_use_versioned_recovery')
    else:
        write(selection, prepared)
    return rows, prepared


def run(*, prepare_only=True):
    rows, prepared = prepare()
    if prepare_only:
        print(json.dumps({'state': 'PREPARED_NO_INFERENCE', 'n': len(rows)}))
        return
    import atomic_check_v2
    budget = Budget('reviewer_repair')
    llm = budget.install()
    journal = FOLDER / 'predictions.jsonl'
    done = {r['id'] for r in map(json.loads, journal.read_text(encoding='utf-8').splitlines())} if journal.exists() else set()
    try:
        for row in rows:
            if row['id'] in done:
                continue
            began = time.monotonic()
            out = atomic_check_v2.run_case(llm, llm.DEFAULT_MISTRAL_MODEL, row)
            rec = {'id': row['id'], 'source_sha256': source_sha(row),
                   'code_sha256': prepared['code_sha256'],
                   'atomizer_text_status': out['atomizer_text_status'],
                   'requirement_status': out['requirement_status'],
                   'verifier_status': out['verifier_status'],
                   'coverage_gap': out['coverage_gap'],
                   'mechanical_actions': [a['tool'] for a in out['contract']['target']['actions']],
                   'text_atoms_n': len(out['contract']['target']['claims']),
                   'demoted_atoms': out['contract']['coverage']['demoted_atoms'],
                   'verification_relations': [c.get('relation') for c in out['verification'].get('checks', [])],
                   'contract': out['contract'],
                   'wall_seconds': time.monotonic() - began}
            append(journal, rec)
            done.add(row['id'])
            write(FOLDER / 'status.json', {'state': 'RUNNING', 'done': len(done), 'total': len(rows),
                                           'budget': budget.snapshot()})
        write(FOLDER / 'status.json', {'state': 'SUCCEEDED', 'done': len(done), 'total': len(rows),
                                       'budget': budget.snapshot()})
    except BudgetStop as exc:
        write(FOLDER / 'status.json', {'state': 'BUDGET_STOP', 'reason': str(exc), 'done': len(done),
                                       'total': len(rows), 'budget': budget.snapshot()})
    except Exception as exc:
        write(FOLDER / 'status.json', {'state': 'FAILED', 'error_type': type(exc).__name__, 'done': len(done),
                                       'budget': budget.snapshot()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    run(prepare_only=not args.run)
