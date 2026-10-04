"""Offline prospective evaluation; inference never imports this scorer."""
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'src/guardian_truth').is_dir())
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
sys.path.insert(0, str(Path(__file__).parent.parent))
from pilot import digest, inputs, make_graph, read, sha, write
from score import metrics
from source_guard import future_native_sources


def evaluate(out):
    here = Path(__file__).parent
    protocol = read(out / 'protocol.json')
    seal = dict(protocol)
    if seal.pop('protocol_sha256') != digest(seal):
        raise ValueError('PROTOCOL_SEAL_CHANGED')
    for file, key in [('inputs.jsonl', 'input_sha256'), ('gold.json', 'gold_sha256')]:
        if sha(here / 'fixtures' / file) != protocol[key]:
            raise ValueError('FROZEN_FIXTURE_CHANGED')
    if sha(here.parent / 'source_guard.py') != protocol['guard_sha256']:
        raise ValueError('FROZEN_GUARD_CHANGED')
    predictions = read(out / 'predictions_A0.json')
    source_rows = {r['id']: r for r in inputs(here / 'fixtures/inputs.jsonl')}
    gold = read(here / 'fixtures/gold.json')
    if len(predictions) != len(gold) or {r['id'] for r in predictions} != set(gold):
        raise ValueError('INCOMPLETE_OR_DUPLICATE_PREDICTIONS')
    before, after, guarded, changes, failures = [], [], [], [], []
    for row in predictions:
        g = gold[row['id']]
        previous = row['result']['verdict']
        future = future_native_sources(make_graph(source_rows[row['id']]), row['result'].get('evidence_ids', []))
        new = deepcopy(row)
        if not row['failure'] and future and previous != 'UNKNOWN':
            new['result']['verdict'] = 'UNKNOWN'
            new['result']['chronology_guard'] = {'cause': 'EVIDENCE_AFTER_FIRST_TARGET', 'source_ids': future}
            changes.append({'id': row['id'], 'gold': g['verdict'], 'before': previous,
                            'after': 'UNKNOWN', 'source_ids': future})
        guarded.append(new)
        before.append({'id': row['id'], 'family': g['family'], 'gold': g['verdict'], 'predicted': previous})
        after.append({**before[-1], 'predicted': new['result']['verdict']})
        if previous != g['verdict'] or new['result']['verdict'] != g['verdict'] or row['failure']:
            failures.append({'id': row['id'], 'gold': g, 'original': row, 'guarded': new['result']})
    result = {'mode': 'PROSPECTIVE_GUARD_FALSIFICATION_AUTHOR_CONTROLLED_NOT_EXTERNALLY_BLINDED',
              'protocol_sha256': protocol['protocol_sha256'], 'scorer_sha256': sha(Path(__file__)),
              'original': metrics(before), 'guarded': metrics(after),
              'by_family': {f: {'original': metrics([r for r in before if r['family'] == f]),
                                'guarded': metrics([r for r in after if r['family'] == f])}
                            for f in sorted({r['family'] for r in before})},
              'changes': changes, 'inference_failures': dict(Counter(r['failure'] or 'NONE' for r in predictions)),
              'new_http_during_scoring': 0, 'semantic_completeness_proven': False}
    write(out / 'prospective_metrics.json', result)
    write(out / 'prospective_failures.json', failures)
    write(out / 'guarded_predictions.json', guarded)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    import json
    print(json.dumps(evaluate(parser.parse_args().out)))
