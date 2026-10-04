"""Read-only, post-freeze diagnostics; never sends HTTP or changes selectors."""
import hashlib
import json
from pathlib import Path
from experiments.retrieval_bakeoff_v1.runner import references
from experiments.retrieval_bakeoff_v1.scoring import CATEGORIES, score_reference, unique, covered, span_identity

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/retrieval_bakeoff_v1'

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def all_sources(p):
    return p['read_sources'] + p['current_targets'] + p['declarations']

def main():
    seal = read(OUT / 'model_inputs_seal.json')
    for name, expected in seal['files'].items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == expected, name
    refs = references()
    plan = read(OUT / 'model_plan.json')
    result = {'model_input_seal': 'PASS', 'official_s2g': 'OFFICIAL_S2G_NOT_EXECUTED',
              'implementation': 'S2G_INSPIRED_API_BASED', 'cases': []}
    for spec in plan['cases']:
        index = spec['index']
        ref = refs[spec['case_id']]
        initial = read(OUT / 'offline_packets' / f"{index:02d}_{plan['selection']['best']}_k8_t20000.json")['packet']
        required = unique([u for category in CATEGORIES.values() for u in ref.get(category, [])])
        arms = {}
        for arm in ('S0', 'S1', 'S2'):
            file = OUT / 's2g_packets' / f'{index:02d}_{arm}.json'
            if not file.exists():
                arms[arm] = {'status': 'NO_ADMITTED_SOURCE_PACKET'}
                continue
            p = read(file)
            sources = all_sources(p)
            new_required = [u for u in required if covered(u, sources) and not covered(u, all_sources(initial))]
            assert len(set(p['selected_ids'])) == len(p['selected_ids']) <= 12
            assert p['cost']['source_token_upper_bound'] <= 20000
            for s in sources:
                # Text/offset checks independent of retrieval's integrity assertion.
                catalog = read(OUT / 'catalogs' / f'{index:02d}.json')
                candidates = catalog['sources'] + catalog['current_targets'] + catalog['declarations']
                assert any(s['source_id'] == c['source_id'] and s == c for c in candidates), s['source_id']
            arms[arm] = {'status': 'SOURCE_INTEGRITY_PASS', 'reads': len(p['selected_ids']),
                         'new_distinct_reads_vs_seed': len(set(p['selected_ids']) - set(initial['selected_ids'])),
                         'source_utf8_bound': p['cost']['source_token_upper_bound'],
                         'seed_retained': set(initial['selected_ids']) <= set(p['selected_ids']),
                         'score': score_reference(ref, p),
                         'new_required_units': [list(span_identity(u)) for u in new_required],
                         'new_required_count': len(new_required),
                         'gap_diagnostics': p.get('gap_diagnostics')}
        gap_path = OUT / 's2g_gap_results' / f'{index:02d}.json'
        result['cases'].append({'id': spec['case_id'], 'index': index, 'arms': arms,
                               'gap': read(gap_path) if gap_path.exists() else None})
    ledger = read(OUT / 'ledger.json')
    result['usage'] = {'actual_inference_http': len(ledger),
                       'known_tokens': sum(x['known_tokens'] for x in ledger.values()),
                       'charged_tokens': sum(x['charged_tokens'] for x in ledger.values()),
                       'unknown_usages': sum(x['unknown_usage'] for x in ledger.values())}
    assert result['usage']['actual_inference_http'] <= 18
    assert result['usage']['charged_tokens'] <= 130000
    (OUT / 's2g_source_metrics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for c in result['cases']:
        print(c['index'], c['gap']['status'] if c['gap'] else None,
              {k: {x: v.get(x) for x in ('reads', 'new_required_count', 'seed_retained')} for k,v in c['arms'].items()})
    print(result['usage'])
    print('Actual per-request usage:', [(v['name'], v['known_tokens'], v.get('actual_model')) for v in ledger.values()])
    for c in result['cases']:
        print('Packet details:', c['index'], {k: (v.get('source_utf8_bound'),
              v.get('score', {}).get('complete_evidence_set_success'),
              v.get('score', {}).get('categories', {}).get('history', {}).get('found'))
              for k, v in c['arms'].items()})

if __name__ == '__main__':
    main()
