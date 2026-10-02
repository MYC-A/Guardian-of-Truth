"""§9.6 deferred comparison on the 24-case new-construction bank.

RULES FROZEN BEFORE ANY NEW RESULT IS VIEWED (in selection.json):
  - systems: C0_J_control (official V0 JUDGE_SYSTEM, mistral — the original
    primary judge), D_V1_gptoss, D_V1_gemma (repaired calibrated contract);
  - binary mapping: label 1 -> ERROR, label 0 -> NO_ERROR; INVALID/missing ->
    UNKNOWN which counts correct on clean and miss on error, always reported
    separately; no threshold tuning on these results;
  - primary metrics: TP/FP/FN/TN, P/R/F1 per system + paired transitions vs
    C0_J_control on the same cases; abstention counted separately;
  - the shortlist's multi-call variants (EJ pipelines, Gk3 majority, cross)
    are bank-level results and are NOT re-measured here (budget ceiling);
  - Gk3 majority rule (bank-level, pre-fixed): majority of the 3 valid
    samples; fewer than 2 valid samples -> UNKNOWN; a 1-1-1 split -> UNKNOWN.
Round-robin per case so a budget stop leaves complete case triples.
"""
import argparse
import json
import time

from modular_common import Budget, BudgetStop, HERE, RESULTS, append, sha, source_sha, write

FOLDER = RESULTS / 'deferred_pilot'
BANK = HERE / 'dataset' / 'deferred_bank'
SYSTEMS = ['C0_J_control', 'D_V1_gptoss', 'D_V1_gemma']


def code_identity():
    from pathlib import Path
    here = Path(__file__).resolve().parent
    files = ['deferred_pilot.py', 'role_prompts.py']
    return sha({f: sha((here / f).read_text(encoding='utf-8').encode()) for f in files})


def load_bank():
    manifest = json.loads((BANK / 'manifest.json').read_text(encoding='utf-8'))
    assert sha((BANK / 'input.jsonl').read_bytes()) == manifest['input_sha256'], 'deferred_input_changed'
    rows = [json.loads(l) for l in (BANK / 'input.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len({r['id'] for r in rows}) == len(rows), 'duplicate ids'
    return rows, manifest


def prepare():
    rows, manifest = load_bank()
    prepared = {
        'schema': 'deferred-comparison/1', 'status': 'FROZEN_BEFORE_RUN', 'phase': 'reviewer_repair',
        'ids': [r['id'] for r in rows], 'systems': SYSTEMS,
        'frozen_rules': {
            'binary_mapping': 'label1->ERROR, label0->NO_ERROR; INVALID/missing->UNKNOWN counts correct-on-clean miss-on-error, reported separately',
            'no_tuning': 'no thresholds or majority rules are adjusted on these results',
            'primary_metrics': 'TP/FP/FN/TN P/R/F1 per system + paired transitions vs C0_J_control',
            'shortlist_note': 'multi-call variants (EJ/Gk3/cross) are bank-level; not re-measured within the ceiling',
            'gk3_majority_rule_bank_level': 'majority of 3 valid samples; <2 valid -> UNKNOWN; 1-1-1 split -> UNKNOWN',
        },
        'bank_manifest': {'n': manifest['n'], 'counts': manifest['counts'],
                          'input_sha256': manifest['input_sha256'],
                          'gold_sha256': manifest['gold_sha256']},
        'code_sha256': code_identity(),
        'gold_access': 'runner never reads author gold; post-run scorer only',
        'forecast': {'attempts': '24 cases x 3 systems = 72 + reasks'},
    }
    prepared['source_sha256'] = {r['id']: source_sha(r) for r in rows}
    selection = FOLDER / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('deferred_freeze_changed_use_versioned_recovery')
    else:
        write(selection, prepared)
    return rows, prepared


def run(*, prepare_only=True):
    rows, prepared = prepare()
    if prepare_only:
        print(json.dumps({'state': 'PREPARED_NO_INFERENCE', 'n': len(rows)}))
        return
    import llm as llm_mod
    import role_prompts as RP
    from judge import JUDGE_SYSTEM, build_judge_user, validate_vote
    from structural_v02 import parse_case_v02
    budget = Budget('reviewer_repair')
    llm = budget.install()
    journal = FOLDER / 'predictions.jsonl'
    done = set()
    if journal.exists():
        for line in journal.read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            done.add((r['system'], r['id']))
    ctxs = {r['id']: parse_case_v02(r['id'], r['prompt'], r['response']) for r in rows}

    def call(system, model, system_prompt, user, ctx, cid):
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user}]
        attempts = []
        for i in range(2):
            answer = llm.chat(model, messages, max_tokens=2000, temperature=0,
                              json_mode=True, transport_retries=0,
                              caller=f'modular/deferred/{system}/{i}')
            attempts.append({'content': answer.get('content'),
                             'cached': bool(answer.get('cached')),
                             'usage': answer.get('usage') or {},
                             'error': answer.get('error'),
                             'error_type': answer.get('error_type'),
                             'elapsed_s': answer.get('elapsed'),
                             'request_sha256': sha({'model': model, 'messages': messages})})
            content = answer.get('content')
            if content is None:
                return attempts, None, False, 'no_content'
            try:
                vote = llm_mod.extract_json(content)
            except Exception:
                vote = None
            valid, reason = validate_vote(vote, ctx) if vote is not None else (False, 'unparseable')
            if valid or i == 1:
                return attempts, vote, valid, reason
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content":
                 f"Technical validation failed: {reason}. Fix the JSON fields, keeping your semantic assessment. Return JSON only."}]
        return attempts, None, False, 'unreachable'

    try:
        for row in rows:  # round-robin: complete case triples before moving on
            cid = row['id']
            ctx = ctxs[cid]
            for system in SYSTEMS:
                if (system, cid) in done:
                    continue
                began = time.monotonic()
                if system == 'C0_J_control':
                    model = llm.DEFAULT_MISTRAL_MODEL
                    user, trim = build_judge_user(ctx)
                    attempts, vote, valid, reason = call(system, model, JUDGE_SYSTEM, user, ctx, cid)
                    contract = 'V0_official_judge'
                elif system == 'D_V1_gptoss':
                    model = 'gpt-oss:20b'
                    user = json.dumps({"sources": {"policy": ctx.policy_text, "history": ctx.prompt_raw,
                                                   "catalog": ctx.system, "response": ctx.response_raw},
                                       "target": ctx.response_raw}, ensure_ascii=False)
                    attempts, vote, valid, reason = call(system, model, RP.DIRECT_V1, user, ctx, cid)
                    contract = 'V1_calibrated'
                else:
                    model = 'gemma4:31b'
                    user = json.dumps({"sources": {"policy": ctx.policy_text, "history": ctx.prompt_raw,
                                                   "catalog": ctx.system, "response": ctx.response_raw},
                                       "target": ctx.response_raw}, ensure_ascii=False)
                    attempts, vote, valid, reason = call(system, model, RP.DIRECT_V1, user, ctx, cid)
                    contract = 'V1_calibrated'
                append(journal, {'system': system, 'id': cid,
                                 'source_sha256': source_sha(row),
                                 'code_sha256': prepared['code_sha256'],
                                 'model': model, 'contract': contract,
                                 'valid': valid, 'reason': reason,
                                 'label': vote.get('label') if isinstance(vote, dict) else None,
                                 'vote': vote, 'calls': attempts,
                                 'wall_seconds': time.monotonic() - began})
                done.add((system, cid))
                write(FOLDER / 'status.json', {'state': 'RUNNING', 'done': len(done),
                                               'total': len(rows) * len(SYSTEMS),
                                               'budget': budget.snapshot()})
        write(FOLDER / 'status.json', {'state': 'SUCCEEDED', 'done': len(done),
                                       'total': len(rows) * len(SYSTEMS),
                                       'budget': budget.snapshot()})
    except BudgetStop as exc:
        write(FOLDER / 'status.json', {'state': 'BUDGET_STOP', 'reason': str(exc), 'done': len(done),
                                       'total': len(rows) * len(SYSTEMS), 'budget': budget.snapshot()})
    except Exception as exc:
        write(FOLDER / 'status.json', {'state': 'FAILED', 'error_type': type(exc).__name__,
                                       'done': len(done), 'budget': budget.snapshot()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    run(prepare_only=not args.run)
