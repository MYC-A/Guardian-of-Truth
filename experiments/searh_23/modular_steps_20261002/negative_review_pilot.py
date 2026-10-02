"""Four routing arms share exact archived primary J and one identical B query.

Prepare without inference. --run respects the original shared resource cap;
an extension must be explicitly approved and recorded before it can continue.
No gold, oracle or case-name routing. Raw B is journaled before aggregation.
"""
import copy
import json
from pathlib import Path
from modular_common import HERE, ROOT, RESULTS, Budget, BudgetStop, append, load_input, sha, source_sha, write
from negative_routing import primary_vote, route, matched_random

ARMS = ('strict_positive', 'strict_always', 'strict_source_adaptive', 'strict_matched_random')


def code_identity():
    paths = [HERE / name for name in ('negative_review_pilot.py', 'negative_routing.py', 'negative_routing_protocol.json')]
    paths += [ROOT / 'service/runtime.py', ROOT / 'service/configs/modular-source-bound-r0-v1.json',
              ROOT / 'experiments/searh_23/hybrid_service_v1/counterevidence.py']
    # Python normalizes source newlines on load; JSON whitespace is not a
    # setting. Raw prompt/history bytes remain separately hashed unchanged.
    return sha({p.relative_to(ROOT).as_posix(): sha(json.loads(p.read_text(encoding='utf-8')))
                if p.suffix == '.json' else sha(p.read_text(encoding='utf-8').encode()) for p in paths})


def prepare(root):
    path = root / 'control_dev/predictions.jsonl'
    controls = list(map(json.loads, path.read_text(encoding='utf-8').splitlines()))
    inputs = {r['id']: r for r in load_input()}
    if len({r['id'] for r in controls}) != len(controls):
        raise ValueError('duplicate_primary_input')
    negatives = []
    routes = {}
    for record in controls:
        row = inputs[record['id']]
        if record['source_sha256'] != source_sha(row):
            raise ValueError('primary_source_changed')
        decision = primary_vote(record['output'])
        routes[row['id']] = route(row, decision)
        if decision == 'NO_ERROR':
            negatives.append(row)
    count = sum(r['negative_review'] for r in routes.values())
    random = matched_random(negatives, count)
    prepared = {'schema': 'paired-negative-review/1', 'status': 'FROZEN_BEFORE_B_CALLS',
        'ids': [r['id'] for r in controls], 'arms': list(ARMS), 'code_sha256': code_identity(),
        'code_identity_normalization': 'UTF8 universal source newlines; semantic JSON config; exact input separately unchanged',
        'primary_archive_sha256': sha(path.read_bytes()),
        'source_sha256': {r['id']: source_sha(inputs[r['id']]) for r in controls},
        'routes': routes, 'matched_random_source_sha256': sorted(random),
        'B_protocol': 'source-bound-v2', 'B_model': 'env_mistral', 'B_max_tokens': 2000,
        'max_B_queries_before_technical_reasks': len(controls), 'primary_reused_not_new_inference': True,
        'same_B_query_shared_across_arms_not_independent_votes': True,
        'human_gold_reviewed': False, 'new_sealed_access': False}
    folder = root / 'negative_review_pilot_v4'
    selection = folder / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('negative_pilot_freeze_changed_use_versioned_recovery')
    else:
        write(selection, prepared)
    return prepared, controls, inputs, folder


def run(root, *, prepare_only=True):
    prepared, controls, inputs, folder = prepare(root)
    if prepare_only:
        print(json.dumps({'state': 'PREPARED_NO_INFERENCE', 'n': len(controls), 'arms': ARMS,
                          'maximum_unique_B_queries': len(controls)}))
        return
    budget = Budget()
    llm = budget.install()
    original_chat = llm.chat
    active_source = {}
    def raw_chat(model, messages, **kwargs):
        answer = original_chat(model, messages, **kwargs)
        # No headers, endpoint URLs, env or arbitrary provider exceptions.
        # Preserve the complete output before the author adapter's head limit.
        append(folder / 'raw_B_calls.jsonl', dict(active_source, model=model,
            request_sha256=sha({'model': model, 'messages': messages, 'parameters': kwargs}),
            raw={key: answer.get(key) for key in ('content', 'usage', 'cached', 'error', 'error_type', 'http_status')}))
        return answer
    llm.chat = raw_chat
    from structural_v02 import parse_case_v02
    from runtime import _judge_findings, load_config
    from counterevidence import collect_review, aggregate_review
    config = load_config('modular-source-bound-r0-v1')['stages']['counterevidence']
    shared_path, journal = folder / 'shared_B.jsonl', folder / 'predictions.jsonl'
    shared = {r['id']: r for r in map(json.loads, shared_path.read_text(encoding='utf-8').splitlines())} if shared_path.exists() else {}
    done = {(r['id'], r['arm']) for r in map(json.loads, journal.read_text(encoding='utf-8').splitlines())} if journal.exists() else set()
    try:
        for control in controls:
            row = inputs[control['id']]
            active_source.update(id=row['id'], source_sha256=source_sha(row))
            ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
            decision = prepared['routes'][row['id']]['primary_decision']
            primary_records = [r for s in control['output']['module_trace'] if s['module'] == 'judge' for r in s['records']]
            findings = _judge_findings(primary_records, ctx) if decision == 'ERROR' else []
            if decision == 'ERROR' and not findings:
                decision = 'UNKNOWN'
            if row['id'] not in shared:
                before = budget.snapshot()
                review = collect_review(config, ctx, findings, caller='modular/negative-paired')
                after = budget.snapshot()
                record = {'id': row['id'], 'source_sha256': source_sha(row), 'code_sha256': prepared['code_sha256'],
                    'resolved_B_model': llm.DEFAULT_MISTRAL_MODEL, 'review': review,
                    'cost': {k: after[k] - before[k] for k in ('actual_api_attempts', 'logical_tokens', 'model_seconds')}}
                append(shared_path, record)
                shared[row['id']] = record
            record = shared[row['id']]
            if record['source_sha256'] != source_sha(row) or record['code_sha256'] != prepared['code_sha256']:
                raise ValueError('shared_review_identity_mismatch')
            if record['resolved_B_model'] != llm.DEFAULT_MISTRAL_MODEL:
                raise ValueError('B_model_changed_use_versioned_recovery')
            for arm in ARMS:
                if (row['id'], arm) in done:
                    continue
                review_now = decision != 'NO_ERROR' or arm == 'strict_always' or (
                    arm == 'strict_source_adaptive' and prepared['routes'][row['id']]['negative_review']) or (
                    arm == 'strict_matched_random' and source_sha(row) in prepared['matched_random_source_sha256'])
                final, out_findings, reason = decision, copy.deepcopy(findings), 'PRIMARY_J_NOT_REVIEWED_BY_THIS_ARM'
                degraded = decision == 'UNKNOWN'
                if review_now:
                    final, out_findings, reason = aggregate_review(record['review'], decision, findings, ctx)
                    if not record['review']['valid']:
                        final, out_findings, degraded = 'UNKNOWN', [], True
                append(journal, {'id': row['id'], 'arm': arm, 'source_sha256': source_sha(row),
                    'config_sha256': prepared['code_sha256'], 'decision': final, 'degraded': degraded,
                    'findings': out_findings, 'reason': reason, 'primary_decision': decision,
                    'primary_reused_not_new_inference': True, 'B_used': review_now,
                    'B_shared_reference': {'id': row['id'], 'path': 'shared_B.jsonl', 'sha256': sha(record)} if review_now else None,
                    'cost_if_executed_alone': record['cost'] if review_now else {'actual_api_attempts': 0, 'logical_tokens': 0, 'model_seconds': 0}})
                done.add((row['id'], arm))
        write(folder / 'status.json', {'state': 'COMPLETED', 'done': len(done), 'total': len(controls) * len(ARMS), 'budget': budget.snapshot()})
    except BudgetStop as exc:
        write(folder / 'status.json', {'state': 'BUDGET_STOP', 'reason': str(exc), 'done': len(done),
                                     'total': len(controls) * len(ARMS), 'budget': budget.snapshot()})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=RESULTS)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    run(args.root, prepare_only=not args.run)
