"""Post-inference audit of saved receipts; never changes verdicts or calls models."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
from pilot import read, write, HERE, make_graph, registry, admit, decode_json
from contracts import Discovery


def raw_reply(out, request):
    path = out / 'raw' / (request['request_sha256'] + '.json')
    if not path.exists():
        return None
    record = read(path)
    if record['status'] != 'OK':
        return None
    choice = record['provider_response'].get('choices', [{}])[0]
    text = choice.get('message', {}).get('content')
    if not isinstance(text, str) or choice.get('finish_reason') != 'stop':
        return None
    value, valid = decode_json(text)
    return value if valid and isinstance(value, dict) else None


def audit(out, predictions):
    rows = read(predictions)
    raw_inputs = {r['id']: r for r in [json.loads(s) for s in (HERE / 'fixtures/inputs.jsonl').read_text(encoding='utf-8').splitlines()]}
    gold = read(HERE / 'fixtures/gold.json')
    stages = Counter()
    inventory_admissions = {}
    discoveries = {}
    for row in rows:
        stages[row['arm'], 'PREDICTIONS'] += 1
        if row['failure']:
            stages[row['arm'], row['failure'].split(':')[0] + ':' + row['failure'].split(':')[-1].split('\n')[0]] += 1
        for observation in row['observations']:
            admission = observation.get('admission')
            if admission:
                task = next((q['task'] for q in row['requests'] if q['request_sha256'] == observation['request_sha256']), '?')
                key = (row['arm'], task, observation['request_sha256'])
                inventory_admissions[key] = admission
        g = make_graph(raw_inputs[row['id']]); reg = registry(raw_inputs[row['id']], g)
        for request in row['requests']:
            if request['task'] not in ('DISCOVER', 'REVERSE'):
                continue
            data = raw_reply(out, request)
            if data:
                try:
                    value = admit(Discovery, data, reg)
                except (ValueError, KeyError, TypeError):
                    continue
                ids = set(s for c in value['candidates'] for s in c['policy_ids'] + c['exception_ids'])
                discoveries.setdefault(row['id'], {})[request['task']] = {'ids': sorted(ids), 'reply': value}
    additions = []
    for cid, d in discoveries.items():
        forward = set(d.get('DISCOVER', {}).get('ids', []))
        reverse = set(d.get('REVERSE', {}).get('ids', []))
        needed = set(gold[cid]['required_policy_ids'])
        additions.append({'id': cid, 'forward_ids': sorted(forward), 'reverse_ids': sorted(reverse),
                          'additional_ids': sorted(reverse - forward),
                          'additional_required_ids': sorted((reverse - forward) & needed),
                          'forward_missing_required_ids': sorted(needed - forward),
                          'union_missing_required_ids': sorted(needed - forward - reverse),
                          'metric': 'GOLD_SOURCE_SELECTION_NOT_SEMANTIC_NORM_COMPLETENESS'})
    schema = Counter()
    for (arm, task, _), result in inventory_admissions.items():
        schema[arm, task, 'ACCEPTED' if result['valid'] else 'REJECTED'] += 1
    result = {'pipeline_events': [{'arm': a, 'cause': c, 'count': n} for (a, c), n in stages.items()],
              'unique_graph_admissions': [{'arm': a, 'task': t, 'status': s, 'count': n} for (a, t, s), n in schema.items()],
              'source_discovery_additions': additions,
              'source_recovery_cases': sum(bool(r['additional_required_ids']) for r in additions),
              'new_http': 0, 'does_not_certify_semantic_support': True}
    write(out / 'stage_audit.json', result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True); p.add_argument('--predictions', type=Path)
    args = p.parse_args()
    r = audit(args.out, args.predictions or args.out / 'predictions_A0_A1_A2_A3.json')
    print(json.dumps({k: r[k] for k in ('unique_graph_admissions', 'source_recovery_cases', 'new_http')}))
