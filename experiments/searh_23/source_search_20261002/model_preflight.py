"""Frozen paired readiness checks before another expensive full comparison.

No gold is imported. These are authored contrasts, not independent transfer.
The shared ledger is retained; defaults cannot extend the approved phase cap.
"""
import argparse
import json
from pathlib import Path

from acceptance import ROOT
from run_compare import identity, write
from guardian_truth.source_search.pipeline import contract, run
from guardian_truth.source_search.archive import persist_snapshot
from guardian_truth.source_search.store import digest
from guardian_truth.source_search.transport import ModelTransport

OUT = ROOT / 'outputs/searh_23/source_search_20261002/model_preflight_v3'
PHASE = Path('/workspace/guardian/results/source-search-api-phase-20261002')


def prepare():
    bank = ROOT / 'outputs/searh_23/source_search_20261002/transfer_v1/inputs.jsonl'
    rows = [json.loads(line) for line in bank.read_text(encoding='utf-8').splitlines()]
    # Frozen first variant of three contrast families. Opaque IDs, no labels.
    selected = [rows[i] for i in (0, 1, 8, 9, 20, 21)]
    protocol = {'scope': 'AUTHOR_CONTRAST_PREFLIGHT_NOT_INDEPENDENT_TRANSFER',
        'human_review_status': 'PENDING', 'inputs': selected, 'input_sha256': digest(selected),
        'code_sha256': identity(), 'runner_sha256': digest(Path(__file__).read_text(encoding='utf-8')),
        'arms': ['direct', 'search'], 'max_steps': 8,
        'models': [{'provider': 'mistral', 'model': 'SERVER_MISTRAL_MODEL'},
                   {'provider': 'ollama', 'model': 'gemma4:31b'}],
        'prompts': {p: contract(p) for p in ('DIRECT', 'SEARCH', 'JUDGE')},
        'stops': 'First provider breaker stops whole job; no retries. Every UNKNOWN retained.',
        'phase_ledger': PHASE.as_posix(), 'additional_budget_approved': False}
    path = OUT / 'frozen.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8')) != protocol:
        raise RuntimeError('frozen preflight changed; preserve prior version')
    write(path, protocol)
    return protocol


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    # Raising either limit requires explicit user authorization. No reset, new
    # phase directory, counter discount, or automatic extension is performed.
    parser.add_argument('--authorized-total-tokens', type=int, default=500000)
    parser.add_argument('--authorized-total-attempts', type=int, default=150)
    args = parser.parse_args()
    protocol = prepare()
    if not args.run:
        print(json.dumps({'state': 'FROZEN_NOT_STARTED', 'cases': 6, 'planned_records': 24,
            'code_sha256': protocol['code_sha256'], 'additional_budget': 'PENDING'}))
        return
    journal = OUT / 'predictions.jsonl'
    done = set()
    if journal.exists():
        done = {(r['case_id'], r['provider'], r['model'], r['mode'])
            for line in journal.read_text(encoding='utf-8').splitlines()
            if (r := json.loads(line))}
    for model in protocol['models']:
        transport = ModelTransport(PHASE, provider=model['provider'],
            model=None if model['model'] == 'SERVER_MISTRAL_MODEL' else model['model'],
            max_calls=args.authorized_total_attempts, max_tokens=args.authorized_total_tokens)
        # Capture the resolved actual model and cap before any HTTP request.
        launch_path = OUT / ('launch_' + model['provider'] + '.json')
        launch = {'frozen_sha256': digest(protocol), 'provider': transport.provider,
            'resolved_model': transport.model, 'limits': transport.snapshot()['limits']}
        if launch_path.exists() and json.loads(launch_path.read_text()) != launch:
            raise RuntimeError('resolved model/cap changed; do not overwrite launch receipt')
        write(launch_path, launch)
        for row in protocol['inputs']:
            for arm in protocol['arms']:
                key = (row['id'], transport.provider, transport.model, arm)
                if key in done:
                    continue
                before = transport.snapshot()
                result = run(row, transport, mode=arm, max_steps=protocol['max_steps'])
                result['source_archive'] = persist_snapshot(result.pop('sources'), OUT / 'source_stores')
                result.update(provider=transport.provider, model=transport.model,
                              budget_before=before, budget_after=transport.snapshot())
                with journal.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(result, ensure_ascii=False) + '\n')
                done.add(key)
                if transport.breaker.exists() or result['stop_reason'] == 'approved_phase_budget_exhausted':
                    write(OUT / 'status.json', {'state': 'STOPPED', 'records': len(done),
                        'budget': transport.snapshot(), 'reason': result['stop_reason']})
                    return
    write(OUT / 'status.json', {'state': 'COMPLETE', 'records': len(done), 'planned_records': 24})


if __name__ == '__main__':
    main()
