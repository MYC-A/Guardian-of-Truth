"""Offline provenance/outcome comparison; no inferred gold, no model calls.

The second probe reuses observed authored tasks. This is an interface diagnostic,
not a blinded accuracy estimate. Preserve both original prediction journals.
"""
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'outputs/searh_23/source_search_20261002'


def summarize(name):
    directory = BASE / name
    status = json.loads((directory / 'status.json').read_text(encoding='utf-8'))
    if status['state'] != 'COMPLETE':
        raise ValueError('Only summarize a completed probe; preserve partial status.')
    rows = [json.loads(line) for line in
            (directory / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    cases = []
    for row in rows:
        record = row['review_record']
        try:
            raw_reviews = json.loads(record['content'])['reviews']
        except (ValueError, KeyError, TypeError):
            raw_reviews = None
        view = row.get('graph_view') or {}
        cases.append({
            'id': row['id'], 'strategy': row['strategy'],
            'decision': row['decision'], 'review_status': row.get('review_status'),
            'review_error': row.get('review_error'),
            'provenance_valid': 'reviews' in row,
            'raw_reviews': raw_reviews,
            'graph_roots': len(view.get('roots', [])),
            'traversal_count': len(view.get('traversals', [])),
            'provider_tokens': record.get('usage', {}).get('total_tokens'),
            'finish_reason': record.get('finish_reason'),
        })
    return {
        'scope': 'OBSERVED_AUTHOR_INTERFACE_DIAGNOSTIC_NOT_NEW_HELDOUT',
        'records': len(rows), 'distinct_authored_cases': len({r['id'] for r in rows}),
        'provenance_valid': sum(r['provenance_valid'] for r in cases),
        'decisions': dict(Counter(r['decision'] for r in rows)),
        'real_nonempty_graph_records': sum(r['graph_roots'] > 0 for r in cases),
        'new_http_attempts': rows[-1]['budget_after']['actual_api_attempts'] -
                             rows[0]['budget_before']['actual_api_attempts'],
        'known_provider_tokens': rows[-1]['budget_after']['known_provider_tokens'] -
                                 rows[0]['budget_before']['known_provider_tokens'],
        'final_budget': rows[-1]['budget_after'],
        'cases': cases,
    }


if __name__ == '__main__':
    result = {name: summarize(name) for name in
              ('review_graph_probe_v1', 'review_ids_probe_v2')}
    path = BASE / 'review_ids_probe_v2/interface_diagnostic.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: {a: b for a, b in v.items() if a not in ('cases', 'final_budget')}
                      for k, v in result.items()}, ensure_ascii=False))
