"""Live registration/resource-guard check; never an adaptive quality claim."""
from modular_common import RESULTS, Budget, load_input, write
from http_cli_probe import request


def main():
    configs = request('/v1/configs')
    assert 'modular-negative-adaptive-v1' in configs['configs']
    budget = Budget()
    before = budget.snapshot()
    if not 0 <= budget.limits['max_logical_tokens'] - before['logical_tokens'] <= 333:
        raise RuntimeError('budget_changed_skip_inference_probe')
    row = load_input(ids=['dev_inclusive_timezone::02'])[0]
    result = request('/v1/check', {'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response'],
                                  'config_id': 'modular-negative-adaptive-v1'})
    assert result['decision'] == 'UNKNOWN' and result['degraded']
    assert result['cost']['actual_api_attempts'] == 0
    assert any(r.startswith('resource_guard/') for r in result['unknown_reasons'])
    after = budget.snapshot()
    assert before['actual_api_attempts'] == after['actual_api_attempts']
    receipt = {'scope': 'Live config registration/resource guard; primary/B inference and adaptive quality not run',
        'health': request('/health'), 'config_registered': True, 'response': result,
        'budget': {k: after[k] for k in ('actual_api_attempts', 'logical_tokens', 'pending_reservations')}}
    write(RESULTS / 'adaptive_http_probe.json', receipt)
    print({'registered': True, 'decision': result['decision'], 'new_api_attempts': 0})


if __name__ == '__main__':
    main()
