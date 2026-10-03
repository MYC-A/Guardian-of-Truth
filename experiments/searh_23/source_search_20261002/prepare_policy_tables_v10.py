"""Build all exact compiler requests from original inputs, without inference."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.source_search.store import SourceStore
from guardian_truth.policy_table.compile import request
from guardian_truth.policy_table.segment import policy_hash, enum_catalog, clauses


def prepare():
    inputs = ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl'
    groups = defaultdict(list)
    for line in inputs.read_text(encoding='utf-8').splitlines():
        row = json.loads(line); groups[policy_hash(SourceStore(row))].append(row)
    output = ROOT / 'outputs/searh_23/v10/compiler_preparation'
    output.mkdir(parents=True, exist_ok=True)
    records, inventory = [], []
    for key, rows in sorted(groups.items()):
        stores = [SourceStore(row) for row in rows]
        catalog = enum_catalog(stores)
        inventory.append({'policy_sha256': key, 'cases': len(rows), 'clause_count': len(clauses(stores[0])),
            'tools': len(catalog['tools']), 'paths': len(catalog['paths']),
            'unwitnessed_paths': sorted(set(catalog['paths']) - set(catalog['path_witnesses']))})
        for sample_index in range(3):
            messages = request(stores, sample_index)
            encoded = json.dumps(messages, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            records.append({'policy_sha256': key, 'sample_index': sample_index,
                'request_sha256': hashlib.sha256(encoded).hexdigest(), 'request_utf8_bytes': len(encoded),
                'model': 'gpt-oss:120b', 'reasoning_effort': 'medium', 'messages': messages})
    (output / 'requests.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
    summary = {'status': 'PREPARED_NO_MODEL_CALLS_NOT_COMPILED', 'api_calls': 0, 'requests': len(records),
        'source_inputs_file_sha256': hashlib.sha256(inputs.read_bytes()).hexdigest(), 'policies': inventory,
        'total_request_utf8_bytes': sum(r['request_utf8_bytes'] for r in records),
        'limitation': 'Confirmation and current datetime slots have no code-bound source witness yet; conditions using them cannot become DECISIVE.'}
    (output / 'inventory.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return summary


if __name__ == '__main__': print(json.dumps(prepare(), ensure_ascii=True))
