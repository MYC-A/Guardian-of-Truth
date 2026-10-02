"""Input-only historical template census. Never opens any gold file.

Lexical normalization is deliberately mechanical, NOT logical equivalence.
Numbers, ID-like tokens and encountered catalog tool names are normalized;
connectives, negations, field names and truth values remain distinguishable.
"""
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from modular_common import HERE, ROOT, RESULTS, load_input, sha, write
from structural_v02 import parse_case_v02

TOKEN = re.compile(r'\b[A-Za-z_][\w.-]*\b|\d+(?:\.\d+)?|[^\w\s]', re.UNICODE)
ID = re.compile(r'(?=[\w.-]*[A-Za-z])(?=[\w.-]*\d)[\w.-]+\Z')
NUMBER = re.compile(r'\d+(?:\.\d+)?\Z')
HISTORICAL = (
    'experiments/searh_23/three_architectures/data/public46.csv',
    'experiments/searh_23/hybrid_service_v1/dataset/fresh_v1/dev_input.jsonl',
    'experiments/searh_23/hybrid_service_v1/dataset/fresh_v1/sealed_input.jsonl',
    'experiments/searh_23/system_research_v2/frozen/trajectories_v2/dev_inputs.json',
    'experiments/searh_23/system_research_v2/frozen/trajectories_v2/sealed_inputs.json',
    'benchmarks/theory_extraction_v1/input.jsonl',
    'benchmarks/theory_extraction_v1/b3_smoke_input.jsonl',
)


def signature(row):
    if 'prompt' in row and 'response' in row:
        ctx = parse_case_v02(str(row.get('id', row.get('case_id', 'input'))), row['prompt'], row['response'])
        policy, tools = ctx.policy_text, list(ctx.catalog.tools)
        source = row['prompt'] + '\0' + row['response']
    elif 'system_policy' in row and 'available_tools' in row:
        policy, tools = row['system_policy'], [t['name'] for t in row['available_tools']]
        source = json.dumps({k: row[k] for k in ('system_policy', 'available_tools', 'history', 'target_response')}, sort_keys=True)
    else:
        return None
    mapping = {name.lower(): 'tool_' + str(i) for i, name in enumerate(tools)}
    def norm(text):
        aliases = {}
        parts = []
        for token in TOKEN.findall(text.lower()):
            if token in mapping:
                token = mapping[token]
            elif ID.fullmatch(token):
                token = aliases.setdefault(token, 'id_' + str(len(aliases)))
            elif NUMBER.fullmatch(token):
                token = '<number>'
            parts.append(token)
        return parts
    policy_tokens = norm(policy)
    grams = {tuple(policy_tokens[i:i+5]) for i in range(max(0, len(policy_tokens)-4))}
    return {'normalized_input_sha256': sha(norm(source)), 'normalized_policy_sha256': sha(policy_tokens),
            'policy_5grams': grams, 'raw_input_sha256': sha(source.encode())}


def read(path):
    if path.suffix == '.csv':
        csv.field_size_limit(10000000)
        return list(csv.DictReader(path.open(encoding='utf-8-sig')))
    text = path.read_text(encoding='utf-8-sig')
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in text.splitlines()]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError('historical_input_not_list')
    return data


def run(root):
    old, files = [], []
    for name in HISTORICAL:
        path = ROOT / name
        if not path.exists():
            files.append({'path': name, 'status': 'MISSING'})
            continue
        records = read(path)
        signatures = [(r, signature(r)) for r in records]
        files.append({'path': name, 'status': 'READ_INPUT_ONLY', 'sha256': sha(path.read_bytes()),
                      'rows': len(records), 'unrecognized_layouts': sum(s is None for _, s in signatures)})
        old += [(name, str(r.get('id', r.get('case_id', i))), s) for i, (r, s) in enumerate(signatures) if s]
    fresh, records = [], []
    for split in ('dev', 'sealed'):
        for row in load_input(split):
            fresh.append((split, row['id'], signature(row)))
    for split, cid, s in fresh:
        full, policy, near = [], [], []
        for path, oid, o in old:
            ref = {'path': path, 'id': oid}
            if s['normalized_input_sha256'] == o['normalized_input_sha256']:
                full.append(ref)
            if s['normalized_policy_sha256'] == o['normalized_policy_sha256']:
                policy.append(ref)
            intersection = s['policy_5grams'] & o['policy_5grams']
            union = s['policy_5grams'] | o['policy_5grams']
            similarity = len(intersection) / len(union) if union else 0
            if similarity >= 0.65:
                near.append(dict(ref, policy_5gram_jaccard=similarity))
        records.append({'split': split, 'id': cid, 'normalized_input_sha256': s['normalized_input_sha256'],
            'normalized_policy_sha256': s['normalized_policy_sha256'], 'historical_full_overlap': full,
            'historical_policy_overlap': policy, 'historical_policy_near_overlap': near})
    by_policy = defaultdict(lambda: defaultdict(list))
    for r in records:
        by_policy[r['normalized_policy_sha256']][r['split']].append(r['id'])
    crossings = [dict(policy_hash=k, **v) for k, v in by_policy.items() if len(v) > 1]
    report = {'schema': 'historical-input-template-audit/1', 'gold_opened': False,
        'normalization': 'Tool names by catalog encounter; ID-like tokens by encounter; numeric literals collapsed; lowercased lexical tokens. Connectives/negation/truth values/field names retained.',
        'historical_files': files, 'historical_recognized_rows': len(old), 'fresh_rows': len(records),
        'historical_full_overlap_cases': sum(bool(r['historical_full_overlap']) for r in records),
        'historical_policy_overlap_cases': sum(bool(r['historical_policy_overlap']) for r in records),
        'historical_policy_near_overlap_cases': sum(bool(r['historical_policy_near_overlap']) for r in records),
        'dev_sealed_identical_normalized_policy_groups': crossings, 'per_case': records,
        'limits': ['Lexical non-overlap does not establish unseen logic or semantic independence.',
                   'Names of generators differ, but necessary/sufficient, Boolean and entity/time primitives are shared.',
                   'Five-word similarity is a review aid, not an entailment test. No model or solver gold is consulted.']}
    write(root / 'template_overlap_audit.json', report)
    print(json.dumps({k: report[k] for k in ('historical_recognized_rows', 'fresh_rows', 'historical_full_overlap_cases', 'historical_policy_overlap_cases', 'historical_policy_near_overlap_cases')}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=RESULTS)
    run(parser.parse_args().root)
