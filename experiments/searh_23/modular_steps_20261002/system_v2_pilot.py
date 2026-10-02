"""E2E dev measurement of automatic SystemV2 Steps 2-4 (assignment §7.D M1).

Ordinary upstream only: the modular-system-v2-v1 service profile runs the
automatic SystemV2 Steps 2-4 advisory (no gold substitution), the selected
G2 graph advisory, the original J and the strict independent B. The §7.A
v2_replay already proved archived proposals bit-identical; this pilot
measures the live end-to-end profile against gold and the archived C0
baseline. Gold is never imported here; the post-run scorer opens it.
"""
import argparse
import json
import time
from modular_common import Budget, BudgetStop, HERE, RESULTS, append, budget_phase, load_input, sha, source_sha, write

IDS = ['dev_nested_gate::00', 'dev_negative_scope::00', 'dev_refusal_inventory::00', 'dev_refusal_inventory::01']
CONFIG = 'modular-system-v2-v1'
FOLDER = RESULTS / 'system_v2_pilot'


def code_identity():
    from modular_common import ROOT
    paths = [HERE / name for name in ('system_v2_pilot.py', 'modular_runtime.py', 'v2_pipeline.py',
                                      'mechanism_pilots.py', 'evidence_views.py')]
    paths += [ROOT / 'service/runtime.py', ROOT / 'service/configs/r0-service-v1.json',
              ROOT / 'service/configs/modular-source-bound-r0-v1.json',
              ROOT / 'experiments/searh_23/hybrid_service_v1/counterevidence.py']
    return sha({p.relative_to(ROOT).as_posix(): sha(json.loads(p.read_text(encoding='utf-8')))
                if p.suffix == '.json' else sha(p.read_text(encoding='utf-8').encode()) for p in paths})


def prepare():
    prepared = {'schema': 'system-v2-e2e/1', 'status': 'FROZEN_BEFORE_RUN', 'ids': IDS,
        'config': CONFIG, 'config_description': 'automatic SystemV2 Steps2-4 advisory + G2 graph + original J + strict B',
        'upstream': 'ordinary automatic IR extraction; no gold substitutions',
        'code_sha256': code_identity(),
        'source_sha256': {}, 'baseline_reference': 'control_dev/predictions.jsonl (C0, frozen)',
        'v2_replay_reference': '§7.A receipt: proposals bit-identical 4/4 on these cases',
        'gold_access': 'runner never imports gold; post-run scorer only',
        'forecast': {'per_case_calls': '4 SystemV2 stage calls + 1 J + 1-2 strict B'}}
    rows = load_input('dev', IDS)
    prepared['source_sha256'] = {r['id']: source_sha(r) for r in rows}
    selection = FOLDER / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('system_v2_freeze_changed_use_versioned_recovery')
    else:
        write(selection, prepared)
    return rows, prepared


def run(*, prepare_only=True):
    rows, prepared = prepare()
    if prepare_only:
        print(json.dumps({'state': 'PREPARED_NO_INFERENCE', 'n': len(rows), 'config': CONFIG}))
        return
    import modular_runtime
    budget = Budget(budget_phase('dev'))
    budget.install()
    journal = FOLDER / 'predictions.jsonl'
    done = {r['id'] for r in map(json.loads, journal.read_text(encoding='utf-8').splitlines())} if journal.exists() else set()
    try:
        for row in rows:
            if row['id'] in done:
                continue
            began = time.monotonic()
            out = modular_runtime.check({'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response']}, CONFIG)
            rec = {'id': row['id'], 'source_sha256': source_sha(row), 'config': CONFIG,
                   'config_sha256': prepared['code_sha256'],
                   'decision': out['decision'], 'basis': out.get('basis'),
                   'degraded': out.get('degraded'), 'unknown_reasons': out.get('unknown_reasons'),
                   'cost': out.get('cost'), 'modules': [m.get('module') for m in out.get('modules', [])],
                   'v2_advisory_summary': _advisory_summary(out),
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


def _advisory_summary(out):
    """Compact SystemV2 advisory provenance: per-step status, no payloads."""
    for module in out.get('modules', []):
        payload = module.get('payload') or {}
        if isinstance(payload, dict) and payload.get('module') == 'automatic-SystemV2-native-Steps2-4/1':
            steps = {}
            for key in ('step1', 'step2', 'step3', 'step4'):
                stage = payload.get(key) or {}
                entry = {'issues': len(stage.get('issues', []))}
                for extra in ('programs', 'bindings', 'queries', 'proofs'):
                    if isinstance(stage.get(extra), list):
                        entry[extra] = len(stage[extra])
                if isinstance(stage.get('reachability'), dict):
                    entry['reachability'] = stage['reachability'].get('status')
                steps[key] = entry
            steps['native_fact_count'] = payload.get('native_fact_count')
            steps['source_pairing_issues'] = len(payload.get('source_pairing_issues', []))
            return steps
    return {'note': 'advisory_module_not_found_in_modules'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    run(prepare_only=not args.run)
