"""Real public46 ingestion/navigation acceptance; no gold, no model calls."""
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'service'),
    str(ROOT / 'experiments/searh_23/hybrid_service_v1'),
    str(ROOT / 'experiments/searh_23/three_architectures')]
from guardian_truth.source_search import SourceStore, calculate
from guardian_truth.source_search.calculations import literals
from structural_v02 import parse_case_v02
from unittest.mock import patch
import runtime

OUT = ROOT / 'outputs/searh_23/source_search_20261002'


def rows():
    csv.field_size_limit(10**9)
    with (ROOT / 'experiments/searh_23/three_architectures/data/public46.csv').open(
            newline='', encoding='utf-8') as stream:
        return [{k: r[k] for k in ('id', 'prompt', 'response')} for r in csv.DictReader(stream)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records, indexes = [], {}
    for row in rows():
        store = SourceStore(row)
        ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
        snapshot = store.snapshot()
        # Full source archive is immutable and separate from compact/model view.
        archive = OUT / 'sources' / (store.source_sha256 + '.json')
        archive.parent.mkdir(exist_ok=True)
        archive.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True), encoding='utf-8')
        compact_bytes = len(json.dumps(store.compact(), ensure_ascii=False).encode())
        record = {'id': row['id'], 'source_sha256': store.source_sha256,
            'input_chars': len(row['prompt']) + len(row['response']),
            'source_events': len(store.sources) - 2, 'facts': len(store.facts),
            'tool_results': sum(e.kind == 'result' for e in store.history_events),
            'text_tool_results': sum(e.kind == 'result' and not e.json_valid for e in store.history_events),
            'indexed_text_tool_results': sum(s['kind'] == 'result' and not s['json_valid'] for s in store.sources.values() if s['kind'] != 'raw'),
            'unique_quotes': len(store.quotes), 'compact_bytes': compact_bytes,
            'structural_ran': True, 'structural_hits': len(ctx.structural_hits),
            'source_roundtrip_exact': snapshot['raw'] == {'prompt': row['prompt'], 'response': row['response']}}
        assert record['source_roundtrip_exact']
        assert record['text_tool_results'] == record['indexed_text_tool_results']
        records.append(record); indexes[row['id']] = store
    retail = next(store for name, store in indexes.items() if name.startswith('retail__29::'))
    traversal = retail.traverse({'field': 'product_id', 'value': '6679515468'}, strategy='BFS',
                                max_depth=1, max_nodes=80)
    # Preserve the literal type: public product IDs can be integers or strings.
    if len(traversal['items']) == 1:
        traversal = retail.traverse({'field': 'product_id', 'value': 6679515468}, strategy='BFS',
                                    max_depth=1, max_nodes=80)
    orders = sorted({str(r['entity']['value']) for r in traversal['items'] if r['entity']['field'] == 'order_id'})
    assert '#W2575533' in orders and '#W7181492' in orders, orders
    banking = {}
    for suffix in ('051', '003'):
        store = next(store for name, store in indexes.items() if 'banking' in name and f'{suffix}::' in name)
        result = store.search_sources('Content', source_types=['result'])
        banking[suffix] = {'results': result, 'text_results_indexed': sum(s['kind'] == 'result' and not s['json_valid']
            for s in store.sources.values() if s['kind'] != 'raw')}
        assert banking[suffix]['text_results_indexed'] > 0
        assert result['total'] > 0
        if suffix == '051':
            account_sources = [sid for sid, source in store.sources.items()
                if source['kind'] == 'result' and 'current_balance: $3,000.00' in store.text(sid)
                and 'credit_limit: $4,000.00' in store.text(sid)]
            assert len(account_sources) == 1
            found = literals(store, account_sources[0], 'decimal')
            operands = [next(r for r in found if r['literal'] == value) for value in ('3,000.00', '4,000.00')]
            percentage = calculate(store, 'percentage', [{k: r[k] for k in ('source_id', 'kind')} for r in operands])
            assert percentage['result'] == '75.00'
            banking[suffix]['source_bound_percentage'] = percentage
    airline = next(store for name, store in indexes.items() if name.startswith('airline__7::'))
    dates = []
    for sid, source in airline.sources.items():
        if source['kind'] != 'raw' and source['document'] == 'prompt':
            dates.extend(literals(airline, sid, 'date'))
    distinct = list({r['literal']: r for r in dates if r['kind'] == 'date'}.values())
    assert len(distinct) >= 2
    arithmetic = calculate(airline, 'compare', [{k: r[k] for k in ('source_id', 'kind')} for r in distinct[:2]])
    assert arithmetic['status'] == 'COMPUTED'
    cfg = json.loads((ROOT / 'service/configs/source-search-v1.json').read_text())
    class DisabledModel:
        def snapshot(self):
            return {'actual_api_attempts': 0, 'known_provider_tokens': 0, 'unknown_usage_upper_bounds': 0}
        def __call__(self, messages):
            return {'status': 'UNAVAILABLE', 'reason': 'MECHANICAL_ACCEPTANCE_MODEL_DISABLED'}
    with patch.object(runtime, 'load_config', return_value=cfg):
        service = runtime.GuardianServiceRuntime('source-search-v1', audit_path=OUT / 'service_audit.jsonl')
    service._source_transport = DisabledModel()
    service_receipts = []
    for row in rows():
        result = service.check({'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response']})
        assert result['coverage']['source_index_complete']
        assert result['coverage']['structural'] in ('clean_scan', 'confirmed_hit')
        assert result['source_store']['raw'] == {'prompt': row['prompt'], 'response': row['response']}
        service_receipts.append({'id': row['id'], 'decision': result['decision'], 'coverage': result['coverage']})
    report = {'scope': 'REAL_INPUT_MECHANICAL_ACCEPTANCE_NOT_LLM_QUALITY', 'model_calls': 0,
        'cases': records, 'passed': len(records), 'second_order': {'orders': orders, 'traversal': traversal},
        'service_chain': service_receipts,
        'banking': banking, 'airline': {'distinct_date_literals': len(distinct), 'calculation': arithmetic},
        'limitations': ['Order association is not an authorization proof.',
            'Airline date pair is a source arithmetic check, not automatic relevant-clock selection.',
            'The judge/controller semantic quality remains unmeasured.']}
    (OUT / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'accepted': len(records), 'orders': orders,
        'bank_text_sources': {k: v['text_results_indexed'] for k, v in banking.items()},
        'airline_distinct_dates': len(distinct), 'model_calls': 0}))


if __name__ == '__main__':
    main()
