"""Live HTTP layout boundaries and exhausted-budget behavior, no inference.

Structural outcomes are NOT scores against semantic author labels. This
script never increases a budget and skips the budget probe if it changed.
"""
import json
from modular_common import HERE, RESULTS, Budget, sha, write
from http_cli_probe import request


def main():
    folder = HERE / 'dataset/long_context_v2'
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    blob = (folder / 'input.jsonl').read_bytes()
    if sha(blob) != manifest['splits']['input']:
        raise ValueError('frozen_long_input_mismatch')
    rows = list(map(json.loads, blob.decode().splitlines()))
    out = RESULTS / 'service_long_v2_probes'
    out.mkdir(parents=True, exist_ok=True)
    budget = Budget()
    before = budget.snapshot()
    health_before = request('/health')
    results = []
    for row in rows:
        response = request('/v1/check', {'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response'],
                                        'config_id': 'modular-structural-v1'})
        assert response['cost']['actual_api_attempts'] == 0
        size = len(row['prompt']) + len(row['response'])
        if size > 12000:
            assert response['decision'] == 'UNKNOWN' and 'context_limit_no_truncation' in response['unknown_reasons']
        else:
            assert 'context_limit_no_truncation' not in response['unknown_reasons']
            assert response['coverage']['source_complete']
            assert response['modules'][0]['payload']['policy']
        results.append({'id': row['id'], 'characters': size, 'source_sha256': response['source_sha256'],
            'config_sha256': response['config_sha256'], 'decision': response['decision'],
            'basis': response['basis'], 'unknown_reasons': response['unknown_reasons'],
            'trace_id': response['trace_id'], 'elapsed_seconds': response['elapsed_seconds']})
    # No new provider attempt is allowed for this operational test. The first
    # cold request reserves >700 tokens; <=333 remain in the original ledger.
    guard = {'status': 'SKIPPED_LEDGER_CHANGED'}
    if 0 <= budget.limits['max_logical_tokens'] - before['logical_tokens'] <= 333:
        row = rows[0]
        response = request('/v1/check', {'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response'],
                                        'config_id': 'modular-r0-v1'})
        assert response['decision'] == 'UNKNOWN' and response['degraded']
        assert any(reason.startswith('resource_guard/') for reason in response['unknown_reasons'])
        assert response['cost']['actual_api_attempts'] == 0
        guard = {'status': 'ACTUAL_HTTP_BUDGET_GUARD_NO_PROVIDER_CALL', 'response': response}
    after = Budget().snapshot()
    assert after['actual_api_attempts'] == before['actual_api_attempts']
    receipt = {'scope': 'Actual live HTTP, layout/source/length and resource boundary only; no new inference quality',
        'manifest_sha256': sha((folder / 'manifest.json').read_bytes()), 'health_before': health_before,
        'health_after': request('/health'), 'ready': request('/ready'), 'n': len(results),
        'within_limit': sum(r['characters'] <= 12000 for r in results),
        'above_limit_UNKNOWN': sum(r['characters'] > 12000 and r['decision'] == 'UNKNOWN' for r in results),
        'new_api_attempts': after['actual_api_attempts'] - before['actual_api_attempts'],
        'exhausted_budget_probe': guard, 'results': results}
    write(out / 'receipt.json', receipt)
    print(json.dumps({k: receipt[k] for k in ('n', 'within_limit', 'above_limit_UNKNOWN', 'new_api_attempts')}))


if __name__ == '__main__':
    main()
