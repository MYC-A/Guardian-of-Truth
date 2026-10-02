"""Frozen source-only inputs, same-model direct/search comparison, resumable."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from acceptance import ROOT, rows
from guardian_truth.source_search.pipeline import contract, run
from guardian_truth.source_search.store import digest
from guardian_truth.source_search.transport import ModelTransport
from guardian_truth.source_search.archive import persist_snapshot
from guardian_truth.source_search.store import SourceStore
from runtime import GuardianServiceRuntime

OUT = ROOT / 'outputs/searh_23/source_search_20261002/comparison_v12'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode())


def identity():
    files = sorted((ROOT / 'src/guardian_truth/source_search').glob('*.py')) + [Path(__file__),
        Path(__file__).parent / 'acceptance.py', ROOT / 'service/runtime.py',
        ROOT / 'service/configs/source-search-v1.json', ROOT / 'src/guardian_truth/parsing.py',
        ROOT / 'src/guardian_truth/provenance.py', ROOT / 'src/guardian_truth/types.py',
        ROOT / 'experiments/searh_23/three_architectures/judge.py',
        ROOT / 'experiments/searh_23/three_architectures/common.py',
        ROOT / 'experiments/searh_23/hybrid_service_v1/structural_v02.py']
    return digest({p.relative_to(ROOT).as_posix(): p.read_text(encoding='utf-8') for p in files})


def prepare():
    prior_inputs = ROOT / 'outputs/searh_23/source_search_20261002/comparison_v3/inputs.jsonl'
    if (OUT / 'inputs.jsonl').exists():
        source_rows = [json.loads(line) for line in (OUT / 'inputs.jsonl').read_text(encoding='utf-8').splitlines()]
    elif prior_inputs.exists():
        source_rows = [json.loads(line) for line in prior_inputs.read_text(encoding='utf-8').splitlines()]
    else:
        source_rows = rows()
    # All source inputs are frozen; no labels/explanations enter this process.
    input_sha = digest(source_rows)
    cfg = json.loads((ROOT / 'service/configs/source-search-v1.json').read_text())
    protocol = {'schema': 'guardian-source-comparison/1', 'scope': 'HISTORICAL_PUBLIC46_DEVELOPMENT',
        'input_sha256': input_sha, 'code_sha256': identity(), 'case_ids': [r['id'] for r in source_rows],
        'model_budget': cfg['model_budget'], 'algorithm': cfg['stages']['source_search'],
        'arms': ['direct', 'search'], 'prompts': {phase: contract(phase) for phase in ('DIRECT', 'SEARCH', 'JUDGE')},
        'interleave': 'direct then search per identical source input; resume exact completed pairs',
        'stops': 'first 402/429 stops whole batch, no retries/polling; resource caps preserve partial records',
        'quality_scoring': 'separate script after predictions; UNKNOWN not renamed to NO_ERROR',
        'cap_authorization': 'User approved new separate 500000-token / 150-attempt phase on 2026-10-02',
        'prior_ledger_reset': False, 'predict_py_changed': False}
    if (OUT / 'frozen.json').exists():
        if json.loads((OUT / 'frozen.json').read_text(encoding='utf-8')) != protocol:
            raise RuntimeError('frozen code/input changed; create a new version, do not overwrite this run')
    else:
        write(OUT / 'frozen.json', protocol)
        (OUT / 'inputs.jsonl').write_bytes(b''.join((json.dumps(r, ensure_ascii=False) + '\n').encode() for r in source_rows))
    return protocol, source_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    protocol, source_rows = prepare()
    if not args.run:
        print(json.dumps({'state': 'FROZEN', 'cases': len(source_rows), 'code_sha256': protocol['code_sha256']}))
        return
    transport = ModelTransport('/workspace/guardian/results/source-search-api-phase-20261002', **protocol['model_budget'])
    done = set()
    journal = OUT / 'predictions.jsonl'
    if journal.exists():
        done = {(r['case_id'], r['mode']) for line in journal.read_text(encoding='utf-8').splitlines() if (r := json.loads(line))}
    state = 'COMPLETE'
    for row in source_rows[:args.limit]:
        for arm in protocol['arms']:
            if (row['id'], arm) in done:
                continue
            before = transport.snapshot()
            started = time.monotonic()
            service = GuardianServiceRuntime('source-search-v1', audit_path=OUT / 'service_audit.jsonl')
            service.config['stages']['source_search']['mode'] = arm
            service._source_transport = transport
            result = service.check({'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response']})
            result['source_archive'] = persist_snapshot(result.pop('source_store'), OUT / 'source_stores')
            result['mode'] = arm
            result['stop_reason'] = result['coverage'].get('stop_reason', 'structural_confirmed_hit')
            result['cost_before'], result['cost_after'] = before, transport.snapshot()
            result['wall_seconds'] = time.monotonic() - started
            # Keep raw model votes and validator errors, even when UNKNOWN.
            with journal.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(result, ensure_ascii=False) + '\n'); stream.flush()
            done.add((row['id'], arm))
            if transport.breaker.exists() or result['stop_reason'] == 'approved_phase_budget_exhausted':
                state = 'PROVIDER_STOP' if transport.breaker.exists() else 'BUDGET_STOP'
                break
        if state != 'COMPLETE':
            break
    if args.limit and state == 'COMPLETE' and args.limit < len(source_rows):
        state = 'LIMITED_PILOT'
    status = {'state': state, 'completed_records': len(done), 'planned_records': len(source_rows)*2,
              'budget': transport.snapshot(), 'frozen_sha256': digest(protocol)}
    write(OUT / 'status.json', status)
    print(json.dumps(status))


if __name__ == '__main__':
    main()
