"""Label-free V11 source inventory. Never imports or reads benchmark gold."""
from collections import defaultdict, Counter
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.source_search.store import SourceStore
from guardian_truth.policy_table.segment import policy_hash, enum_catalog, clauses
from guardian_truth.policy_table_v11.catalog import normalize_catalog
from guardian_truth.policy_table_v11.witness import explicit_confirmation, current_datetime, timeline
from dataclasses import asdict
import random

INPUTS = ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl'
OUTPUT = ROOT / 'outputs/searh_23/v11/preparation'

def groups():
    result = defaultdict(list)
    for line in INPUTS.read_text(encoding='utf-8').splitlines():
        row = json.loads(line); store = SourceStore(row); store.case_id = row['id']
        result[policy_hash(store)].append(store)
    return result

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def prepare():
    inventory = []
    for key, stores in sorted(groups().items()):
        catalog = normalize_catalog(stores)
        write(OUTPUT / (key + '.json'), {'policy_sha256': key,
            'clauses': clauses(stores[0]), 'catalog': catalog})
        inventory.append({'policy': key, 'cases': len(stores), 'clauses': len(clauses(stores[0])),
            'before_paths': len(enum_catalog(stores)['paths']), 'after_paths': len(catalog['paths']),
            'tools': len(catalog['tools']), 'roles': dict(Counter(t['role'] for t in catalog['tools'].values())),
            'numeric_ID_paths': [p for p in catalog['paths'] if p.startswith('state.') and __import__('re').search(r'\d{4}', p)]})
    write(OUTPUT / 'inventory.json', {'policies': inventory, 'gold_opened': False, 'api_calls': 0})
    return inventory


def witnesses():
    rows = []
    for key, stores in sorted(groups().items()):
        catalog = normalize_catalog(stores)
        for store in stores:
            for prefix, events in [('h', store.history_events), ('t', store.target_events)]:
                for i, event in enumerate(events):
                    if event.kind != 'call' or event.role != 'assistant' or event.name not in catalog['tools']:
                        continue
                    if catalog['tools'][event.name]['role'] == 'READ': continue
                    target = {'source_id': prefix + str(i), 'tool': event.name, 'arguments': event.value}
                    prior_text = [(sid, e) for sid, e in timeline(store, target) if e.kind == 'text' and e.role in ('assistant', 'user')]
                    rows.append({'case_id': store.case_id, 'policy': key, 'target': target,
                        'confirmation': asdict(explicit_confirmation(store, target)),
                        'time': asdict(current_datetime(store, target)),
                        'last_texts': [{'source_id': sid, 'role': e.role, 'text': e.text} for sid, e in prior_text[-3:]]})
    sample = random.Random(20261003).sample(rows, min(20, len(rows)))
    write(OUTPUT / 'witness_inventory.json', {'calls': rows, 'gold_opened': False})
    write(OUTPUT / 'witness_review_20.json', {'seed': 20261003, 'sample': sample,
        'review_status': 'PENDING_MANUAL_REVIEW', 'gold_opened': False})
    return {'calls': len(rows), 'confirmation_statuses': dict(Counter(r['confirmation']['status'] for r in rows)),
            'sample': sample}

if __name__ == '__main__':
    result = witnesses() if '--witnesses' in sys.argv else prepare()
    if isinstance(result, dict): result.pop('sample')
    print(json.dumps(result, ensure_ascii=False))
