"""Deferred comparison completion (assignment 2026-10-02 §3.4).

Runs the six previously unmeasured deferred-bank goals
(def_effect_new::05, def_mixed::00, def_mixed::01, def_perm_new::06,
def_perm_new::07, def_mixed::02) on the SAME three systems and the SAME
frozen rules as the §9.6 comparison (selection.json in deferred_pilot/),
on the new phase modular_all_noft_20261002 (reviewer_repair is closed).
The gold repair (def_mixed::01 provenance, manifest v2) happened BEFORE this
run; the runner never reads author gold.

Versioned recovery pattern: the old deferred_pilot.py + its freeze stay
untouched; this is a separate frozen runner with its own journal folder.
"""
import argparse
import json
import time

from modular_common import Budget, BudgetStop, HERE, RESULTS, append, sha, source_sha, write

FOLDER = RESULTS / 'deferred_completion'
BANK = HERE / 'dataset' / 'deferred_bank'
SYSTEMS = ['C0_J_control', 'D_V1_gptoss', 'D_V1_gemma']
IDS = ['def_effect_new::05', 'def_mixed::00', 'def_mixed::01',
       'def_perm_new::06', 'def_perm_new::07', 'def_mixed::02']


def code_identity():
    from pathlib import Path
    here = Path(__file__).resolve().parent
    files = ['deferred_completion_pilot.py', 'role_prompts.py']
    out = {f: sha((here / f).read_text(encoding='utf-8').encode()) for f in files}
    return sha(out)


def load_bank():
    manifest = json.loads((BANK / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest.get('version') == 2, 'expected repaired bank v2'
    assert sha((BANK / 'input.jsonl').read_bytes()) == manifest['input_sha256'], 'input changed'
    rows = [json.loads(l) for l in (BANK / 'input.jsonl').read_text(encoding='utf-8').splitlines()]
    return [r for r in rows if r['id'] in IDS], manifest


def prepare():
    rows, manifest = load_bank()
    old_sel = json.loads((RESULTS / 'deferred_pilot' / 'selection.json').read_text(encoding='utf-8'))
    prepared = {
        'schema': 'deferred-completion/1', 'status': 'FROZEN_BEFORE_RUN',
        'phase': 'modular_all_noft_20261002',
        'ids': IDS, 'systems': SYSTEMS,
        'frozen_rules': old_sel['frozen_rules'],
        'bank_manifest': {'n': manifest['n'], 'version': manifest['version'],
                          'counts': manifest['counts'],
                          'input_sha256': manifest['input_sha256'],
                          'gold_sha256': manifest['gold_sha256']},
        'continuation_of': {
            'selection': 'deferred_pilot/selection.json (rules frozen before any result)',
            'measured_then': '18 complete triples of 24 (round-robin, BUDGET_STOP at 300/300)',
            'unmeasured_then': IDS,
            'systems_identical': True,
            'gold_v2_note': 'def_mixed::01 provenance repaired before this run; label unchanged',
        },
        'code_sha256': code_identity(),
        'gold_access': 'runner never reads author gold; post-run scorer only',
        'forecast': {'attempts': '6 cases x 3 systems = 18 + at most one schema-repair reask each'},
    }
    prepared['source_sha256'] = {r['id']: source_sha(r) for r in rows}
    selection = FOLDER / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('deferred_completion_freeze_changed_use_versioned_recovery')
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
    budget = Budget('modular_all_noft_20261002')
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
                              caller=f'modular/deferred_completion/{system}/{i}')
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
        for row in rows:
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
