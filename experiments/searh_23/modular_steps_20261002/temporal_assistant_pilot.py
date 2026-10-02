"""Paired temporal-calculation assistant check (assignment §7.C tail).

Identical sources twice: the strict source-bound-v2 B review without the
module's advisory and with it. The module (typed_calculations.timestamps)
computes ISO literal arithmetic only; policy scope, entity IDs and action
admissibility stay with the judges. Primary J is reused from the frozen
archive where present; new-case primary J runs once (r0-service-v1) and is
shared by both arms. Gold is never imported here: only the post-run scorer
opens it. Selection is frozen before the first B call; the offline module
ground-truth gate must pass before that freeze.
"""
import copy
import json
import time
from pathlib import Path
from modular_common import Budget, BudgetStop, HERE, RESULTS, append, budget_phase, load_input, sha, source_sha, write

DEV_IDS = [f'dev_inclusive_timezone::{i:02d}' for i in range(8)]
FOLDER = RESULTS / 'temporal_assistant_pilot'

ADVISORY_HEADER = ("ADVISORY ONLY, verify against full original source.\n"
    "TEMPORAL CALCULATION MODULE (typed-ISO-relations/1): machine-computed arithmetic "
    "between quoted ISO-8601 literals only (EQUAL/LESS_THAN/GREATER_THAN and delta_seconds). "
    "These relations carry no policy semantics: policy scope, entity IDs and action "
    "admissibility are NOT decided by this module. Unzoned or relative date expressions, "
    "if present in the sources, are not parsed and produce no relations; no default "
    "timezone is guessed.\n")


def bank_rows():
    """8 frozen dev timezone cases + the new author boundary bank."""
    from modular_common import HERE as here
    dev = load_input('dev', DEV_IDS)
    manifest = json.loads((here / 'dataset/temporal_boundary/manifest.json').read_text(encoding='utf-8'))
    import hashlib
    for split in ('input', 'author_gold'):
        path = here / f'dataset/temporal_boundary/{split}.jsonl'
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[f'{split}_sha256']:
            raise ValueError('temporal_bank_hash_mismatch')
    new = [json.loads(s) for s in (here / 'dataset/temporal_boundary/input.jsonl').read_text(encoding='utf-8').splitlines()]
    if len(new) != manifest['n'] or {r['id'] for r in new} & {r['id'] for r in dev}:
        raise ValueError('temporal_bank_identity_problem')
    return dev + new


def module_advisory(row):
    from typed_calculations import timestamps
    return ADVISORY_HEADER + json.dumps(timestamps(row), ensure_ascii=False, sort_keys=True)


def code_identity():
    paths = [HERE / name for name in ('temporal_assistant_pilot.py', 'typed_calculations.py')]
    from modular_common import ROOT
    paths += [ROOT / 'service/runtime.py', ROOT / 'service/configs/modular-source-bound-r0-v1.json',
              ROOT / 'experiments/searh_23/hybrid_service_v1/counterevidence.py']
    return sha({p.relative_to(ROOT).as_posix(): sha(json.loads(p.read_text(encoding='utf-8')))
                if p.suffix == '.json' else sha(p.read_text(encoding='utf-8').encode()) for p in paths})


def verify_module(rows):
    """Offline ground-truth gate: arithmetic, spans, non-decision, no guessing.

    No API, no gold. The reference set is produced by an independent literal
    scan of the raw prompt; module sources must be a subset of it, relations
    must be pairwise-complete over its own sources and arithmetically exact.
    """
    import re
    from datetime import datetime
    from typed_calculations import timestamps
    iso = re.compile(r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b')
    report, failures = {}, []
    for row in rows:
        out = timestamps(row)
        problems = []
        found = [m.group() for m in iso.finditer(row['prompt'])]
        if out['coverage']['literals'] != len(set(found)):
            problems.append('coverage_literal_count_mismatch')
        if row['id'] == 'temporal_boundary::07' and '2026-10-03T12:00:00' in json.dumps(out):
            problems.append('unzoned_literal_parsed_default_timezone_guessed')
        module_literals = []
        for rel in out['relations']:
            for side in ('left_source', 'right_source'):
                lit = rel[side]['literal']
                if lit not in module_literals:
                    module_literals.append(lit)
                if lit not in found:
                    problems.append(f'literal_not_in_prompt:{lit}')
                start, end = rel[side]['start'], rel[side]['end']
                if row['prompt'][start:end] != lit:
                    problems.append(f'span_mismatch:{lit}')
        total_pairs = len(module_literals) * (len(module_literals) - 1) // 2
        if not out['coverage']['pair_limit_reached'] and len(out['relations']) != total_pairs:
            problems.append('relation_count_inconsistent')
        seen_pairs = set()
        values = {lit: datetime.fromisoformat(lit.replace('Z', '+00:00')) for lit in module_literals}
        for rel in out['relations']:
            pair = tuple(sorted((rel['left_source']['literal'], rel['right_source']['literal'])))
            if pair in seen_pairs:
                problems.append('duplicate_pair')
            seen_pairs.add(pair)
            delta = (values[rel['left_source']['literal']] - values[rel['right_source']['literal']]).total_seconds()
            truth = 'EQUAL' if delta == 0 else 'LESS_THAN' if delta < 0 else 'GREATER_THAN'
            if rel['relation'] != truth or abs(rel['delta_seconds'] - delta) > 1e-6:
                problems.append(f'arithmetic_error:{pair}')
        if out['decision'] != 'ADVISORY_ONLY_NOT_AUTOMATIC_ERROR':
            problems.append('module_decides')
        if not any('no default timezone is guessed' in line for line in out['limitations']):
            problems.append('missing_no_guess_limitation')
        report[row['id']] = {'module_literals': module_literals,
                             'prompt_iso_literals': sorted(set(found)),
                             'relations': len(out['relations']), 'problems': problems}
        failures += [f"{row['id']}:{p}" for p in problems]
    write(FOLDER / 'module_verification.json', {'status': 'PASS' if not failures else 'FAIL',
                                                'cases': report, 'failures': failures})
    if failures:
        raise ValueError('module_ground_truth_gate_failed:' + ';'.join(failures[:8]))
    return report


def prepare(rows, report):
    controls = {r['id']: r for r in map(json.loads, (RESULTS / 'control_dev/predictions.jsonl').read_text(encoding='utf-8').splitlines())}
    shared = {r['id'] for r in map(json.loads, (RESULTS / 'negative_review_pilot_v4/shared_B.jsonl').read_text(encoding='utf-8').splitlines())}
    from typed_calculations import timestamps
    prepared = {'schema': 'temporal-assistant-paired/1', 'status': 'FROZEN_BEFORE_B_CALLS',
        'bank_ids': [r['id'] for r in rows],
        'source_sha256': {r['id']: source_sha(r) for r in rows},
        'arms': ['B_without_calc', 'B_with_calc'],
        'arm_definition': ('identical sources, ctx, source-bound-v2 protocol, model and aggregation; '
                            'B_with_calc additionally sets ctx.advisory_context to the typed-ISO-relations '
                            'module output (pre-registered sha256 below)'),
        'module_output_sha256': {r['id']: sha(timestamps(r)) for r in rows},
        'module_verification': 'offline ground truth gate PASS, see module_verification.json',
        'code_sha256': code_identity(),
        'primary_reuse': {'control_dev_archive': [i for i in DEV_IDS if i in controls],
                          'new_primary_shared_by_both_arms': [r['id'] for r in rows if r['id'] not in controls],
                          'primary_config': 'r0-service-v1'},
        'B_reuse': {'negative_review_pilot_v4/shared_B.jsonl': [i for i in DEV_IDS if i in shared]},
        'B_protocol': 'source-bound-v2', 'B_model': 'env_mistral',
        'gold_access': 'runner_never_imports_gold; post-run scorer only',
        'human_gold_reviewed': False, 'new_sealed_access': False,
        'recovery_note': ('attempt-1 (archived as temporal_assistant_pilot_attempt1) ran fresh '
                          'primaries for all 18 cases including the 4 archived-control cases, '
                          'contradicting this frozen reuse plan; versioned recovery re-runs with '
                          'archive reuse. Paired arm validity was unaffected (both arms shared '
                          'the same primary per case). Attempt-1 costs remain in the dev2 ledger.'),
        'forecast': {'new_B_queries': 2 * len(rows) - len([i for i in DEV_IDS if i in shared]),
                     'new_primary_checks': len([r['id'] for r in rows if r['id'] not in controls]),
                     'repair_reasks': 'at most one per B call per frozen protocol'}}
    selection = FOLDER / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('temporal_pilot_freeze_changed_use_versioned_recovery')
    else:
        write(selection, prepared)
    return prepared, controls


def run(*, prepare_only=True):
    rows = bank_rows()
    report = verify_module(rows)
    prepared, controls = prepare(rows, report)
    if prepare_only:
        print(json.dumps({'state': 'PREPARED_NO_INFERENCE', 'bank': len(rows),
                          'arms': prepared['arms'], 'new_B_queries': prepared['forecast']['new_B_queries']}))
        return
    budget = Budget(budget_phase('dev'))
    llm = budget.install()
    original_chat = llm.chat
    active_source = {}

    def raw_chat(model, messages, **kwargs):
        answer = original_chat(model, messages, **kwargs)
        append(FOLDER / 'raw_B_calls.jsonl', dict(active_source, model=model,
            request_sha256=sha({'model': model, 'messages': messages, 'parameters': kwargs}),
            raw={key: answer.get(key) for key in ('content', 'usage', 'cached', 'error', 'error_type', 'http_status')}))
        return answer
    llm.chat = raw_chat
    from structural_v02 import parse_case_v02
    from runtime import GuardianServiceRuntime, _judge_findings, load_config
    from counterevidence import collect_review, aggregate_review
    from negative_routing import primary_vote
    config = load_config('modular-source-bound-r0-v1')['stages']['counterevidence']
    runtime = GuardianServiceRuntime('r0-service-v1')
    shared_path = RESULTS / 'negative_review_pilot_v4/shared_B.jsonl'
    shared = {r['id']: r for r in map(json.loads, shared_path.read_text(encoding='utf-8').splitlines())}
    primary_journal = FOLDER / 'primary_predictions.jsonl'
    primaries = {r['id']: r for r in map(json.loads, primary_journal.read_text(encoding='utf-8').splitlines())} if primary_journal.exists() else {}
    journal = FOLDER / 'predictions.jsonl'
    done = {(r['id'], r['arm']) for r in map(json.loads, journal.read_text(encoding='utf-8').splitlines())} if journal.exists() else set()
    try:
        for row in rows:
            # --- primary J: archived where possible, otherwise once per case ---
            if row['id'] in controls:
                # frozen archive reuse (selection.json primary_reuse plan): no new
                # inference for pilot-48 cases (attempt-1 bug: fresh primary ran
                # anyway; recovered under versioned recovery with archive reuse)
                if controls[row['id']]['source_sha256'] != source_sha(row):
                    raise ValueError('archived_primary_source_changed')
                primary_record = controls[row['id']]
                reused_primary = True
            else:
                if row['id'] in primaries and primaries[row['id']]['source_sha256'] != source_sha(row):
                    raise ValueError('primary_source_changed')
                if row['id'] not in primaries:
                    active_source.update(id=row['id'], stage='primary')
                    before = budget.snapshot()
                    out = runtime.check({'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response']})
                    after = budget.snapshot()
                    append(primary_journal, {'id': row['id'], 'source_sha256': source_sha(row), 'arm': 'C0',
                        'output': out, 'cost': {k: after[k] - before[k] for k in ('actual_api_attempts', 'logical_tokens', 'model_seconds')}})
                    primaries[row['id']] = {'id': row['id'], 'source_sha256': source_sha(row), 'output': out}
                primary_record = primaries[row['id']]
                reused_primary = False
            decision = primary_vote(primary_record['output'])
            ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
            primary_records = [r for s in primary_record['output']['module_trace']
                               if s.get('module') == 'judge' for r in s.get('records', [])]
            findings = _judge_findings(primary_records, ctx) if decision == 'ERROR' else []
            if decision == 'ERROR' and not findings:
                decision = 'UNKNOWN'
            # --- two paired arms ---
            for arm in ('B_without_calc', 'B_with_calc'):
                if (row['id'], arm) in done:
                    continue
                began = time.monotonic()
                reuse = arm == 'B_without_calc' and row['id'] in shared
                if reuse:
                    record = shared[row['id']]
                    if record['source_sha256'] != source_sha(row) or record['resolved_B_model'] != llm.DEFAULT_MISTRAL_MODEL:
                        raise ValueError('shared_review_identity_mismatch')
                    review, cost = record['review'], {'actual_api_attempts': 0, 'logical_tokens': 0, 'model_seconds': 0.0,
                                                      'reused_from': 'negative_review_pilot_v4/shared_B.jsonl',
                                                      'cost_if_executed_alone': record['cost']}
                else:
                    arm_ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
                    if arm == 'B_with_calc':
                        arm_ctx.advisory_context = module_advisory(row)
                    active_source.update(id=row['id'], stage=arm)
                    before = budget.snapshot()
                    review = collect_review(config, arm_ctx, findings, caller='modular/temporal/' + arm)
                    after = budget.snapshot()
                    cost = {k: after[k] - before[k] for k in ('actual_api_attempts', 'logical_tokens', 'model_seconds')}
                final, out_findings, reason = aggregate_review(review, decision, findings, ctx)
                degraded = decision == 'UNKNOWN'
                if not review['valid']:
                    final, out_findings, degraded = 'UNKNOWN', [], True
                append(journal, {'id': row['id'], 'arm': arm, 'source_sha256': source_sha(row),
                    'config_sha256': prepared['code_sha256'], 'primary_decision': decision,
                    'primary_reused_not_new_inference': reused_primary,
                    'module_advisory_sha256': prepared['module_output_sha256'][row['id']],
                    'advisory_attached': arm == 'B_with_calc', 'B_valid': review['valid'],
                    'B_status': review['status'], 'B_reason': review['reason'],
                    'B_additional_error': (review['review'] or {}).get('additional_error') is not None if review['review'] else None,
                    'decision': final, 'degraded': degraded, 'reason': reason,
                    'findings': out_findings, 'cost': cost,
                    'wall_seconds': time.monotonic() - began})
                done.add((row['id'], arm))
                write(FOLDER / 'status.json', {'state': 'RUNNING', 'done': len(done),
                    'total': 2 * len(rows), 'budget': budget.snapshot()})
        write(FOLDER / 'status.json', {'state': 'SUCCEEDED', 'done': len(done),
            'total': 2 * len(rows), 'budget': budget.snapshot()})
    except BudgetStop as exc:
        write(FOLDER / 'status.json', {'state': 'BUDGET_STOP', 'reason': str(exc), 'done': len(done),
            'total': 2 * len(rows), 'budget': budget.snapshot()})
    except Exception as exc:
        write(FOLDER / 'status.json', {'state': 'FAILED', 'error_type': type(exc).__name__, 'done': len(done),
            'budget': budget.snapshot()})
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    run(prepare_only=not args.run)
