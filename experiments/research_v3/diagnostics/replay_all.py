"""Reproduce every V4 phase offline and verify saved prediction byte identity."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'outputs/searh_23'
DIAG = BASE / 'semantic_hybrid_v4_diagnostics_20261004'
RUNNER = 'experiments/research_v3/'
PHASES = [
    ('semantic_hybrid_v4_20261004', 'pilot.py', [], 'A0_A1_A2_A3'),
    ('semantic_hybrid_v4_gemma_20261004', 'pilot.py', ['--provider', 'ollama', '--model', 'gemma4:31b', '--arms', 'A0', 'A2', 'A3'], 'A0_A2_A3'),
    ('semantic_hybrid_v4_graph_ids_dev_20261004', 'diagnostics/id_controls.py', ['--control', 'graph_ids'], 'A1'),
    ('semantic_hybrid_v4_context_enums_dev_20261004', 'diagnostics/id_controls.py', ['--control', 'context_enums'], 'A0'),
    ('semantic_hybrid_v4_gemma_contract_20261004', 'diagnostics/gemma_contract.py', ['--limit', '2'], 'A0_A2'),
    ('semantic_hybrid_v4_gemma_context_20261004', 'diagnostics/gemma_context.py', [], 'A0'),
    ('semantic_hybrid_v4_prospective_20261004', 'diagnostics/prospective/run.py', [], 'A0'),
]


def invoke(script, args):
    command = [sys.executable, RUNNER + script, *map(str, args)]
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=120)
    if result.returncode:
        raise RuntimeError(f'{command}: {result.stdout}\n{result.stderr}')
    return result


def main():
    DIAG.mkdir(parents=True, exist_ok=True)
    verifications, costs = [], []
    for name, script, options, suffix in PHASES:
        out = BASE / name
        prediction = out / f'predictions_{suffix}.json'
        completion = out / f'completion_{suffix}.json'
        before = prediction.read_bytes()
        original_completion = completion.read_bytes()
        ledger_before = (out / 'ledger.json').read_bytes()
        try:
            invoke(script, ['replay', '--out', out, *options])
            if prediction.read_bytes() != before:
                raise ValueError('PREDICTION_REPLAY_DIFFERS:' + name)
            if (out / 'ledger.json').read_bytes() != ledger_before:
                raise ValueError('REPLAY_CHANGED_HTTP_LEDGER:' + name)
        finally:
            completion.write_bytes(original_completion)
        verifications.append({'phase': name, 'prediction_sha256': hashlib.sha256(before).hexdigest(),
                              'byte_identical': True, 'ledger_unchanged': True, 'new_http': 0})
        ledger = json.loads(ledger_before)
        costs.append({'phase': name, 'attempts': len(ledger),
                      'known_tokens': sum(v.get('known_tokens', 0) for v in ledger.values()),
                      'charged_tokens': sum(v.get('charged_tokens', 0) for v in ledger.values()),
                      'http_seconds': sum(v.get('seconds', 0) for v in ledger.values()),
                      'statuses': dict(Counter(v['status'] for v in ledger.values()))})
        if name.endswith('prospective_20261004'):
            invoke('diagnostics/prospective/score_results.py', ['--out', out])
        else:
            invoke('score.py', ['--out', out, '--predictions', prediction])
            invoke('diagnostics/execution_subset.py', ['--out', out, '--predictions', prediction])
        if suffix == 'A1' or suffix == 'A0_A1_A2_A3':
            invoke('diagnostics/audit_results.py', ['--out', out, '--predictions', prediction])
    invoke('diagnostics/tri_logic_gap.py', [])
    invoke('diagnostics/comparison_summary.py', [])
    invoke('diagnostics/source_guard.py', ['--out', BASE / 'semantic_hybrid_v4_gemma_context_20261004',
           '--predictions', BASE / 'semantic_hybrid_v4_gemma_context_20261004/predictions_A0.json'])
    total = {k: sum(c[k] for c in costs) for k in ('attempts', 'known_tokens', 'charged_tokens', 'http_seconds')}
    statuses = Counter()
    for c in costs:
        statuses.update(c['statuses'])
    result = {'phases': costs, 'total': {**total, 'statuses': dict(statuses), 'retries': 0,
              'gpu_inference': False, 'provider_reported_dollars': None,
              'historical_replay_tokens_excluded': 399533}, 'offline_verification': verifications,
              'python': sys.version, 'new_http_during_replay': 0}
    (DIAG / 'aggregate_and_replay.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    with (DIAG / 'cost_comparison.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['phase', 'attempts', 'known_tokens', 'charged_tokens', 'http_seconds'])
        writer.writeheader()
        writer.writerows({k: c[k] for k in writer.fieldnames} for c in costs)
    print(json.dumps({'verified_phases': len(verifications), 'new_http': 0, 'total': result['total']}))


if __name__ == '__main__':
    main()
