"""RAG-Triad paired-input bank extension (assignment §7.E).

The frozen pilot_triad selection covered one preselected uncertainty case;
this versioned extension completes the remaining two on the same paired
inputs (raw prompt / G2 selected graph / G2-linear same-facts linear),
checking both the target move and the Guardian explanation. The TruLens
author feedback templates run through the pinned transparent adapter with
the budgeted Mistral backend: an adapted feedback executor, NOT a native
TruLens provider evaluation. Three scores plus coverage are diagnostics,
not correctness proofs. No gold import.
"""
import json
import time
from modular_common import Budget, BudgetStop, RESULTS, append, budget_phase, load_input, sha, source_sha, write
from mechanism_pilots import baseline, triad_pass

IDS = ['dev_request_effect::01', 'dev_inclusive_timezone::02']
FOLDER = RESULTS / 'pilot_triad_v2'


def code_identity():
    from modular_common import ROOT, HERE
    paths = [HERE / name for name in ('triad_bank.py', 'mechanism_pilots.py', 'triad_adapter.py',
                                      'evidence_views.py')]
    return sha({p.relative_to(ROOT).as_posix(): sha(p.read_text(encoding='utf-8').encode()) for p in paths})


def prepare():
    prepared = {'schema': 'triad-bank-extension/1', 'status': 'FROZEN_BEFORE_RUN', 'ids': IDS,
        'paired_inputs': ['raw', 'G2', 'G2-linear'], 'checked': ['target', 'explanation'],
        'dimensions': ['context_relevance', 'groundedness', 'answer_relevance'],
        'adapter': 'TruLens-author-template-port/1 (adapted feedback executor, not native provider run)',
        'completion_of': 'pilot_triad (1 case, frozen); total bank = 3 preselected uncertainty cases',
        'code_sha256': code_identity(),
        'gold_access': 'runner never imports gold'}
    selection = FOLDER / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('triad_bank_freeze_changed_use_versioned_recovery')
    else:
        write(selection, prepared)
    return prepared


def run():
    prepared = prepare()
    budget = Budget(budget_phase('dev'))
    llm = budget.install()
    controls = baseline()
    journal = FOLDER / 'predictions.jsonl'
    done = {r['id'] for r in map(json.loads, journal.read_text(encoding='utf-8').splitlines())} if journal.exists() else set()
    try:
        for row in load_input(ids=IDS):
            if row['id'] in done:
                continue
            began = time.monotonic()
            result = triad_pass(llm, row, controls[row['id']])
            append(journal, {'id': row['id'], 'arm': 'triad', 'source_sha256': source_sha(row),
                             'config_sha256': prepared['code_sha256'], 'result': result,
                             'wall_seconds': time.monotonic() - began})
            done.add(row['id'])
            write(FOLDER / 'status.json', {'state': 'RUNNING', 'done': len(done), 'total': len(IDS),
                                           'budget': budget.snapshot()})
        write(FOLDER / 'status.json', {'state': 'SUCCEEDED', 'done': len(done), 'total': len(IDS),
                                       'budget': budget.snapshot()})
    except BudgetStop as exc:
        write(FOLDER / 'status.json', {'state': 'BUDGET_STOP', 'reason': str(exc), 'done': len(done),
                                       'total': len(IDS), 'budget': budget.snapshot()})
    except Exception as exc:
        write(FOLDER / 'status.json', {'state': 'FAILED', 'error_type': type(exc).__name__, 'done': len(done),
                                       'budget': budget.snapshot()})
        raise


if __name__ == '__main__':
    run()
