"""Prepare label-free generation inputs; missing prerequisites stay explicit."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from benchmarks.mutations_v10.generate import generate, save
from guardian_truth.source_search.store import SourceStore
from guardian_truth.policy_table.evaluate import load_table
from guardian_truth.policy_table.segment import policy_hash, enum_catalog


def prepare(output):
    path = ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl'
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    tables, formats = {}, {}
    for row in rows:
        store = SourceStore(row); key = policy_hash(store)
        table = load_table(store, ROOT / 'outputs/searh_23/policy_tables')
        if table is not None: tables[key] = table
        formats.setdefault(key, set()).update(field['format']
            for tool in enum_catalog([store])['tools'].values() for field in tool['arguments'].values() if field.get('format'))
    inputs, expectations, summary = generate(rows, tables)
    summary.update(original_inputs_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        original_inputs_rewritten=False, compiled_table_hashes=sorted(tables),
        actual_declared_formats_by_policy={key: sorted(values) for key, values in sorted(formats.items())},
        rule_local_negative_labels_authorized_by_user=True,
        no_model_frames_in_this_preparation=True,
        selection='POLICY_BALANCED_SEEDED_NO_LABEL_FILTER',
        original_negative_control_types_not_claimed='Formatting controls do not replace evidence of paraphrase or causal-permutation robustness.')
    save(output, inputs, expectations, summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/searh_23/v10/mutations_preparation')
    args = parser.parse_args()
    summary = prepare(args.output)
    print(json.dumps({key: summary[key] for key in ('status', 'mutants', 'policies', 'counts', 'actual_declared_formats_by_policy')}))
