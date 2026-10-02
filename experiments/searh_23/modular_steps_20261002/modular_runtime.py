"""Separate experimental service runtime; original R0 remains untouched.

No auxiliary proposal is promoted as a proof of full source semantics.
Replay is an explicit operational profile, never a fresh model measurement.
"""
import copy
import json
import time
import uuid
from modular_common import Budget, BudgetPhaseConflict, BudgetStop, HERE, ROOT, RESULTS, append, budget_phase, source_sha, sha
from module_contract import ModuleResult

CONFIGS = {
    'modular-structural-v1': 'Structural v0.2 + source graph, no semantic NO_ERROR certificate.',
    'modular-replay-v1': 'Exact archived C0 input+output for HTTP transport verification, no new inference.',
    'modular-r0-v1': 'Original R0 with shared pilot resource guard.',
    'modular-source-bound-r0-v1': 'Original R0 routing, strict independent B source interface.',
    'modular-source-bound-always-v1': 'Independent strict B also reviews primary NO_ERROR; not yet measured.',
    'modular-negative-adaptive-v1': 'Strict B additionally reviews primary NO_ERROR on fixed source/time hazards; downstream quality unmeasured.',
    'modular-g2-v1': 'Selected source graph -> original J -> original independent B.',
    'modular-g2-linear-v1': 'Same selected source facts, linear view -> original J -> B.',
    'modular-g2-calculations-v1': 'Linked source graph + exact ISO ordering hints -> J -> strict B. Unmeasured candidate.',
    'modular-atoms-v1': 'Original R0 -> automatic target/explanation atoms -> B advisory audit.',
    'modular-system-v2-v1': 'Automatic SystemV2 Steps2-4 + linked graph advisory -> original J -> independent B.',
}
_budget = None
_llm = None


def config_identity(config):
    import subprocess
    import llm
    revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    return sha({'revision': revision, 'config': config, 'B': llm.DEFAULT_MISTRAL_MODEL,
        'protocol': json.loads((HERE / 'protocol.json').read_text()),
        'module_sources': {p.name: sha(p.read_bytes()) for p in HERE.glob('*.py')}})


def guarded_llm():
    """Single shared budget for runner and runtime (user bug 2026-10-02 §4).

    install() is idempotent per ledger: when the runner already installed a
    same-phase budget (system_v2_pilot → modular_runtime.check), this reuses
    that exact instrumentation layer instead of wrapping the already-wrapped
    transport. _budget is pinned to the LIVE OWNER published by install(),
    so begin_request/end_request/snapshot act on the object that actually
    meters the calls — never on a shadow copy whose per-request limits would
    not bind. A phase mismatch surfaces as BudgetPhaseConflict.
    """
    global _budget, _llm
    if _llm is None:
        _llm = Budget(budget_phase()).install()
        _budget = getattr(_llm, '_budget_layer_owner', _budget)
    return _llm


def base(config):
    from runtime import GuardianServiceRuntime
    return GuardianServiceRuntime(config)


def check(payload, config, *, inject_auxiliary_failure=False):
    if config not in CONFIGS:
        raise KeyError(config)
    began = time.monotonic()
    row = {'id': payload.get('case_id', 'unnamed'), 'prompt': payload['prompt'], 'response': payload['response']}
    identity = source_sha(row)
    out = {'case_id': row['id'], 'config_id': config, 'trace_id': str(uuid.uuid4()),
           'config_sha256': config_identity(config),
           'source_sha256': identity, 'decision': 'UNKNOWN', 'basis': 'coverage_gap',
           'findings': [], 'modules': [], 'degraded': False, 'unknown_reasons': [],
           'coverage': {'source_complete': True, 'semantic_completeness_proven': False},
           'cost': {'actual_api_attempts': 0, 'logical_tokens': 0}}
    def finish():
        out['elapsed_seconds'] = time.monotonic() - began
        append(RESULTS / 'modular_service/audit.jsonl', out)
        return out
    if len(row['prompt']) + len(row['response']) > 12000:
        out.update(degraded=True, unknown_reasons=['context_limit_no_truncation'])
        return finish()
    from evidence_views import graph_for
    graph = graph_for(row)
    out['modules'].append(ModuleResult('source-graph/1', 'ADVISORY', row['response'], identity,
        'MECHANICAL_SOURCE_SPANS', coverage=graph['coverage'],
        limitations=['Observed payloads and chronology do not establish current truth or effect semantics.'], payload=graph).json())
    if config == 'modular-replay-v1':
        journal = RESULTS / 'control_dev/predictions.jsonl'
        matches = [r for r in map(json.loads, journal.read_text().splitlines()) if r['source_sha256'] == identity] if journal.exists() else []
        if len(matches) != 1:
            out.update(degraded=True, unknown_reasons=['no_unique_exact_archived_input'])
            return finish()
        cached = copy.deepcopy(matches[0]['output'])
        out.update(decision=cached['decision'], basis='ARCHIVED_JUDGED_REPLAY_NOT_NEW_INFERENCE',
                   findings=cached.get('findings', []), archived_runtime=cached)
        out['cost']['replayed_original_usage'] = cached.get('cost', cached.get('usage'))
        return finish()
    if config == 'modular-structural-v1':
        measured = base('structural-v02').check(payload)
        out.update(decision=measured['decision'], basis=measured.get('basis', 'STRUCTURAL_OR_UNKNOWN'),
                   findings=measured.get('findings', []), original_runtime=measured)
        return finish()
    llm = guarded_llm()
    before = _budget.snapshot()
    _budget.begin_request(max_api_attempts=20)
    try:
        advisory = None
        if inject_auxiliary_failure:
            raise RuntimeError('injected_auxiliary_failure_not_provider_measurement')
        if config == 'modular-system-v2-v1':
            from v2_pipeline import run
            advisory = run(llm, llm.DEFAULT_MISTRAL_MODEL, row)
        if config == 'modular-g2-calculations-v1':
            from typed_calculations import timestamps
            advisory = timestamps(row)
        if config in {'modular-g2-v1', 'modular-g2-linear-v1', 'modular-system-v2-v1', 'modular-g2-calculations-v1'}:
            from mechanism_pilots import graph_pass
            measured = graph_pass(llm, row, 'G2-linear' if config == 'modular-g2-linear-v1' else 'G2', additional_advisory=advisory,
                                  strict_review=config in {'modular-g2-calculations-v1', 'modular-system-v2-v1'})
        else:
            measured = base('modular-source-bound-r0-v1' if config == 'modular-negative-adaptive-v1' else
                            config if config.startswith('modular-source-bound-') else 'r0-service-v1').check(payload)
            if config == 'modular-negative-adaptive-v1':
                from negative_routing import followup
                measured = followup(row, measured)
            if config == 'modular-atoms-v1':
                from mechanism_pilots import atomic_pass
                advisory = atomic_pass(llm, row, measured)
        out.update(decision=measured['decision'], basis='JUDGED', findings=measured.get('findings', []), original_runtime=measured)
        if measured.get('degraded'):
            out.update(degraded=True, unknown_reasons=measured.get('degradation_reasons', ['original_runtime_degraded']))
        if advisory is not None:
            out['modules'].append(ModuleResult(config, 'ADVISORY', row['response'], identity,
                'MODEL_PROPOSED_PLUS_RELATIVE_NATIVE_COMPUTATION',
                assumptions=['Native inference is relative to automatically proposed contracts/claims.'],
                limitations=['Full policy, fact semantics and action inventory remain unproven.'], payload=advisory).json())
    except BudgetStop as exc:
        out.update(degraded=True, unknown_reasons=['resource_guard/' + str(exc)], basis='coverage_gap')
    except Exception as exc:
        out.update(degraded=True, unknown_reasons=['auxiliary_or_model_failure/' + type(exc).__name__], basis='coverage_gap')
    finally:
        _budget.end_request()
    after = _budget.snapshot()
    out['cost'] = {key: after[key] - before[key] for key in ('actual_api_attempts', 'logical_tokens', 'model_seconds')}
    return finish()
