"""Record actual read-only unit/integrity checks and stage artifact availability."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from guardian_truth.vnext.integrity import file_digest, verify_files, write_new


ROOT = Path(__file__).resolve().parents[1]


def head(directory):
    return subprocess.run(['git', '-C', str(directory), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'v[1-9][0-9]*', args.version):
        raise ValueError('safe new checkpoint version required')
    output = ROOT / 'outputs/vnext'
    manifest = json.loads((output / 'freeze_manifest.json').read_text(encoding='utf-8'))
    errors = verify_files(ROOT, manifest['frozen_input_sha256']) + verify_files(ROOT, manifest['regression_input_sha256'])
    stages = {}
    for prefix, freeze_name, report_name in (
        ('T1', 'tool_t1_freeze_v1.json', 'tool_t1_results_v1.json'),
        ('Claim_v1', 'claim_graph_v1_freeze.json', 'claim_graph_v1_results.json'),
        ('Goal_v2', 'goal_plan_v2_freeze.json', 'goal_plan_v2_results.json'),
        ('T2_v1', 'tool_t2_v1_freeze.json', 'tool_t2_v1_results.json'),
        ('Policy_program_v1', 'policy_programs_v1_freeze.json', 'policy_programs_v1_results.json')):
        freeze_path, report_path = output / freeze_name, output / report_name
        if freeze_path.exists():
            errors.extend(verify_files(ROOT, json.loads(freeze_path.read_text(encoding='utf-8'))['source_sha256']))
        stages[prefix] = {'freeze_sha256': file_digest(freeze_path) if freeze_path.exists() else None,
            'report_sha256': file_digest(report_path) if report_path.exists() else None,
            'status': 'REPORT_PRESENT' if report_path.exists() else 'FINAL_REPORT_NOT_PRESENT',
            'liveness': 'NOT_INFERRED_FROM_ARTIFACTS'}
    protected = {name: {'actual': head(ROOT.parent / folder), 'expected': expected}
        for name, folder, expected in (
            ('production', 'Guardian of Truth', manifest['baseline_commits']['X0']),
            ('Cycle1', 'Guardian of Truth Next', manifest['baseline_commits']['Cycle1']),
            ('Cycle2', 'Guardian of Truth Cycle2', manifest['cycle2_base']))}
    command = [sys.executable, '-m', 'pytest', '-q']
    units = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    matches = re.findall(r'(\d+) passed', units.stdout)
    good = not errors and units.returncode == 0 and all(row['actual'] == row['expected'] for row in protected.values())
    report = {'schema_version': 'guardian-vnext-unit-checkpoint-v3', 'architecture_commit': head(ROOT),
        'status': 'UNIT_AND_INTEGRITY_VALIDATED_ONLY' if good else 'FAILED',
        'full_project_units': {'command': ['python', '-m', 'pytest', '-q'], 'exit_code': units.returncode,
            'passed': int(matches[-1]) if matches else 0},
        'integrity_errors': errors, 'protected_heads': protected, 'model_stages': stages,
        'api_requests': 0, 'blind_gold_read': False, 'whole_core_blind_end_to_end': 'NOT_RUN',
        'supersedes_scope_label': 'v10 ran pytest tests -q (1053 tests); this checkpoint records unrestricted discovery with its exact command; original receipt preserved'}
    write_new(output / ('checkpoint_checks_' + args.version + '.json'), report)
    print(json.dumps({'status': report['status'], 'tests_passed': report['full_project_units']['passed'],
        'integrity_errors': len(errors), 'api_requests': 0}))
    return 0 if good else 1


if __name__ == '__main__':
    raise SystemExit(main())
