"""Read-only checkpoint with actual stage evidence, not placeholder model results."""

import argparse
import json
from pathlib import Path
import subprocess

from guardian_truth.vnext.integrity import file_digest, verify_files, write_new


ROOT = Path(__file__).resolve().parents[1]


def head(directory):
    return subprocess.run(['git', '-C', str(directory), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, choices=['v9'])
    args = parser.parse_args()
    output = ROOT / 'outputs/vnext'
    manifest_path = output / 'freeze_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    errors = verify_files(ROOT, manifest['frozen_input_sha256']) + verify_files(ROOT, manifest['regression_input_sha256'])
    for name in ('tool_t1_freeze_v1.json', 'claim_graph_v1_freeze.json', 'goal_plan_v2_freeze.json'):
        freeze = json.loads((output / name).read_text(encoding='utf-8'))
        errors += verify_files(ROOT, freeze['source_sha256'])
    expected = {'production': ('Guardian of Truth', manifest['baseline_commits']['X0']),
        'Cycle1': ('Guardian of Truth Next', manifest['baseline_commits']['Cycle1']),
        'Cycle2': ('Guardian of Truth Cycle2', manifest['cycle2_base'])}
    protected = {name: {'actual': head(ROOT.parent / folder), 'expected': sha} for name, (folder, sha) in expected.items()}
    import sys
    completed = subprocess.run([sys.executable, '-m', 'pytest', 'tests', '-q'], cwd=ROOT, capture_output=True, text=True)
    import re
    match = re.findall(r'(\d+) passed', completed.stdout)
    passed = int(match[-1]) if match else 0
    stage_files = {'provider_gate': 'provider_gate_v1.json', 'T1': 'tool_t1_results_v1.json',
        'Goal_v1': 'goal_plan_v1_results.json', 'Claim_v1': 'claim_graph_v1_results.json'}
    stages = {}
    for stage, name in stage_files.items():
        path = output / name
        stages[stage] = {'status': 'COMPLETED_REPORT_PRESENT' if path.exists() else 'REPORT_NOT_PRESENT',
            'report': name, 'sha256': file_digest(path) if path.exists() else None}
    stages['Goal_v2'] = {'status': 'FROZEN_REQUESTS_STARTED_TERMINAL_OUTCOME_PENDING',
        'freeze_sha256': file_digest(output / 'goal_plan_v2_freeze.json'),
        'note': 'process liveness is separately tracked; started artifacts alone are not terminal results'}
    good = completed.returncode == 0 and not errors and all(row['actual'] == row['expected'] for row in protected.values())
    report = {'schema_version': 'guardian-vnext-unit-checkpoint-v2', 'architecture_commit': head(ROOT),
        'status': 'UNIT_AND_INTEGRITY_VALIDATED_ONLY' if good else 'FAILED',
        'scope': 'read-only controlled units/integrity; stage results are separately authoritative',
        'full_project_units': {'command': ['python', '-m', 'pytest', 'tests', '-q'], 'exit_code': completed.returncode, 'passed': passed},
        'integrity_errors': errors, 'protected_heads': protected, 'model_stages': stages,
        'claim_admission': 'SPAN_PASSED_SHARED_TYPED_GAIN_FAILED', 'general_semantic_lowering': 'PARTIAL',
        'whole_core_blind_end_to_end': 'NOT_RUN', 'api_requests': 0, 'blind_gold_read': False,
        'supersedes': 'v8 stage-reference bookkeeping: T1 report exists under versioned tool_t1_results_v1.json; original v8 preserved'}
    write_new(output / ('checkpoint_checks_' + args.version + '.json'), report)
    print(json.dumps({'status': report['status'], 'tests_passed': passed, 'integrity_errors': len(errors), 'api_requests': 0}))
    return 0 if good else 1


if __name__ == '__main__':
    raise SystemExit(main())
