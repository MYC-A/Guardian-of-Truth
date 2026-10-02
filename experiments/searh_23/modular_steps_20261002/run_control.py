"""Unchanged C0 service on hash-frozen new inputs. No gold access."""
import argparse
import json
from pathlib import Path
import time
from modular_common import Budget, BudgetStop, HERE, RESULTS, append, budget_phase, load_input, source_sha, write


def run(split='dev', all_cases=False):
    ids = None if all_cases else json.loads((HERE / 'dataset/pilot_ids.json').read_text())
    rows = load_input(split, ids)
    # Explicit phase wiring (user fix 2026-10-02 #1): dev continuation runs
    # charge the authorized dev2 phase, sealed stays on the frozen heldout.
    budget = Budget(budget_phase(split))
    budget.install()
    from runtime import GuardianServiceRuntime
    runtime = GuardianServiceRuntime('r0-service-v1')
    folder = RESULTS / ('control_' + split)
    folder.mkdir(parents=True, exist_ok=True)
    write(folder / 'selection.json', {'config': runtime.config, 'ids': [r['id'] for r in rows],
                                     'source_hashes': {r['id']: source_sha(r) for r in rows}})
    journal = folder / 'predictions.jsonl'
    done = {}
    if journal.exists():
        for line in journal.read_text().splitlines():
            rec = json.loads(line)
            if rec['id'] in done:
                raise ValueError('duplicate_prediction')
            done[rec['id']] = rec
    try:
        for row in rows:
            if row['id'] in done:
                assert done[row['id']]['source_sha256'] == source_sha(row)
                continue
            began = time.monotonic()
            out = runtime.check({'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response']})
            rec = {'id': row['id'], 'source_sha256': source_sha(row), 'arm': 'C0',
                   'output': out, 'wall_seconds': time.monotonic() - began}
            append(journal, rec)
            done[row['id']] = rec
            write(folder / 'status.json', {'state': 'RUNNING', 'done': len(done), 'total': len(rows), 'budget': budget.snapshot()})
        write(folder / 'status.json', {'state': 'SUCCEEDED', 'done': len(done), 'total': len(rows), 'budget': budget.snapshot()})
    except BudgetStop:
        write(folder / 'status.json', {'state': 'BUDGET_STOP', 'done': len(done), 'total': len(rows), 'budget': budget.snapshot()})
    except Exception as exc:
        write(folder / 'status.json', {'state': 'FAILED', 'error_type': type(exc).__name__, 'done': len(done), 'budget': budget.snapshot()})
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--split', default='dev', choices=['dev', 'sealed'])
    p.add_argument('--all', action='store_true')
    args = p.parse_args()
    run(args.split, args.all)
