"""DEV-only native oracle substitutions. Never imported by service/inference.

AUTHOR structured contracts and policy trees are an injected diagnostic input,
not automatic extraction, human review, or improvements to an LLM arm.
"""
import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
from modular_common import HERE, RESULTS, load_input, sha, source_sha, write
from v2_pipeline import as_row, native_case
from guardian_truth.parsing import parse_events
from guardian_truth.integration.contracts import facts_from_documented
from guardian_truth.integration.proof_engine import ReviewedProgram, ClaimQuery, check_call, check_claim, decide_reviewed
from guardian_truth.step2.trusted import producer_scope
from guardian_truth.step2.verifier import CallEvent


def native_gate(spec, *, inverted=False):
    """Generic Boolean AST translation, including De Morgan. No prose parser."""
    op = spec['op']
    if op == 'NOT':
        return native_gate(spec['args'][0], inverted=not inverted)
    if op == 'ATOM':
        return {'atom': {'predicate': 'item.' + spec['field'], 'entity_type': 'item',
                         'value': not inverted, 'allowed_strengths': ['OBSERVED'], 'scope_joins': {}}}
    if op in {'AND', 'OR'}:
        operator = ('any' if op == 'AND' else 'all') if inverted else ('all' if op == 'AND' else 'any')
        return {operator: [native_gate(child, inverted=inverted) for child in spec['args']]}
    raise ValueError('oracle_AST_operator_not_supported/' + op)


def oracle_case(converted):
    """Inject exact scalar field=state contracts for this AUTHOR world only.

    These contracts are NOT inferred by matching English descriptions. Result
    paths/ID/time are still checked by the original native provenance verifier.
    """
    converted = copy.deepcopy(converted)
    for tool in converted['available_tools']:
        declarations = []
        for key in tool['result_schema']:
            if key in tool['parameters']:
                continue
            declarations.append({'predicate': 'item.' + key, 'entity_type': 'item',
                'entity_argument': 'item_id', 'result_entity_path': '$.item_id',
                'result_value_path': '$.' + key, 'strength': 'OBSERVED', 'allowed_values': []})
        tool['documented_contracts'] = declarations
        tool['declarations_origin'] = 'AUTHOR_ORACLE_STATE_FIELD_EQUALS_WORLD_FIELD_NOT_MODEL'
    return native_case(converted)


def call_targets(row, converted):
    return [CallEvent(converted['target_response']['index'], 'target' + str(i), event.name, event.value)
            for i, event in enumerate(parse_events(row['response'], 'response')) if event.kind == 'call']


def policy_program(row, gold, case, converted):
    targets = call_targets(row, converted)
    if len(targets) != 1:
        raise ValueError('oracle_requires_one_governed_call')
    target = targets[0]
    tool = next(t for t in case.tools if t['name'] == target.tool)
    return ReviewedProgram(case.category, target.tool, tool['description'], producer_scope(case, target.tool),
                           'item_id', native_gate(gold['requirement']['specification']),
                           evidence_source='ENV_TESTED', complete_for_governed_action=True)


def source_bound_programs(programs, case):
    """Only recompute catalog fingerprint after oracle catalog injection.

    Predicate, values, scopes and conditions remain EXACTLY the auto proposal.
    A source identity update is recorded, not presented as semantic repair.
    """
    output = []
    for raw in programs:
        values = dict(raw, governed_producer=producer_scope(case, raw['governed_tool']))
        output.append(ReviewedProgram(**values))
    return output


def oracle_calls(rows, gold, original):
    records = []
    for row in rows:
        converted = as_row(row)
        case = oracle_case(converted)
        facts, assessments, issues = facts_from_documented(case)
        oracle = policy_program(row, gold[row['id']], case, converted)
        automatic = source_bound_programs(original.get(row['id'], {}).get('step1', {}).get('programs', []), case)
        target = call_targets(row, converted)[0]
        variants = [('gold_S1_only', [oracle], []), ('gold_S1_S2', [oracle], facts)]
        if row['id'] in original:
            variants += [('auto_S1_gold_S2', automatic, facts)]
        arms = {}
        for name, programs, evidence in variants:
            proofs = [check_call(p, case, target, tuple(evidence), hypothetical=True)
                      for p in programs if p.governed_tool == target.tool]
            decision = decide_reviewed(tuple(proofs), (), policy_complete=bool(programs), claim_inventory_complete=True)
            arms[name] = {'decision': decision, 'proofs': proofs}
        records.append({'id': row['id'], 'source_sha256': source_sha(row), 'logical_group': gold[row['id']]['logical_group'],
            'author_label': gold[row['id']]['label'], 'oracle_program': asdict(oracle),
            'verified_fact_count': len(facts), 'facts': [v.as_dict() for v in facts],
            'contract_issues': list(issues), 'assessments': [a.as_dict() for a in assessments],
            'auto_original': original.get(row['id']), 'arms': arms})
    return records


def oracle_claims(rows, gold):
    records = []
    for row in rows:
        converted = as_row(row)
        case = oracle_case(converted)
        facts, assessments, issues = facts_from_documented(case)
        claims = gold[row['id']]['atomic_claims']
        proofs = []
        for atom in claims:
            if not all(k in atom for k in ('field', 'value', 'entity_id')):
                continue
            quote = atom['text']
            start = row['response'].index(quote)
            query = ClaimQuery(row['response'], converted['target_response']['index'], quote, start, start + len(quote),
                'STATE_CLAIM', 'item.' + atom['field'], 'item', atom['entity_id'], atom['value'], 'ENV_TESTED')
            proof = check_claim(query, case, tuple(facts))
            proofs.append({'query': asdict(query), 'proof': proof, 'author_relation': atom['relation']})
        records.append({'id': row['id'], 'source_sha256': source_sha(row), 'author_label': gold[row['id']]['label'],
            'verified_fact_count': len(facts), 'proofs': proofs, 'issues': list(issues),
            'decision': decide_reviewed((), tuple(p['proof'] for p in proofs), policy_complete=True, claim_inventory_complete=len(proofs) == len(claims))})
    return records


def oracle_reachability(rows, gold):
    from guardian_truth.integration.reachability import ReviewedGoal, assess_local_reachability, decide_refusal
    spec = json.loads((HERE / 'dataset/oracle_reachability_specs.json').read_text(encoding='utf-8'))
    by_id = {r['id']: r for r in rows}
    output = []
    for selected in spec['cases']:
        row = by_id[selected['id']]
        converted = as_row(row)
        assert spec['capability']['source_catalog_quote'] in row['prompt']
        case = oracle_case(converted)
        cap = spec['capability']
        tools = copy.deepcopy(list(case.tools))
        tool = next(t for t in tools if t['name'] == cap['tool'])
        tool['result_schema']['status'] = 'scalar'
        tool['documented_contracts'].append({
            'predicate': cap['predicate'], 'entity_type': cap['entity_type'],
            'entity_argument': cap['entity_argument'], 'result_entity_path': cap['result_entity_path'],
            'result_value_path': cap['result_value_path'], 'strength': cap['strength'],
            'allowed_values': [cap['success_value']]})
        case = replace(case, tools=tuple(tools))
        facts, _, issues = facts_from_documented(case)
        program = ReviewedProgram(case.category, cap['tool'], tool['description'], producer_scope(case, cap['tool']),
            cap['entity_argument'], native_gate(spec[selected['gate']]),
            evidence_source='ENV_TESTED', complete_for_governed_action=True)
        goal = ReviewedGoal(converted['user_request'], cap['entity_type'], cap['entity_id'], cap['predicate'],
            cap['success_value'], True, ({'tool': cap['tool'], 'arguments': {cap['entity_argument']: cap['entity_id']}},), 'ENV_TESTED')
        variants = [('gold_inventory_S1_S2', goal, facts, True), ('gold_inventory_S1_no_S2', goal, [], True),
                    ('incomplete_inventory', replace(goal, candidate_actions_exhaustive=False), facts, True),
                    ('incomplete_catalog', goal, facts, False)]
        arms = {}
        for name, scoped_goal, evidence, complete in variants:
            reach = assess_local_reachability(converted['user_request'], row['response'], converted['target_response']['index'],
                scoped_goal, (program,), case, tuple(evidence), catalog_complete=complete)
            refusal = decide_refusal(row['response'], {'quote': row['response'], 'absolute_inability': True,
                                                       'evidence_source': 'ENV_TESTED'}, reach)
            arms[name] = {'reachability': reach, 'refusal': refusal}
        output.append({'id': row['id'], 'source_sha256': source_sha(row), 'author_label': gold[row['id']]['label'],
            'author_expected_reachability': selected['expected_reachability'], 'oracle_program': asdict(program),
            'oracle_goal': asdict(goal), 'verified_facts': len(facts), 'issues': list(issues), 'arms': arms})
    return output


def run(root):
    gold = {r['id']: r for r in map(json.loads, (HERE / 'dataset/dev_gold.jsonl').read_text(encoding='utf-8').splitlines())}
    rows = load_input()
    policy_rows = [r for r in rows if (gold[r['id']]['requirement'] or {}).get('kind') == 'PERMISSION']
    claim_rows = [r for r in rows if gold[r['id']]['atomic_claims'] and all(a.get('mode') == 'FACT' for a in gold[r['id']]['atomic_claims'])]
    original_path = root / 'pilot_v2/predictions.jsonl'
    original = {r['id']: r['result'] for r in map(json.loads, original_path.read_text(encoding='utf-8').splitlines())}
    calls, claims = oracle_calls(policy_rows, gold, original), oracle_claims(claim_rows, gold)
    reachability = oracle_reachability(rows, gold)
    counts = {}
    for name in ('gold_S1_only', 'gold_S1_S2', 'auto_S1_gold_S2'):
        selected = [r for r in calls if name in r['arms']]
        counts[name] = {'n': len(selected), 'UNKNOWN': sum(r['arms'][name]['decision']['status'] == 'UNKNOWN' for r in selected),
                       'determined_correct': sum((r['arms'][name]['decision']['status'] == 'ERROR') == bool(r['author_label']) and r['arms'][name]['decision']['status'] != 'UNKNOWN' for r in selected)}
    report = {'scope': 'DEV AUTHOR-ORACLE DIAGNOSTIC, NOT AUTOMATIC DETECTOR RESULTS',
              'human_reviewed': False, 'native_engine_changed': False, 'counts': counts, 'call_cases': calls, 'claim_cases': claims,
              'reachability_cases': reachability,
              'limits': ['Only native Boolean gate operators are represented; no general implication/time/ordering compiler.',
                         'Oracle scalar state contracts supply semantics absent from automatic acquisition.',
                         'Auto programs use a mechanical producer fingerprint update only; all semantic fields are untouched.',
                         'Missing facts return UNKNOWN; this is distinct from unsupported-statement ERROR under the contest definition.']}
    write(root / 'oracle_probe.json', report)
    print(json.dumps({'policy': counts, 'claims': {'n': len(claims), 'decisions': {s: sum(r['decision']['status'] == s for r in claims) for s in ('ERROR', 'NO_ERROR', 'UNKNOWN')}},
        'reachability': {'n': len(reachability), 'correct': sum(r['arms']['gold_inventory_S1_S2']['reachability']['status'] == r['author_expected_reachability'] for r in reachability)}}))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=RESULTS)
    run(p.parse_args().root)
