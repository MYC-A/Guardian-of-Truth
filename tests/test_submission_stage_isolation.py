"""Optional exceptions retain independent decisions through real parser/review.

These deterministic clients test processing boundaries, not inference quality.
"""
import json
from copy import deepcopy

import pytest

from guardian_truth.integrated.transport import StaticClient
from guardian_truth.repair import v5
from guardian_truth.verification.pipeline import packet_for


def fixture(monkeypatch):
    row = dict(prompt='⟦SYSTEM⟧\nNever call lookup with order_id forbidden-9.\n'
                      '⟦USER⟧\nLook up another order.',
               response='⟦ASSISTANT · ход 1⟧\n'
                        '→ TOOL_CALL lookup: {"order_id":"forbidden-9"}\n'
                        '→ TOOL_CALL lookup: {"order_id":"allowed-2"}')
    packet = packet_for(row, 20000)
    assert len(packet['current_targets']) == 2

    def reply(req):
        p = json.loads(req['messages'][1]['content'])
        return json.dumps(dict(decision='NO_ERROR',
                               regulated_action=dict(target_id=p['current_targets'][0]['source_id'], description='Lookup'),
                               applicable_norms=[], supporting_evidence=[], exception_analysis='',
                               reason='No violation proposed.', open_questions=[]))

    client = StaticClient(reply, 'test')
    monkeypatch.setattr(v5.ems, 'trigger', lambda *a: dict(quant=['fixture'], fallback=[]))
    monkeypatch.setattr(v5.df, 'trigger', lambda *a: [])
    monkeypatch.setattr(v5, 'ems_run', lambda *a: dict(candidates=[]))
    monkeypatch.setattr(v5, 'at_run', lambda *a: dict(candidates=[]))
    candidate = dict(origin='AT', target_id=packet['current_targets'][0]['source_id'],
                     requirement='Never call lookup with order_id forbidden-9.', reason='Forbidden ID requested.',
                     policy_source_ids=[packet['normative_sources'][0]['source_id']],
                     evidence_source_ids=[packet['current_targets'][0]['source_id']],
                     code_proven=False, certificate=False)
    return row, client, candidate


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in ('seconds', 'wall_seconds', 'model_seconds')}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def fail(*args, **kwargs):
    raise ValueError('private source data must not enter the error receipt')


def test_success_isolation_keeps_requests_and_decisions_unchanged(monkeypatch):
    row, client, _ = fixture(monkeypatch)
    normal = v5.run_v5(row, client, model='test', flags=v5.FIXES)
    calls = deepcopy(client.calls)
    client.calls.clear()
    snapshots = []
    isolated = v5.run_v5(row, client, model='test', flags=v5.FIXES,
                         tolerate_component_errors=True, on_primary=snapshots.append)
    assert client.calls == calls
    assert semantic(isolated) == semantic(normal)
    assert v5.decide(isolated) == v5.decide(normal) == (0, None)
    assert len(snapshots) == 2
    assert 'A_adm2' not in snapshots[0]
    assert snapshots[0]['base_error'] is False
    assert snapshots[1]['A_adm2']['decision'] == 'NO_ERROR'
    snapshots[1]['A']['steps'].clear()
    assert isolated['A']['steps']


@pytest.mark.parametrize('component', ['DF4', 'Ems', 'AT'])
def test_component_exception_does_not_erase_valid_primary(monkeypatch, component):
    row, client, _ = fixture(monkeypatch)
    if component == 'DF4':
        monkeypatch.setattr(v5.df, 'trigger', lambda *a: ['fixture'])
        monkeypatch.setattr(v5.df5, 'run', fail)
    else:
        monkeypatch.setattr(v5, 'ems_run' if component == 'Ems' else 'at_run', fail)
    with pytest.raises(ValueError):
        v5.run_v5(row, client, model='test')
    snapshots = []
    out = v5.run_v5(row, client, model='test', tolerate_component_errors=True, on_primary=snapshots.append)
    assert out['A_adm2']['decision'] == snapshots[-1]['A_adm2']['decision'] == 'NO_ERROR'
    assert out['components'][component] == dict(tag=component, admission='TECHNICAL_FAILURE',
                                               verification_status='TECHNICAL_FAILURE',
                                               error_type='ValueError', candidates=[])
    assert out['pool'] == [] and v5.decide(out) == (0, None)


def test_failed_ems_does_not_erase_supported_other_component(monkeypatch):
    row, client, candidate = fixture(monkeypatch)
    monkeypatch.setattr(v5, 'ems_run', fail)
    monkeypatch.setattr(v5, 'at_run', lambda *a: dict(candidates=[candidate]))
    monkeypatch.setattr(v5, 'verify', lambda *a, **k: dict(verdict='SUPPORTED', verification_status='SUPPORTED'))
    out = v5.run_v5(row, client, model='test', tolerate_component_errors=True)
    assert out['components']['Ems']['candidates'] == []
    binary, accusation = v5.decide(out)
    assert binary == 1 and accusation['origin'] == 'AT'
    assert len(out['pool']) == 1


def test_failed_verifier_does_not_erase_supported_next_candidate(monkeypatch):
    row, client, candidate = fixture(monkeypatch)
    second = dict(candidate, target_id='t1', reason='Independent later hypothesis.')
    monkeypatch.setattr(v5, 'at_run', lambda *a: dict(candidates=[candidate, second]))
    checked = []

    def verifier(*args, **kwargs):
        c = args[2]
        checked.append(c)
        if c == candidate:
            fail()
        return dict(verdict='SUPPORTED', verification_status='SUPPORTED')

    monkeypatch.setattr(v5, 'verify', verifier)
    out = v5.run_v5(row, client, model='test', flags={'pool'}, tolerate_component_errors=True)
    assert checked == [candidate, second]
    assert [p['verification_status'] for p in out['pool']] == ['TECHNICAL_FAILURE', 'SUPPORTED']
    assert v5.decide(out)[0] == 1 and v5.decide(out)[1]['target_id'] == 't1'


def test_completed_primary_is_observed_before_trigger_failure(monkeypatch):
    row, client, _ = fixture(monkeypatch)
    monkeypatch.setattr(v5.ems, 'trigger', fail)
    snapshots = []
    with pytest.raises(ValueError):
        v5.run_v5(row, client, model='test', on_primary=snapshots.append, tolerate_component_errors=True)
    assert len(snapshots) == 2 and snapshots[-1]['A_adm2']['decision'] == 'NO_ERROR'


def test_cb_exception_isolated_per_binding(monkeypatch):
    row, client, candidate = fixture(monkeypatch)
    monkeypatch.setattr(v5.confirm, 'trigger', lambda *a: ['broken', 'valid'])
    cb_candidate = dict(candidate, origin='CB')

    def cb(*args):
        if args[3] == 'broken':
            fail()
        return dict(candidates=[cb_candidate])

    monkeypatch.setattr(v5, 'cb_run', cb)
    monkeypatch.setattr(v5, 'verify', lambda *a, **k: dict(verdict='SUPPORTED', verification_status='SUPPORTED'))
    out = v5.run_v5(row, client, model='test', with_cb=True, tolerate_component_errors=True)
    assert out['components']['CB']['runs'][0]['admission'] == 'TECHNICAL_FAILURE'
    assert v5.decide(out, cb=True)[0] == 1


@pytest.mark.parametrize('guard_error', [False, True])
def test_first_snapshot_carries_only_established_guard_authority(monkeypatch, guard_error):
    row, client, _ = fixture(monkeypatch)
    original_review = v5.review

    def reviewed(*args, **kwargs):
        primary = original_review(*args, **kwargs)
        primary['guard']['established_error'] = guard_error
        # Deliberately unadmitted model ERROR must not acquire authority merely
        # because this field is present before packet/admission processing.
        primary['final_decision'] = 'ERROR'
        primary['binary'] = 1
        return primary

    monkeypatch.setattr(v5, 'review', reviewed)
    monkeypatch.setattr(v5, 'packet_for', fail)
    snapshots = []
    with pytest.raises(ValueError):
        v5.run_v5(row, client, model='test', on_primary=snapshots.append)
    assert len(snapshots) == 1
    assert snapshots[0]['base_error'] is guard_error
    assert 'A_adm2' not in snapshots[0]


def test_supported_candidate_snapshot_survives_later_queue_exception(monkeypatch):
    row, client, candidate = fixture(monkeypatch)
    ems_candidate = dict(candidate, origin='Ems', kind='SEMANTIC')
    malformed_later = dict(candidate, origin='UNSUPPORTED_ORIGIN')
    monkeypatch.setattr(v5, 'ems_run', lambda *a: dict(candidates=[ems_candidate]))
    monkeypatch.setattr(v5, 'at_run', lambda *a: dict(candidates=[malformed_later]))
    monkeypatch.setattr(v5, 'verify', lambda *a, **k: dict(verdict='SUPPORTED', verification_status='SUPPORTED'))
    snapshots = []
    with pytest.raises(KeyError):
        v5.run_v5(row, client, model='test', tolerate_component_errors=True, on_primary=snapshots.append)
    saved = snapshots[-1]
    assert len(saved['pool']) == 1
    assert saved['pool'][0]['verification_status'] == 'SUPPORTED'
    assert v5.decide(saved)[0] == 1
    assert saved['components']['AT']['candidates'] == [malformed_later]
