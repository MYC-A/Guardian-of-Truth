"""Separate DEV selection scoring. Does NOT score an unrun B decision."""
import json
from pathlib import Path
from modular_common import HERE, RESULTS, sha, write


def run(root):
    manifest = json.loads((HERE / 'dataset/manifest.json').read_text(encoding='utf-8'))
    blob = (HERE / 'dataset/dev_gold.jsonl').read_bytes()
    if sha(blob) != manifest['splits']['dev']['gold_sha256']:
        raise ValueError('dev_gold_identity_mismatch')
    gold = {r['id']: r for r in map(json.loads, blob.decode().splitlines())}
    replay = json.loads((root / 'routing_replay.json').read_text(encoding='utf-8'))
    if replay['protocol_sha256'] != sha((HERE / 'negative_routing_protocol.json').read_bytes()):
        raise ValueError('routing_protocol_changed_before_scoring')
    negatives = [r for r in replay['per_case'] if r['primary_decision'] == 'NO_ERROR']
    wrong = {r['id'] for r in negatives if gold[r['id']]['label'] == 1}
    selected = {r['id'] for r in negatives if r['routing']['negative_review']}
    random = set(replay['random_ids'])
    report = {'scope': 'DEV route inclusion only, not false-negative repair or new B quality',
        'human_reviewed': False, 'designed_after_dev_failure_inspection': True,
        'primary_NO_ERROR_count': len(negatives), 'wrong_primary_NO_ERROR_ids': sorted(wrong),
        'adaptive_selected_count': len(selected), 'adaptive_wrong_NO_ERROR_selected': sorted(selected & wrong),
        'random_selected_count': len(random), 'random_wrong_NO_ERROR_selected': sorted(random & wrong),
        'adaptive_clean_NO_ERROR_selected_count': len(selected - wrong),
        'random_clean_NO_ERROR_selected_count': len(random - wrong),
        'downstream_B_executed': False, 'quality_gain_proven': False,
        'limits': ['A selected miss may still be missed by B or produce a new false alarm on a clean case.',
                   'One observed DEV miss cannot establish generalization or significance over matched random.']}
    write(root / 'routing_selection_dev.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=RESULTS)
    run(parser.parse_args().root)
