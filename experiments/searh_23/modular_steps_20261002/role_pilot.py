"""§8 role-matrix pilot runner (phase reviewer_repair).

Frozen 12-case bank (6 error + 6 clean, 12 logical groups, includes the
former B-FP cases). Arms (per assignment §8):
  D(model,V1)      direct judge, full original context, repaired contract
                   (mistral V0 reference = archived strict_always shared_B;
                   C0 primary reference = archived control_dev)
  EJ(e,j)          same/different model extracts then checks (Gemma->Gemma,
                   gpt-oss->gpt-oss self pipelines; cross pairs reuse cached
                   extractor requests)
  G3               Gemma counterevidence reviewer over the Gemma checker
                   verdicts (extractor/checker requests identical to
                   EJ_gemma_gemma -> served from cache)
  Gk3              Gemma direct, temperature 0.7, seeds 11/22/33
  BpmA             B-without-A (findings=[]) on the 6 error cases vs the
                   archived B-with-A answers (anchoring test)
Gold is opened post-run by the scorer only. Append-only journal with resume.
Every model call journals content/usage/cached/elapsed/seed/request hash.
"""
import argparse
import json
import time

from modular_common import Budget, BudgetStop, RESULTS, append, load_input, sha, source_sha, write

BANK = ['dev_necessary::00', 'dev_implication::00', 'dev_refusal_inventory::01',
        'dev_request_effect::00', 'dev_latest::00', 'dev_inclusive_timezone::02',
        'dev_unless::02', 'dev_negative_scope::02', 'dev_units::00',
        'dev_retry_commit::00', 'dev_latest::01', 'dev_refusal_inventory::00']
ERROR_IDS = BANK[:6]
FOLDER = RESULTS / 'role_pilot'
MODELS = {'mistral': None, 'gemma': 'gemma4:31b', 'gptoss': 'gpt-oss:20b',
          'nemotron': 'nemotron-3-nano:30b'}
GK3_SEEDS = (11, 22, 33)
GK3_TEMPERATURE = 0.7


def code_identity():
    from pathlib import Path
    here = Path(__file__).resolve().parent
    return sha({p.name: sha(p.read_text(encoding='utf-8').encode())
                for p in sorted(here.glob('role_*.py'))})


def model_of(llm, key):
    return MODELS[key] or llm.DEFAULT_MISTRAL_MODEL


def prepare():
    prepared = {'schema': 'role-pilot/1', 'status': 'FROZEN_BEFORE_RUN', 'ids': BANK,
        'error_ids': ERROR_IDS, 'phase': 'reviewer_repair',
        'models': {k: (v or 'env_mistral') for k, v in MODELS.items()},
        'gk3': {'seeds': list(GK3_SEEDS), 'temperature': GK3_TEMPERATURE},
        'arms': ['D_V1_mistral', 'D_V1_gemma', 'D_V1_gptoss', 'D_V1_nemotron',
                 'EJ_gemma_gemma', 'EJ_gptoss_gptoss', 'G3_counterevidence',
                 'Gk3_gemma', 'B_without_A', 'X_gemmaE_gptossJ', 'X_gptossE_gemmaJ'],
        'references': {'mistral_V0': 'negative_review_pilot_v4/shared_B.jsonl (archived B on official contract)',
                       'C0_primary': 'control_dev/predictions.jsonl (archived)'},
        'code_sha256': code_identity(),
        'forecast': {'attempts': 'D 4x12=48; EJ self 2x24=48; G3 +12 (E/J cached); '
                     'Gk3 36 (temp 0.7 vs D temp 0); BpmA +6; cross +24 = 174',
                     'note': 'budget guard active; at most one schema-repair reask per call'}}
    rows = load_input('dev', BANK)
    prepared['source_sha256'] = {r['id']: source_sha(r) for r in rows}
    selection = FOLDER / 'selection.json'
    if selection.exists():
        if json.loads(selection.read_text(encoding='utf-8')) != prepared:
            raise ValueError('role_pilot_freeze_changed_use_versioned_recovery')
    else:
        write(selection, prepared)
    return rows, prepared


def _sources_payload(ctx):
    return {"sources": {"policy": ctx.policy_text, "history": ctx.prompt_raw,
                        "catalog": ctx.system, "response": ctx.response_raw},
            "target": ctx.response_raw}


def _source_inventory(ctx):
    return [{"turn_id": t.turn_id, "role": t.role,
             "call_ids": [c.call_id for c in t.tool_calls],
             "result_ids": [r.result_id for r in t.tool_results]}
            for t in ctx.turns]


def call_json(llm, llm_mod, model, system, user, *, caller, validator,
              temperature=0.0, seed=None, max_tokens=2000):
    """One model call; at most ONE schema-repair reask, both counted.

    Returns (attempts, value, valid, reason). The validator runs between
    the calls so the reask only happens on a failed contract."""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]
    attempts = []
    for i in range(2):
        answer = llm.chat(model, messages, max_tokens=max_tokens,
                          temperature=temperature, json_mode=True,
                          transport_retries=0, seed=seed,
                          caller=f'{caller}/{i}')
        attempts.append({'content': answer.get('content'), 'cached': bool(answer.get('cached')),
                         'usage': answer.get('usage') or {}, 'error': answer.get('error'),
                         'error_type': answer.get('error_type'),
                         'elapsed_s': answer.get('elapsed'), 'seed': seed,
                         'temperature': temperature,
                         'request_sha256': sha({'model': model, 'messages': messages,
                                                'parameters': {'temperature': temperature, 'seed': seed}})})
        content = answer.get('content')
        if content is None:
            return attempts, None, False, 'no_content'
        try:
            value = llm_mod.extract_json(content)
        except Exception as exc:
            value = None
            reason = f'parse/{type(exc).__name__}'
        if value is None:
            valid, reason = False, 'unparseable_json'
        else:
            valid, reason = validator(value)
        if valid or i == 1:
            return attempts, value, valid, reason
        messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": f"Technical validation failed: {reason}. Fix the JSON fields, keeping your semantic assessment. Return JSON only."}]
    return attempts, None, False, 'unreachable'


def _vote_validator(ctx):
    from judge import validate_vote
    return lambda value: validate_vote(value, ctx)


def _proposal_validator(ctx):
    sources = {'policy': ctx.policy_text, 'history': ctx.prompt_raw, 'catalog': ctx.system}

    def check(value):
        if not isinstance(value, dict):
            return False, 'proposal not an object'
        for key in ('target_actions', 'target_claims', 'applicable_requirements',
                    'observed_facts', 'unresolved_bindings', 'assumptions', 'coverage'):
            if key not in value:
                return False, f'missing key {key}'
        for r in value.get('applicable_requirements') or []:
            if not isinstance(r, dict) or not isinstance(r.get('quote'), str) or not r['quote']:
                return False, 'requirement quote empty'
            if r.get('source') not in sources or r['quote'] not in sources[r['source']]:
                return False, 'requirement quote not verbatim in named source'
        for a in value.get('target_actions') or []:
            if not isinstance(a, dict) or not isinstance(a.get('tool'), str) or not a['tool']:
                return False, 'target action missing tool'
        for c in value.get('target_claims') or []:
            if not isinstance(c, dict) or not isinstance(c.get('text'), str) or not c['text']:
                return False, 'target claim missing text'
        return True, 'ok'
    return check


def _counterevidence_validator(value):
    if not isinstance(value, dict):
        return False, 'not an object'
    if value.get('refutes') not in (True, False, None) or not isinstance(value.get('status'), str):
        return False, 'bad counterevidence shape'
    return True, 'ok'


def run(*, prepare_only=True, arms=None):
    rows, prepared = prepare()
    if prepare_only:
        print(json.dumps({'state': 'PREPARED_NO_INFERENCE', 'n': len(rows)}))
        return
    import llm as llm_mod
    import role_prompts as RP
    from structural_v02 import parse_case_v02
    budget = Budget('reviewer_repair')
    llm = budget.install()
    journal = FOLDER / 'role_predictions.jsonl'
    done = set()
    if journal.exists():
        for line in journal.read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            done.add((r['arm'], r['id']))
    ctxs = {r['id']: parse_case_v02(r['id'], r['prompt'], r['response']) for r in rows}
    payloads = {cid: _sources_payload(ctxs[cid]) for cid in BANK}
    wanted = arms or prepared['arms']

    def emit(arm, cid, calls, parsed, valid, reason, extra=None):
        rec = {'arm': arm, 'id': cid,
               'source_sha256': source_sha(next(r for r in rows if r['id'] == cid)),
               'code_sha256': prepared['code_sha256'], 'calls': calls,
               'valid': valid, 'reason': reason, 'parsed': parsed}
        if extra:
            rec.update(extra)
        append(journal, rec)
        done.add((arm, cid))
        write(FOLDER / 'status.json', {'state': 'RUNNING', 'done': len(done),
                                       'budget': budget.snapshot()})

    def run_vote_arm(arm, model_key, system, contract='V1'):
        model = model_of(llm, model_key)
        for cid in BANK:
            if (arm, cid) in done:
                continue
            user = dict(payloads[cid])
            user['source_reference_inventory'] = _source_inventory(ctxs[cid])
            calls, value, valid, reason = call_json(
                llm, llm_mod, model, system, user, caller=f'modular/role/{arm}',
                validator=_vote_validator(ctxs[cid]))
            emit(arm, cid, calls, value, valid, reason,
                 {'model': model, 'contract': contract})

    def run_ej_arm(arm, e_key, j_key):
        e_model, j_model = model_of(llm, e_key), model_of(llm, j_key)
        for cid in BANK:
            if (arm + '/E', cid) not in done:
                calls, value, valid, reason = call_json(
                    llm, llm_mod, e_model, RP.EXTRACTOR, payloads[cid],
                    caller=f'modular/role/{arm}/E', validator=_proposal_validator(ctxs[cid]))
                emit(arm + '/E', cid, calls, value, valid, reason, {'model': e_model})
        for cid in BANK:
            if (arm + '/J', cid) in done:
                continue
            value, valid = None, False
            for line in journal.read_text(encoding='utf-8').splitlines():
                r = json.loads(line)
                if r['arm'] == arm + '/E' and r['id'] == cid:
                    value, valid = r['parsed'], r['valid']
                    break
            user = dict(payloads[cid])
            user['PROPOSAL_ADVISORY'] = value if valid else {
                'note': 'extractor proposal invalid; judge on the original only'}
            calls, vote, v, reason = call_json(
                llm, llm_mod, j_model, RP.CHECKER, user, caller=f'modular/role/{arm}/J',
                validator=_vote_validator(ctxs[cid]))
            emit(arm + '/J', cid, calls, vote, v, reason,
                 {'model': j_model, 'proposal_valid': valid})

    try:
        if 'D_V1_mistral' in wanted:
            run_vote_arm('D_V1_mistral', 'mistral', RP.DIRECT_V1)
        if 'D_V1_gemma' in wanted:
            run_vote_arm('D_V1_gemma', 'gemma', RP.DIRECT_V1)
        if 'D_V1_gptoss' in wanted:
            run_vote_arm('D_V1_gptoss', 'gptoss', RP.DIRECT_V1)
        if 'D_V1_nemotron' in wanted:
            run_vote_arm('D_V1_nemotron', 'nemotron', RP.DIRECT_V1)
        if 'EJ_gemma_gemma' in wanted:
            run_ej_arm('EJ_gemma_gemma', 'gemma', 'gemma')
        if 'EJ_gptoss_gptoss' in wanted:
            run_ej_arm('EJ_gptoss_gptoss', 'gptoss', 'gptoss')
        if 'X_gemmaE_gptossJ' in wanted:
            run_ej_arm('X_gemmaE_gptossJ', 'gemma', 'gptoss')
        if 'X_gptossE_gemmaJ' in wanted:
            run_ej_arm('X_gptossE_gemmaJ', 'gptoss', 'gemma')
        if 'Gk3_gemma' in wanted:
            model = model_of(llm, 'gemma')
            for seed in GK3_SEEDS:
                arm = f'Gk3_gemma_s{seed}'
                for cid in BANK:
                    if (arm, cid) in done:
                        continue
                    user = dict(payloads[cid])
                    user['source_reference_inventory'] = _source_inventory(ctxs[cid])
                    calls, value, valid, reason = call_json(
                        llm, llm_mod, model, RP.DIRECT_V1, user,
                        caller=f'modular/role/{arm}', validator=_vote_validator(ctxs[cid]),
                        temperature=GK3_TEMPERATURE, seed=seed)
                    emit(arm, cid, calls, value, valid, reason,
                         {'model': model, 'seed': seed, 'temperature': GK3_TEMPERATURE})
        if 'B_without_A' in wanted:
            from counterevidence import INSTRUCTION as B_V0, SOURCE_BOUND_V2
            model = model_of(llm, 'mistral')
            system = B_V0 + "\n" + SOURCE_BOUND_V2
            for cid in ERROR_IDS:
                if ('B_without_A', cid) in done:
                    continue
                user = dict(payloads[cid])
                user['prior_findings'] = []
                user['source_reference_inventory'] = _source_inventory(ctxs[cid])

                def b_validator(value, _ctx=ctxs[cid]):
                    if not isinstance(value, dict) or 'additional_error' not in value:
                        return False, 'missing additional_error key'
                    vote = value.get('additional_error')
                    if vote is None:
                        return True, 'ok_null'
                    from judge import validate_vote
                    return validate_vote(vote, _ctx)
                calls, value, valid, reason = call_json(
                    llm, llm_mod, model, system, user, caller='modular/role/B_without_A',
                    validator=b_validator)
                emit('B_without_A', cid, calls,
                     value.get('additional_error') if isinstance(value, dict) else None,
                     valid, reason, {'model': model})
        if 'G3_counterevidence' in wanted:
            model = model_of(llm, 'gemma')
            checker_votes = {}
            if journal.exists():
                for line in journal.read_text(encoding='utf-8').splitlines():
                    r = json.loads(line)
                    if r['arm'] == 'EJ_gemma_gemma/J':
                        checker_votes[r['id']] = r
            for cid in BANK:
                if ('G3_counterevidence', cid) in done:
                    continue
                cv = checker_votes.get(cid)
                accusation = (cv or {}).get('parsed') if (cv or {}).get('valid') else None
                if accusation is None or accusation.get('label') != 1:
                    emit('G3_counterevidence', cid, [], None, True,
                         'no_accusation_to_review',
                         {'model': model, 'accusation_present': False})
                    continue
                user = dict(payloads[cid])
                user['ACCUSATION_ADVISORY'] = accusation
                calls, value, valid, reason = call_json(
                    llm, llm_mod, model, RP.COUNTEREVIDENCE, user,
                    caller='modular/role/G3_counterevidence',
                    validator=_counterevidence_validator)
                emit('G3_counterevidence', cid, calls, value, valid, reason,
                     {'model': model, 'accusation_present': True})
        write(FOLDER / 'status.json', {'state': 'SUCCEEDED', 'done': len(done), 'total': None,
                                       'budget': budget.snapshot()})
    except BudgetStop as exc:
        write(FOLDER / 'status.json', {'state': 'BUDGET_STOP', 'reason': str(exc),
                                       'done': len(done), 'budget': budget.snapshot()})
    except Exception as exc:
        write(FOLDER / 'status.json', {'state': 'FAILED', 'error_type': type(exc).__name__,
                                       'done': len(done), 'budget': budget.snapshot()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--arms', nargs='*', default=None)
    args = parser.parse_args()
    run(prepare_only=not args.run, arms=args.arms)
