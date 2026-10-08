"""Freeze all46 paired runtime requests from exact reconstructed B2 requests; no inference."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from scripts.qwen_source_visibility_audit import capture_request, REF, BASE
from experiments.guardian_binding.source_completion import complete
from guardian_truth.integrated import reviewer
from guardian_truth.integrated.transport import sha


def prepare(row, record):
    captured = capture_request(row, record)
    if captured is None:
        raise ValueError('NO_FROZEN_REVIEW_REQUEST')
    control, _, key = captured
    packet = json.loads(control['messages'][1]['content'])
    augmented, receipt = complete(row, packet)
    treatment = copy.deepcopy(control)
    if receipt['sources_added'] or receipt['sources_expanded']:
        treatment['messages'][1]['content'] = json.dumps(augmented, ensure_ascii=False, separators=(',', ':'))
        treatment['response_format']['json_schema']['schema'] = reviewer.schema(augmented)
    return dict(id=row['id'], control=control, completion=treatment,
                source_completion=receipt, archived_dispatched_key=key,
                control_sha256=sha(control), completion_sha256=sha(treatment),
                wire_identical=control == treatment)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--outdir', type=Path, required=True)
    a = ap.parse_args()
    if a.outdir.exists():
        raise ValueError('EXISTING_PHASE_REFUSED')
    def blob(path):
        return subprocess.check_output(['git', 'show', REF + ':' + path], cwd=ROOT)
    import pandas as pd
    original = pd.read_parquet(io.BytesIO(blob('valid.parquet')))
    rows = [dict(id=r.id, prompt=r.prompt, response=r.response) for r in original.itertuples()]
    records = {r['id']: r for r in map(json.loads, blob(BASE + 'valid46/B2_rep1.jsonl').splitlines())}
    prepared = [prepare(row, records[row['id']]) for row in rows]
    a.outdir.mkdir(parents=True)
    content = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in prepared).encode('utf-8')
    (a.outdir / 'runtime_requests.jsonl').write_bytes(content)
    manifest = dict(ref=REF, rows=len(prepared), no_gold_in_runtime=True,
                    changed_rows=sum(not r['wire_identical'] for r in prepared),
                    unique_requests=len({r[k] for r in prepared for k in ('control_sha256', 'completion_sha256')}),
                    runtime_sha256=hashlib.sha256(content).hexdigest(),
                    interpretation='Source completion only; cached neutral hypotheses identical in paired arms')
    (a.outdir / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(manifest)


if __name__ == '__main__':
    main()
