"""Long-bank LLM quality pilot on a pre-registered balanced subset (§7.F).

The 60 completed layout/source checks and live HTTP receipts did not run an
LLM comparison; this pilot does, on a small balanced paired dev subset
chosen BEFORE viewing any results: begin/middle/end positions, real
exception rules and version updates with competing IDs, sizes 1k/4k/8k/12k,
clean/error twins per combo. 12001+ stays the operational UNKNOWN smoke
(existing service_long_v2 receipts referenced, no new call). The bank's
artificial two-SYSTEM-message layout is explicitly flagged in every row.
The unchanged C0 service runs each case; gold is never imported here.
"""
import json
import time
from modular_common import Budget, BudgetStop, HERE, RESULTS, append, budget_phase, sha, source_sha, write

FOLDER = RESULTS / 'long_bank_pilot'

# Pre-registered balanced paired subset: (family, size, position) combos,
# each contributing its clean AND error twin; 12k covered by a probe pair.
COMBOS = [
    ('exception', 1000, 'begin'),
    ('exception', 4000, 'middle'),
    ('exception', 8000, 'end'),
    ('version', 4000, 'begin'),
    ('version', 8000, 'middle'),
]
PROBE_12K = [('exception', 12000, 'middle', 'error'), ('version', 12000, 'begin', 'clean')]


def bank_rows():
    import hashlib
    manifest = json.loads((HERE / 'dataset/long_context_v2/manifest.json').read_text(encoding='utf-8'))
    for split in ('input', 'author_gold'):
        path = HERE / f'dataset/long_context_v2/{split}.jsonl'
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['splits'][split]:
            raise ValueError('long_bank_v2_hash_mismatch')
    inputs = {r['id']: r for r in map(json.loads, (HERE / 'dataset/long_context_v2/input.jsonl').read_text(encoding='utf-8').splitlines())}
    ids = []
    for family, size, position in COMBOS:
        ids += [f'long_v2_{family}_{size}_{position}_{label}' for label in ('clean', 'error')]
    ids += [f'long_v2_{family}_{size}_{position}_{label}' for family, size, position, label in PROBE_12K]
    missing = [i for i in ids if i not in inputs]
    if missing:
        raise ValueError('selection_not_in_long_bank:' + str(missing))
    return [inputs[i] for i in ids], manifest


def prepare(rows, manifest):
    prepared = {'schema': 'long-bank-pilot/1', 'status': 'FROZEN_BEFORE_RUN',
        'ids': [r['id'] for r in rows],
        'selection_rule': ('5 (family,size,position) combos with clean+error twins + one 12k probe pair; '
                           'chosen before viewing results; balanced across begin/middle/end, '
                           'exception/version families, 1k/4k/8k/12k'),
        'combos': [{'family': f, 'size': s, 'position': p, 'labels': ['clean', 'error']} for f, s, p in COMBOS],
        'probe_12k': [{'id': f'long_v2_{f}_{s}_{p}_{l}'} for f, s, p, l in PROBE_12K],
        'context_limit_note': '12000 exactly is in-limit by construction; 12001+ stays operational UNKNOWN smoke (service_long_v2 receipts)',
        'layout_caveat': manifest['format_caveat'],
        'service': 'r0-service-v1 unchanged C0 pipeline (structural v0.2 -> J -> reviewer)',
        'source_sha256': {r['id']: source_sha(r) for r in rows},
        'gold_access': 'runner never imports gold; post-run scorer only',
        'forecast': {'cases': len(rows), 'per_case': '1 J call + internal reviewer on J-ERROR'}}
    selection = FOLDER / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('long_bank_freeze_changed_use_versioned_recovery')
    else:
        write(selection, prepared)
    return prepared


def run():
    rows, manifest = bank_rows()
    prepared = prepare(rows, manifest)
    budget = Budget(budget_phase('dev'))
    budget.install()
    from runtime import GuardianServiceRuntime
    runtime = GuardianServiceRuntime('r0-service-v1')
    journal = FOLDER / 'predictions.jsonl'
    done = {r['id'] for r in map(json.loads, journal.read_text(encoding='utf-8').splitlines())} if journal.exists() else set()
    try:
        for row in rows:
            if row['id'] in done:
                continue
            began = time.monotonic()
            out = runtime.check({'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response']})
            append(journal, {'id': row['id'], 'source_sha256': source_sha(row), 'arm': 'C0',
                'decision': out.get('decision'), 'basis': out.get('basis'),
                'degraded': out.get('degraded'), 'unknown_reasons': out.get('unknown_reasons'),
                'usage': out.get('usage') or out.get('cost'),
                'layout': 'ARTIFICIAL_TWO_SYSTEM_MESSAGES',
                'wall_seconds': time.monotonic() - began})
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
    run()
