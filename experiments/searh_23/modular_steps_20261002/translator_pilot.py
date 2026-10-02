"""Paired real code/instruct translators with original signed-Horn schema.

No names/domain-conditioned branches and no automatic solver promotion.
Native grammar validity, semantic faithfulness and determined relations are
separate diagnostics. Full original policy/history is always provided.
"""
import dataclasses
import json
import time
from modular_common import Budget, BudgetStop, HERE, RESULTS, append, exact_quotes, load_input, sha, source_sha, write

IDS = [f'{group}::{variant:02d}' for group in
       ('dev_nested_gate', 'dev_negative_scope', 'dev_implication', 'dev_entity_binding')
       for variant in (0, 1)]
MODELS = ('env_mistral', 'mistral/codestral-2508', 'mistral/magistral-small-latest', 'ollama/kimi-k2.7-code')


def messages(row):
    from phi_shadow_run import formal_messages
    from structural_v02 import parse_case_v02
    ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
    calls = ctx.target().tool_calls
    target = (json.dumps({'assertion_to_test': 'This proposed tool action is permitted NOW; not a historical occurrence.',
                         'tool': calls[0].name, 'arguments': calls[0].args}, ensure_ascii=False)
              if len(calls) == 1 else row['response'])
    evidence = [{'id': 'prompt', 'text': row['prompt']}, {'id': 'target', 'text': row['response']}]
    return formal_messages(target, evidence), evidence


def trust_issues(parsed, row):
    """Conservative mechanical guard, not an entailment/faithfulness oracle."""
    issues = []
    from guardian_truth.parsing import parse_events
    history = [e for e in parse_events(row['prompt'], 'prompt') if e.kind in ('call', 'result')]
    for i, fact in enumerate(parsed.get('facts', []) if isinstance(parsed, dict) else []):
        sources = fact.get('sources', [])
        if any(s.get('source_id') == 'target' for s in sources):
            issues.append(f'fact:{i}:target_as_evidence')
        if not exact_quotes(sources, {'prompt': row['prompt'], 'target': row['response']}):
            issues.append(f'fact:{i}:invalid_source')
        # Conservative factual fragment: normative clauses/user goals become
        # rules/queries, never business-state facts. Unconditional textual
        # policy facts are unsupported by this narrow guard, not false.
        for citation in sources:
            quote = citation.get('quote', '')
            if citation.get('source_id') != 'prompt' or not quote or not any(quote in e.text for e in history):
                issues.append(f'fact:{i}:not_preceding_observation_or_occurrence')
    for i, rule in enumerate(parsed.get('rules', []) if isinstance(parsed, dict) else []):
        if not exact_quotes(rule.get('sources', []), {'prompt': row['prompt'], 'target': row['response']}):
            issues.append(f'rule:{i}:invalid_source')
    return issues


def run():
    budget = Budget()
    llm = budget.install()
    from guardian_truth.formal_reasoning import evaluate_formalization, FormalValidationError
    rows = load_input(ids=IDS)
    folder = RESULTS / 'translator_pilot'
    write(folder / 'selection.json', {'ids': IDS, 'models': MODELS,
        'schema_sha256': sha(__import__('guardian_truth.formal_reasoning', fromlist=['FORMAL_SCHEMA']).FORMAL_SCHEMA),
        'task': 'automatic query-specific predicate translation, NOT full policy completeness'})
    journal = folder / 'predictions.jsonl'
    prior = { (r['model'], r['id']): r for r in map(json.loads, journal.read_text().splitlines())} if journal.exists() else {}
    try:
        for requested in MODELS:
            model = llm.DEFAULT_MISTRAL_MODEL if requested == 'env_mistral' else requested
            for row in rows:
                if (requested, row['id']) in prior:
                    assert prior[requested, row['id']]['source_sha256'] == source_sha(row)
                    continue
                msgs, evidence = messages(row)
                began = time.monotonic()
                answer = llm.chat(model, msgs, max_tokens=3000, temperature=0, json_mode=True,
                                  transport_retries=0, caller='modular/translator/' + requested)
                parsed = llm.extract_json(answer.get('content'))
                try:
                    result = dataclasses.asdict(evaluate_formalization(json.dumps(parsed) if parsed is not None else '', evidence))
                    format_status = 'VALID'
                except FormalValidationError as exc:
                    result = {'relation': 'INSUFFICIENT', 'reason': exc.category, 'scope': 'invalid_translation'}
                    format_status = 'INVALID'
                issues = trust_issues(parsed, row)
                rec = {'id': row['id'], 'model': requested, 'resolved_model': model,
                       'source_sha256': source_sha(row), 'raw': answer, 'translation': parsed,
                       'formal_result': result, 'format_status': format_status, 'trust_issues': issues,
                       'guarded_relation': 'INSUFFICIENT' if issues else result['relation'],
                       'translation_semantically_verified': False, 'wall_seconds': time.monotonic() - began}
                append(journal, rec)
                prior[requested, row['id']] = rec
                write(folder / 'status.json', {'state': 'RUNNING', 'done': len(prior), 'total': len(IDS)*len(MODELS), 'budget': budget.snapshot()})
            # One model can be access-blocked on every case; recorded as such,
            # never conflated with incorrect semantics from valid responses.
        write(folder / 'status.json', {'state': 'SUCCEEDED', 'done': len(prior), 'total': len(IDS)*len(MODELS), 'budget': budget.snapshot()})
    except BudgetStop:
        write(folder / 'status.json', {'state': 'BUDGET_STOP', 'done': len(prior), 'total': len(IDS)*len(MODELS), 'budget': budget.snapshot()})


if __name__ == '__main__':
    run()
