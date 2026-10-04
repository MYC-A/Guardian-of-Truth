"""Post-hoc selective native chronology guard on saved contextual decisions.

No model calls, semantic predicate mapping, entity-name dictionaries or repairs.
Future evidence downgrades a decision to UNKNOWN, never proves ERROR/NO_ERROR.
"""
from copy import deepcopy
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
from pilot import read, write, inputs, HERE, make_graph
from score import metrics


def future_native_sources(graph, evidence_ids):
    if not graph.targets:
        return []
    tid = next(iter(graph.targets))
    permitted = set(graph._allowed_prior(tid))
    return [sid for sid in evidence_ids if sid in graph.store.sources
            and graph.store.sources[sid]['document'] == 'response'
            and graph.store.sources[sid]['kind'] in ('call', 'result') and sid not in permitted]


def evaluate(out, prediction_file):
    predictions = read(prediction_file)
    source_rows = {r['id']: r for r in inputs(HERE / 'fixtures/inputs.jsonl')}
    gold = read(HERE / 'fixtures/gold.json')
    changes, before, after, guarded = [], [], [], []
    for row in predictions:
        if row['arm'] != 'A0' or row['failure']:
            continue
        g = make_graph(source_rows[row['id']])
        future = future_native_sources(g, row['result'].get('evidence_ids', []))
        new = deepcopy(row)
        previous = row['result']['verdict']
        if future and previous != 'UNKNOWN':
            new['result']['verdict'] = 'UNKNOWN'
            new['result']['chronology_guard'] = {'cause': 'EVIDENCE_AFTER_FIRST_TARGET', 'source_ids': future}
            changes.append({'id': row['id'], 'before': previous, 'after': 'UNKNOWN',
                            'gold': gold[row['id']]['verdict'], 'source_ids': future})
        guarded.append(new)
        before.append({'gold': gold[row['id']]['verdict'], 'predicted': previous})
        after.append({'gold': gold[row['id']]['verdict'], 'predicted': new['result']['verdict']})
    result = {'mode': 'POST_HOC_DIAGNOSTIC_AFTER_PRIMARY_AND_CONTEXTUAL_RESULTS',
              'before': metrics(before), 'after': metrics(after), 'changes': changes,
              'new_http': 0, 'semantic_completeness_proven': False,
              'limitations': ['Future sources might be irrelevant citations; guard conservatively abstains.',
                              'No entity joins or unknown effects are inferred.',
                              'Independent prospective family holdout is required before promotion.']}
    write(out / 'chronology_guard_diagnostic.json', result)
    write(out / 'chronology_guard_predictions.json', guarded)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True); p.add_argument('--predictions', type=Path, required=True)
    args = p.parse_args()
    import json
    print(json.dumps(evaluate(args.out, args.predictions)))
