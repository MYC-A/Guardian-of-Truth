"""Actual System V2 acquisition + native Steps 2-4, not another generic judge.

Model-proposed contracts/programs/goals remain AUTO_VERIFIED_WITH_LIMITS in
external trace. Relative native proofs are advisory and cannot certify source
faithfulness. Raw observations provide schema fields, not semantic contracts.
"""
from dataclasses import asdict
import json
import sys
import types
from modular_common import ROOT, RESULTS, append, exact_quotes, sha
from guardian_truth.parsing import parse_events, parse_catalog
from guardian_truth.step2.verifier import TrajectoryCase, CallEvent, ResultEvent, CandidateFact
from guardian_truth.step2.result_types import json_path_get, scalar_to_json
from guardian_truth.step2.trusted import assess


def original_modules(llm):
    def chat(model, messages, **kwargs):
        out = llm.chat(model, messages, transport_retries=0, caller='modular/SystemV2', **kwargs)
        append(RESULTS / 'v2_stage_calls.jsonl', {'model': model,
            'request_sha256': sha({'messages': messages, 'parameters': kwargs}), 'raw': out})
        return dict(out, parsed=llm.extract_json(out.get('content')))
    # Replace only historical provider paths; retain original V2 algorithms.
    sys.modules['v2_llm'] = types.SimpleNamespace(chat=chat, MODELS=llm.MODEL_REGISTRY)
    sys.path.insert(0, str(ROOT / 'experiments/searh_23/system_research_v2'))
    import steps_2to4
    import step1_arms
    import probe_task1
    return steps_2to4, step1_arms, probe_task1


def as_row(row):
    from structural_v02 import parse_case_v02
    ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
    events = parse_events(row['prompt'], 'prompt')
    tools = []
    for name, spec in ctx.catalog.tools.items():
        # Result schema is explicitly observed, not a contractual promise.
        schemas = {k: 'scalar' for e in events if e.kind == 'result' and e.name == name and isinstance(e.value, dict)
                   for k, v in e.value.items() if v is None or isinstance(v, (str, int, float, bool))}
        schemas.update({p: 'scalar' for p in spec.params})
        tools.append({'name': name, 'description': spec.description,
                      'parameters': {key: {'type': p.type, 'required': p.required} for key, p in spec.params.items()},
                      'result_schema': schemas, 'schema_source': 'observed_payloads_plus_argument_fields_not_documented_guarantee'})
    history, calls = [], []
    for index, event in enumerate(events):
        if event.kind == 'call':
            cid = f'h{len(calls)}'
            calls.append((event.name, cid))
            history.append({'index': index, 'call_id': cid, 'role': 'assistant', 'tool': event.name, 'arguments': event.value})
        elif event.kind == 'result':
            candidates = [p for p in calls if p[0] == event.name]
            if len(candidates) != 1:
                # Match the nearest preceding unmatched same-name call; reuse
                # is disallowed. Transport ambiguity remains visible.
                cid = candidates[-1][1] if candidates else f'unpaired{index}'
            else:
                cid = candidates[0][1]
            if candidates:
                calls.remove((event.name, cid))
            history.append({'index': index, 'call_id': cid, 'role': 'tool', 'tool': event.name, 'payload': event.value})
    request = '\n'.join(e.text for e in events if e.role == 'user')
    return {'case_id': row['id'], 'system_policy': ctx.policy_text, 'available_tools': tools,
            'user_request': request, 'history': history,
            'target_response': {'text': row['response'], 'index': len(events) + 1},
            'catalog_complete': parse_catalog(events, row['prompt']).complete, 'family': 'input_content_not_gold_group'}


def native_case(row):
    return TrajectoryCase(row['case_id'], row['system_policy'], 'automatic_source_adapter',
        tuple(row['available_tools']),
        tuple(CallEvent(e['index'], e['call_id'], e['tool'], e['arguments']) for e in row['history'] if e['role'] == 'assistant'),
        tuple(ResultEvent(e['index'], e['call_id'], e['tool'], e['payload']) for e in row['history'] if e['role'] == 'tool'))


def automatic_facts(case):
    from v2_boundaries import acquire_documented_v2
    acquired = acquire_documented_v2(case)
    out, trace = [], []
    for call in case.calls:
        if not isinstance(call.payload, dict):
            continue
        for result in case.results:
            if result.call_id != call.call_id or result.tool != call.tool:
                continue
            for binding in acquired.bindings:
                from guardian_truth.step2.trusted import producer_scope
                if binding.producer != producer_scope(case, call.tool):
                    continue
                value, present = json_path_get(result.payload, binding.result_path)
                rendered = scalar_to_json(value)
                entity = call.payload.get(binding.entity_field)
                if not present or rendered is None or entity is None or binding.allowed_values and rendered not in binding.allowed_values:
                    continue
                candidate = CandidateFact(binding.predicate, binding.entity_type, binding.entity_field,
                                          str(entity), rendered, binding.result_path, binding.strength)
                result_check = assess(case, call, result, candidate, acquired.bindings)
                trace.append(asdict(result_check))
                if result_check.verified:
                    out.append(result_check.verified)
    return out, {'bindings': [asdict(b) for b in acquired.bindings], 'issues': acquired.issues, 'assessments': trace,
                 'semantic_contract_faithfulness_verified': False}


def run(llm, model, row, *, contracts=None):
    steps, step1, probe = original_modules(llm)
    # Original imported helpers must see the corrected trust labels too.
    # Patch this experimental process only; the existing service is isolated.
    from v2_boundaries import acquire_documented_v2
    from guardian_truth.integration import contracts as contract_module
    contract_module.acquire_documented = acquire_documented_v2
    for name in ('guardian_truth.integration.candidate_claims', 'guardian_truth.integration.claim_binding',
                 'guardian_truth.integration.automatic_claims', 'guardian_truth.integration.reachability'):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, 'acquire_documented'):
            module.acquire_documented = acquire_documented_v2
    converted = as_row(row)
    if contracts is None:
        contracts = steps.acquire_auto_contracts(converted['available_tools'], model)
    enriched = steps.enriched_case(converted, contracts)
    case = native_case(enriched)
    facts, s2 = automatic_facts(case)
    fam = {'policy': converted['system_policy'], 'tools': enriched['available_tools']}
    programs, issues, raw = step1.run_s1a(fam, model)
    from guardian_truth.integration.proof_engine import ReviewedProgram, check_call, check_claim
    from guardian_truth.step2.trusted import producer_scope
    reviewed, program_issues = [], list(issues)
    for p in programs:
        if not isinstance(p.get('governing_quote'), str) or not p['governing_quote'] or p['governing_quote'] not in converted['system_policy']:
            program_issues.append('governing_quote_not_exact')
            continue
        values = {k: p[k] for k in ('policy', 'governed_tool', 'governed_description', 'entity_argument', 'gate', 'when')}
        values.update(governed_producer=producer_scope(case, p['governed_tool']),
                      evidence_source='AUTO_VERIFIED', complete_for_governed_action=p['complete_for_governed_action'])
        try:
            reviewed.append(ReviewedProgram(**values))
        except (ValueError, TypeError):
            program_issues.append('native_program_rejected')
    s1 = {'raw': raw, 'programs': [asdict(p) for p in reviewed], 'issues': program_issues,
          'semantic_faithfulness_verified': False, 'completeness': 'MODEL_CLAIM_ONLY'}
    current = parse_events(row['response'], 'response')
    action_proofs = [check_call(p, case, CallEvent(converted['target_response']['index'], f'target{i}', e.name, e.value), tuple(facts), hypothetical=True)
                     for i, e in enumerate(current) if e.kind == 'call' for p in reviewed if p.governed_tool == e.name]
    # Use actual original automatic claim inventory and literal compiler.
    from guardian_truth.integration.automatic_claims import compile_candidate_claims
    claim_raw = steps.step3_raw(enriched, model)
    compiled = compile_candidate_claims(row['response'], converted['target_response']['index'], case, claim_raw or '')
    s3 = {'raw': claim_raw, 'inventory_complete': compiled.inventory_complete,
          'issues': compiled.issues, 'queries': [asdict(q) for q in compiled.queries],
          'proofs': [check_claim(q, case, tuple(facts)) for q in compiled.queries], 'action_proofs': action_proofs}
    goal_raw = steps.step4_goal(enriched, model)
    from v2_boundaries import validate_goal_v2
    validated, goal_issues = validate_goal_v2(goal_raw, enriched, catalog_complete=False)
    from guardian_truth.integration.reachability import ReviewedGoal, assess_local_reachability, decide_refusal
    s4 = {'raw': goal_raw, 'issues': goal_issues, 'reachability': {'status': 'UNKNOWN', 'reason': 'unvalidated_goal'}}
    if validated is not None and not goal_issues:
        goal_data = validated['goal']
        # A nonempty model list does not prove exhaustive capability discovery.
        # We may witness a legal next action, but never infer CLOSED from this
        # unreviewed inventory. Empty and incomplete catalogs remain UNKNOWN.
        goal_data['candidate_calls'] = tuple(goal_data['candidate_calls'])
        try:
            goal = ReviewedGoal(**goal_data)
            reach = assess_local_reachability(converted['user_request'], row['response'], converted['target_response']['index'],
                goal, tuple(reviewed), case, tuple(facts), catalog_complete=converted['catalog_complete'])
            if reach['status'] == 'CLOSED':
                reach = dict(reach, status='UNKNOWN', reason='model_inventory_does_not_prove_exhaustive_closure')
            s4['reachability'] = reach
            s4['refusal_decision'] = decide_refusal(row['response'], validated['refusal'], reach)
        except (ValueError, TypeError):
            s4['issues'].append('native_goal_rejected')
    return {'module': 'automatic-SystemV2-native-Steps2-4/1', 'step1': s1, 'step2': s2, 'step3': s3, 'step4': s4,
            'native_fact_count': len(facts), 'contract_proposals': contracts,
            'trust': 'AUTO_VERIFIED_WITH_LIMITS_NOT_DOC_EXPLICIT',
            'promotion': 'ADVISORY_ONLY_FULL_SOURCE_CHECK_REQUIRED'}
