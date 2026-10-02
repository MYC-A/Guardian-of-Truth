"""Actual loopback HTTP + CLI probes. Replay explicitly costs no new API.

Separate from fresh LLM quality and separately logged simulated failures.
"""
import json
from pathlib import Path
import subprocess
import urllib.request
from modular_common import HERE, ROOT, RESULTS, load_input, write


def request(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request('http://127.0.0.1:18092' + path, data=data,
        headers={'Content-Type': 'application/json'} if payload is not None else {})
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.load(response)


def main():
    out = RESULTS / 'service_probes'
    out.mkdir(parents=True, exist_ok=True)
    result = {'health': request('/health'), 'ready': request('/ready'), 'configs': request('/v1/configs'),
              'live_HTTP_not_TestClient': True, 'quality_scope': 'Archived exact-input replay and operational source/resource boundaries, not cold inference.'}
    rows = load_input(ids=['dev_latest::00', 'dev_latest::01', 'dev_refusal_inventory::00', 'dev_entity_binding::00'])
    result['case_results'] = []
    for row in rows:
        payload = {'case_id': row['id'], 'prompt': row['prompt'], 'response': row['response'], 'config_id': 'modular-replay-v1'}
        response = request('/v1/check', payload)
        assert response['basis'] == 'ARCHIVED_JUDGED_REPLAY_NOT_NEW_INFERENCE'
        result['case_results'].append(response)
    long_rows = [json.loads(r) for r in (HERE / 'dataset/long_context/input.jsonl').read_text().splitlines()]
    edge = next(r for r in long_rows if len(r['prompt']) + len(r['response']) > 12000)
    response = request('/v1/check', dict(case_id=edge['id'], prompt=edge['prompt'], response=edge['response']))
    assert response['decision'] == 'UNKNOWN' and 'context_limit_no_truncation' in response['unknown_reasons']
    result['long_boundary'] = response
    result['batch'] = request('/v1/check/batch', {'config_id': 'modular-replay-v1',
        'cases': [{'case_id': r['id'], 'prompt': r['prompt'], 'response': r['response']} for r in rows[:2]]})
    input_path = out / 'cli_input.jsonl'
    input_path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    command = ['/workspace/guardian/modular_venv/bin/python', str(HERE / 'modular_cli.py'), '--input', str(input_path),
               '--output', str(out / 'cli_output.jsonl'), '--config', 'modular-replay-v1', '--csv', str(out / 'cli_output.csv')]
    for _ in range(2):
        subprocess.run(command, cwd=ROOT, check=True)
    assert len((out / 'cli_output.jsonl').read_text().splitlines()) == len(rows)
    result['CLI_resume_without_duplicate_rows'] = True
    from modular_runtime import check
    r = rows[0]
    failed = check({'case_id': r['id'], 'prompt': r['prompt'], 'response': r['response']},
                   'modular-r0-v1', inject_auxiliary_failure=True)
    assert failed['decision'] == 'UNKNOWN' and failed['degraded']
    result['simulated_auxiliary_failure_not_real_provider_failure'] = failed
    restored = request('/v1/check', dict(case_id=r['id'], prompt=r['prompt'], response=r['response'], config_id='modular-replay-v1'))
    assert restored['decision'] == result['case_results'][0]['decision']
    result['after_simulated_failure_replay_restored'] = True
    write(out / 'receipt.json', result)
    print(json.dumps({'actual_HTTP_cases': len(rows), 'long_boundary': response['decision'], 'CLI_resume': True, 'simulated_failure': failed['decision']}))


if __name__ == '__main__':
    main()
