"""Check historical source seals without changing manifests or opening labels."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def audit(restore_line_endings=False):
    manifests = list((ROOT / 'outputs/vnext').glob('*freeze*.json'))
    manifests += [ROOT / 'outputs/vnext/source_delimiter_envelope_v4_audit_v1.json']
    failures, restored, blobs = [], [], {}
    for manifest in manifests:
        value = json.loads(manifest.read_text(encoding='utf-8'))
        for relative, expected in value.get('source_sha256', {}).items():
            path = (ROOT / relative).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file(): continue
            original = path.read_bytes()
            if sha(original) == expected: continue
            if relative not in blobs:
                blobs[relative] = subprocess.run(['git', 'show', '9e6e8821:' + relative], cwd=ROOT,
                    capture_output=True, check=True).stdout
            baseline = blobs[relative]
            entry = {'manifest': str(manifest.relative_to(ROOT)), 'source': relative,
                'expected_sha256': expected, 'worktree_sha256': sha(original),
                'baseline_git_blob_sha256': sha(baseline),
                'baseline_matches_seal': sha(baseline) == expected,
                'only_line_endings_differ': original.replace(b'\r\n', b'\n') == baseline}
            if restore_line_endings and entry['baseline_matches_seal'] and entry['only_line_endings_differ']:
                path.write_bytes(baseline)
                restored.append(entry)
            else: failures.append(entry)
    report = {'status': 'AUDIT_NOT_MODEL_TEST', 'api_calls': 0, 'baseline_commit': '9e6e8821',
        'manifests_checked': len(manifests), 'restored_exact_git_blob_line_endings': restored,
        'unresolved_seal_mismatches': failures, 'never_updated_seals': True}
    output = ROOT / 'outputs/searh_23/v10/preflight/regressions.json'
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--restore-line-endings', action='store_true')
    args = parser.parse_args()
    report = audit(args.restore_line_endings)
    print(json.dumps({'restored': len(report['restored_exact_git_blob_line_endings']),
        'remaining_seal_references': len(report['unresolved_seal_mismatches']),
        'unique_remaining_sources': sorted({r['source'] for r in report['unresolved_seal_mismatches']})}))
