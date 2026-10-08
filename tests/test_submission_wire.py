"""Frozen B2 wire composition and real POSIX owned-process signal cleanup.

The lifecycle smoke launches harmless Python sleepers, never a model or GPU
request. Only health/props are stubbed; Popen, POSIX signals, wait and process
ownership remain real.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
PINNED_MODEL = 'qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459'


@pytest.mark.parametrize('status,response,expected', [
    ('NO_ERROR', 'Hello.', 0),
    ('ERROR', 'FORBIDDEN', 1),
])
def test_submission_preserves_frozen_b2_request_attempt_and_tag(status, response, expected):
    from experiments.guardian_addons.variants2 import Hook2
    from experiments.guardian_local_a100.run_local import VARIANTS
    from guardian_truth.integrated.transport import StaticClient
    from guardian_truth.repair.v5 import ARMS, run_v5
    from guardian_truth.submission.cli import MODEL, predict_one
    from guardian_truth.v6fix.pipeline import Layers, decide

    assert MODEL == PINNED_MODEL
    assert VARIANTS['B2'] == dict(pre='blind2', pre_max_tokens=3400)
    row = dict(id='ALIGNMENT_ONLY_MUST_NOT_ENTER_MODEL',
               prompt='⟦SYSTEM⟧\nNever write FORBIDDEN.',
               response='⟦ASSISTANT⟧\n' + response,
               label=1, explanation='GOLD_MUST_NOT_ENTER_MODEL')

    def reply(request):
        name = request['response_format']['json_schema']['name']
        if name == 'pre_analysis_neutral_v2':
            return json.dumps(dict(requirements=[], entities=[], computed_values=[],
                                   expected_actions=[], uncertainties=[]))
        if name == 'current_move_review':
            packet = json.loads(request['messages'][1]['content'])
            target = packet['current_targets'][0]['source_id']
            norms = [dict(policy_source_id=packet['normative_sources'][0]['source_id'],
                          interpretation='Never write FORBIDDEN.', modality='FORBID')] if status == 'ERROR' else []
            evidence = [dict(source_id=target, actor='assistant', role='current assertion',
                             fact='FORBIDDEN')] if status == 'ERROR' else []
            return json.dumps(dict(decision=status, regulated_action=dict(target_id=target, description='Current prose'),
                                   applicable_norms=norms, supporting_evidence=evidence, exception_analysis='',
                                   reason='Forbidden word written.' if status == 'ERROR' else 'Greeting allowed.',
                                   open_questions=[]))
        if name == 'turn_rules_context_v3':
            return json.dumps(dict(rules=[]))
        pytest.fail('unexpected inference stage: ' + name)

    # Exact composition from the measured run_local B2 arm; no submission code
    # supplies its configuration or result to the reference path.
    baseline = StaticClient(reply, PINNED_MODEL)
    hook = Hook2(baseline, 'blind2', PINNED_MODEL, original_row=row,
                 max_request_bytes=60000, max_tokens=3400)
    record = run_v5(row, hook, flags=ARMS['R_fix'], provider='local-llamacpp',
                    model=PINNED_MODEL, attempt=0, review_max_tokens=None)
    layer = Layers(baseline, PINNED_MODEL, budget=20000, attempts=(0, 1),
                   frules_max_tokens=700).findings(row)
    reference = decide(record, layer['findings'])

    deployed = StaticClient(reply, PINNED_MODEL)
    result = predict_one(row, deployed, Layers(deployed, PINNED_MODEL, budget=20000,
                                             attempts=(0, 1), frules_max_tokens=700))
    assert deployed.calls == baseline.calls
    assert result['binary'] == reference['binary'] == expected
    # Reviewer receipts include elapsed CPU/wall time even for a static client.
    # Timing is not part of the wire or semantic replay contract.
    def without_elapsed(value):
        if isinstance(value, dict):
            return {key: without_elapsed(child) for key, child in value.items()
                    if key not in ('seconds', 'wall_seconds', 'model_seconds')}
        if isinstance(value, list):
            return [without_elapsed(child) for child in value]
        return value
    assert without_elapsed(result['rec']) == without_elapsed(record)
    assert result['pre_steps'] == hook.log
    assert result['layer_trace'] == layer
    assert [(call['tag'], call['attempt'], call['request']['max_tokens']) for call in deployed.calls] == [
        ('pre_blind', 0, 3400), ('review', 0, 1700),
        ('turn_rules_context_v3', 0, 700), ('turn_rules_context_v3', 1, 700),
    ]
    wire = json.dumps(deployed.calls, ensure_ascii=False)
    assert 'ALIGNMENT_ONLY_MUST_NOT_ENTER_MODEL' not in wire
    assert 'GOLD_MUST_NOT_ENTER_MODEL' not in wire
    blind_view = json.loads(deployed.calls[0]['request']['messages'][1]['content'])
    assert 'current_targets' not in blind_view


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(os.name != 'posix', reason='POSIX signal ownership is exercised on Linux')
@pytest.mark.parametrize('signum', [signal.SIGTERM, signal.SIGINT])
def test_signal_stops_real_owned_child_and_preserves_foreign_process(tmp_path, signum):
    root = tmp_path / 'package'
    binary = root / 'runtime/llama/llama-server'
    binary.parent.mkdir(parents=True)
    binary.write_text(f'#!{sys.executable}\nimport time\ntime.sleep(600)\n', encoding='utf-8')
    binary.chmod(0o755)
    work = tmp_path / 'work'
    work.mkdir()
    ready = tmp_path / 'owned.pid'
    cli_source = Path(os.environ.get('GUARDIAN_SUBMISSION_CLI', ROOT / 'src/guardian_truth/submission/cli.py')).resolve()
    launcher = '''
import importlib.util, pathlib, sys, time
spec=importlib.util.spec_from_file_location('isolated_submission_cli',sys.argv[1])
cli=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
def metadata(url,payload=None,timeout=20,api_key=None):
    if url.endswith('/health'): return {'status':'ok'}
    return {'model_alias':cli.MODEL,'default_generation_settings':{'n_ctx':4096}}
cli.http_json=metadata
with cli.ModelServer(sys.argv[2],sys.argv[3],1,4096) as server:
    pathlib.Path(sys.argv[4]).write_text(str(server.process.pid),encoding='utf-8')
    while True: time.sleep(1)
'''
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    foreign = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'], env=env)
    owner = None
    owned_pid = None
    try:
        owner = subprocess.Popen([sys.executable, '-c', launcher, str(cli_source), str(root), str(work), str(ready)],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 15
        while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not ready.exists():
            if owner.poll() is None:
                owner.kill()
            out, error = owner.communicate(timeout=5)
            pytest.fail(f'owned child did not become ready: {out}\n{error}')
        owned_pid = int(ready.read_text(encoding='utf-8'))
        assert _alive(owned_pid)
        assert foreign.poll() is None
        owner.send_signal(signum)
        out, error = owner.communicate(timeout=15)
        assert owner.returncode == 128 + signum, out + error
        assert not _alive(owned_pid), f'owned child {owned_pid} survived signal {signum}'
        assert foreign.poll() is None, 'unrelated process was terminated'
    finally:
        if owner is not None and owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        if owned_pid is not None and _alive(owned_pid):
            os.kill(owned_pid, signal.SIGKILL)
        if foreign.poll() is None:
            foreign.terminate()
        foreign.wait(timeout=5)
