"""Input-only replay route selection; neither B inference nor quality scores."""
import json
from pathlib import Path
from collections import Counter
from modular_common import HERE, RESULTS, load_input, source_sha, sha, write
from negative_routing import primary_vote, route, matched_random


def run(root):
    inputs = {r['id']: r for r in load_input()}
    controls = list(map(json.loads, (root / 'control_dev/predictions.jsonl').read_text(encoding='utf-8').splitlines()))
    records, negatives = [], []
    for record in controls:
        row = inputs[record['id']]
        if source_sha(row) != record['source_sha256']:
            raise ValueError('primary_replay_input_mismatch')
        decision = primary_vote(record['output'])
        routed = route(row, decision)
        records.append({'id': row['id'], 'primary_decision': decision, 'routing': routed})
        if decision == 'NO_ERROR':
            negatives.append(row)
    count = sum(r['routing']['negative_review'] for r in records)
    selected = matched_random(negatives, count)
    ablations = {key: [r['id'] for r in records if r['primary_decision'] == 'NO_ERROR' and r['routing']['isolated_signals'][key] is True]
                 for key in ('pairing', 'changing_scoped_observations', 'temporal_literals', 'sample_instability', 'native_judge_nli')}
    report = {'scope': 'Measured routing decisions on ARCHIVED PRIMARY J, not downstream B quality or FN recovery',
        'protocol_sha256': sha((HERE / 'negative_routing_protocol.json').read_bytes()), 'gold_opened': False,
        'new_api_attempts': 0, 'n': len(records), 'primary_counts': dict(Counter(r['primary_decision'] for r in records)),
        'extra_negative_review_count': count, 'extra_negative_review_fraction': count / len(negatives) if negatives else None,
        'random_count_matched': count, 'random_ids': [r['id'] for r in negatives if source_sha(r) in selected],
        'isolated_trigger_ids': ablations, 'per_case': records,
        'quality_limits': ['New B calls not run. Both missed-error recovery and resulting false alarms remain unmeasured.',
                           'Source/time triggers were designed after observing DEV failures; no unseen-data gain claimed.',
                           'No same-input sampled uncertainty supplied to this replay; missing signals stay UNAVAILABLE.']}
    write(root / 'routing_replay.json', report)
    print(json.dumps({k: report[k] for k in ('n', 'primary_counts', 'extra_negative_review_count', 'extra_negative_review_fraction', 'new_api_attempts')}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=RESULTS)
    run(parser.parse_args().root)
