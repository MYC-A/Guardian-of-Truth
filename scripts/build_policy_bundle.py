"""Offline (CI) build of the signed policy bundle. Never calls an LLM.

Inputs are stored artifacts only: prepared policies (outputs/searh_23/v11/preparation)
and frozen proposer replies (pilot audit zip / JSON files). Policies without exactly
three proposers are reported in ``coverage`` and are not compiled.

    GUARDIAN_BUNDLE_KEY=... python scripts/build_policy_bundle.py --output build/policy_bundle.json
"""
import argparse
import glob
import json
import sys
import zipfile
from pathlib import Path

from guardian_truth.policy_table_v11.bundle import build_bundle, compile_from_replies, write_bundle

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREP = ROOT / 'outputs/searh_23/v11/preparation'
DEFAULT_REPLIES = [ROOT / 'outputs/searh_23/v11/pilot_52861003_audit.zip']


def load_replies(sources):
    out = []
    for src in sources:
        src = Path(src)
        if src.suffix == '.zip':
            with zipfile.ZipFile(src) as z:
                for name in sorted(z.namelist()):
                    if name.startswith('replies/') and name.endswith('.json'): out.append(json.loads(z.read(name)))
        elif src.is_dir():
            out += [json.loads(Path(p).read_text(encoding='utf-8')) for p in sorted(glob.glob(str(src / '*.json')))]
        else: out.append(json.loads(src.read_text(encoding='utf-8')))
    return [r for r in out if isinstance(r, dict) and {'policy', 'trigger', 'proposer', 'family', 'response'} <= set(r)]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--preparation', type=Path, default=DEFAULT_PREP)
    ap.add_argument('--replies', type=Path, nargs='*', default=DEFAULT_REPLIES)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--family-fallback', action='store_true')
    args = ap.parse_args(argv)
    policies = {}
    for p in sorted(args.preparation.glob('*.json')):
        d = json.loads(p.read_text(encoding='utf-8'))
        if isinstance(d, dict) and 'policy_sha256' in d and 'clauses' in d: policies[d['policy_sha256']] = d
    tables, coverage = compile_from_replies(policies, load_replies(args.replies), family_fallback=args.family_fallback)
    bundle = build_bundle(tables, coverage=coverage)
    write_bundle(bundle, args.output)
    print(json.dumps({'output': str(args.output), 'signature': bundle['signature']['algorithm'],
                      'tables': len(tables), 'coverage': coverage}, indent=1, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
