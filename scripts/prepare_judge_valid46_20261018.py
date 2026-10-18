"""Extract the entire seen valid46 set; verify exact original Parquet input order.

No selection by model outputs. Gold stays in a separate aligned sidecar.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from scripts.judge_submission import read_input
from scripts.prepare_judge_eval_data_20261018 import sha, write_json, write_jsonl


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--parquet', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    csv.field_size_limit(2**31-1)
    manifest = json.loads((a.source / 'MANIFEST.json').read_bytes())
    for name in ('inputs.csv', 'labels.jsonl'):
        if sha((a.source / name).read_bytes()) != manifest['files'][name]['sha256']:
            raise ValueError('FROZEN_PARENT_CHANGED: ' + name)
    rows = read_input(a.source / 'inputs.csv')
    gold = [json.loads(x) for x in (a.source / 'labels.jsonl').read_bytes().splitlines()]
    if len(rows) != len(gold):
        raise ValueError('PARENT_ALIGNMENT')
    selected = []
    for i, (r, g) in enumerate(zip(rows, gold)):
        if g['position'] != i or r['id'] != g['id']:
            raise ValueError('PARENT_ALIGNMENT')
        if g['domain'] == 'valid46':
            selected.append((r, dict(g, parent_position=i, position=len(selected))))
    original = read_input(a.parquet)
    if len(selected) != 46 or [(r['prompt'], r['response']) for r, _ in selected] != [
            (r['prompt'], r['response']) for r in original]:
        raise ValueError('NOT_EXACT_VALID46_IN_ORIGINAL_ORDER')
    a.out.mkdir(parents=True, exist_ok=False)
    with (a.out / 'inputs.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'prompt', 'response'], lineterminator='\n')
        writer.writeheader()
        writer.writerows(r for r, _ in selected)
    write_jsonl(a.out / 'labels.jsonl', [g for _, g in selected])
    result = dict(schema='guardian-valid46-extract-v1', rows=46,
        positive=sum(g['label'] for _, g in selected),
        purpose='SEEN_REGRESSION_ONLY; overlaps regression_seen397 completely',
        original_parquet_sha256=sha(a.parquet.read_bytes()),
        original_source_pairs_and_order_verified=True,
        parent_manifest_sha256=sha((a.source / 'MANIFEST.json').read_bytes()),
        files={name: dict(bytes=(a.out / name).stat().st_size, sha256=sha((a.out / name).read_bytes()))
               for name in ('inputs.csv', 'labels.jsonl')})
    write_json(a.out / 'MANIFEST.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
