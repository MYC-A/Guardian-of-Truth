"""Extraction/atomization repair (assignment §6).

v2 contract, driven by three rules from the assignment:
  1. Structured tool calls are parsed by the EXISTING parser (structural_v02):
     tool name, arguments, IDs and spans come from code reading the real call;
     the model is never asked to re-guess JSON syntax of a tool call.
  2. The text atomizer must preserve negation, conditionality, modality,
     numbers, time, IDs and requested/allowed/attempt/succeeded markers; a
     per-atom shape failure demotes THAT atom (explicitly listed) instead of
     invalidating the whole inventory; an empty inventory over a non-empty
     verifiable move is an explicit COVERAGE GAP, never perfect groundedness.
  3. One unified proposal contract: target actions/claims; applicable
     requirements and possible exceptions; observed facts with field/entity/
     time/source spans; unresolved bindings and assumptions; coverage.
     Observed facts come MECHANICALLY from tool results only — a policy
     condition is never an observed fact. Proposals stay advisory; the
     verifier sees the full original and may reject them.

Transport failures are reported as TRANSPORT_FAILED (degraded + coverage),
not as an atomizer model failure — the 3/4 historical INVALID cases were
429s, not bad inventories (see REPAIR_CAUSE_AUDIT §6 receipt).
"""
import json
import re

from modular_common import exact_quotes

TEXT_ATOM_PROMPT = '''Decompose the examined TEXT PORTION of the assistant move into all independently checkable claims.
This portion contains NO tool-call lines (they are already parsed mechanically): decompose natural language only.
Keep negatives, conditionality, modality, numbers, time, identities intact. Mark the claimed status of each action
referenced by the text: requested / permitted-or-forbidden claim / attempted / succeeded — do not merge them.
An intention or request to the user is not an occurrence. Extract uncertainty explicitly.
Return JSON {"atoms":[{"text":"standalone claim, no invented facts","kind":"FACT|PERMISSION|INTENTION|UNCERTAINTY|OTHER","entity_ids":["literal ID string occurring verbatim in the text"],"status_marker":"none|requested|permitted|forbidden|attempted|succeeded","target_quote":"exact nonempty substring of the text"}],"inventory_complete":true|false}.
Do not omit an inconvenient or unsupported assertion. Do not judge truth. Source quote and semantic atom are distinct.
If the text portion contains nothing checkable, return {"atoms":[],"inventory_complete":false,"empty_reason":"..."}.'''

REQUIREMENT_PROMPT = '''From the FULL original sources below, list the requirements and exceptions that are APPLICABLE to the examined move.
A requirement is applicable when its subject/action matches the target action or claim. Include neighbouring clauses that
could be mistaken for requirements, each marked applicable=true|false with the reason. Exceptions are stated as exceptions.
Return JSON {"requirements":[{"quote":"exact nonempty substring of the sources","source":"policy|history|catalog","applicable":true|false,"is_exception":true|false,"reason":"..."}]}.
Copy quotes verbatim; do not paraphrase; do not invent requirements the sources do not state.'''

VERIFY_PROMPT = '''Verify each proposed atom using only the original policy, tool documentation and preceding history.
The target and explanation are claims being checked, never their own evidence. A policy condition does not establish a world fact.
Permission does not establish occurrence; requested is not attempted; attempted is not succeeded.
The supplied OBSERVED_FACTS were extracted mechanically from tool results and are reliable as recorded values; everything else must be checked against the full original.
Return JSON {"checks":[{"index":0,"relation":"SUPPORTS|CONTRADICTS|INSUFFICIENT","quotes":[{"source_id":"prompt","quote":"exact preceding-source substring"}],"reason":"specific argument"}],"all_checked":true|false}.
Every SUPPORTS or CONTRADICTS needs concrete source quotes. Mere lack of support, missing retrieval, future observations or ambiguous contracts are INSUFFICIENT.'''

TOOL_CALL_RE = re.compile(r'→ TOOL_CALL ([A-Za-z_][A-Za-z0-9_]*):')


def mechanical_target_atoms(ctx):
    """Tool-call part of the target, parsed by code from the real call.

    Returns (action_atoms, residual_text). Each action atom carries the
    exact span inside ctx.response_raw, the parsed argument dict, and the
    entity IDs taken from string argument values (never re-guessed by a
    model). A mixed target (call + text) is split: the action and the text
    phrase are checked separately downstream.
    """
    actions = []
    covered = []
    used_spans = []
    for call in ctx.all_tool_calls():
        if not call.in_target:
            continue
        # exact span: the verbatim call line inside the target response;
        # duplicate identical call lines get DISTINCT occurrences (each call
        # claims the next unused match — never a shared span)
        needle = f'→ TOOL_CALL {call.name}: {call.args_raw}'
        idx = -1
        while True:
            idx = ctx.response_raw.find(needle, idx + 1)
            if idx < 0:
                match = None
                break
            candidate = (idx, idx + len(needle))
            if candidate not in used_spans:
                used_spans.append(candidate)
                match = candidate
                break
        entity_ids = sorted({str(v) for v in (call.args or {}).values() if isinstance(v, str)})
        actions.append({
            'kind': 'PROPOSED_ACTION', 'tool': call.name, 'arguments': call.args,
            'args_raw': call.args_raw, 'args_error': call.args_error,
            'entity_ids': entity_ids, 'call_id': call.call_id,
            'span': {'start': match[0], 'end': match[1]} if match else None,
            'status_marker': 'attempted',
            'text': f'The assistant proposes the tool call {call.name}({json.dumps(call.args, sort_keys=True)}); this is a request to execute, not a completion.',
            'provenance': 'mechanical_parser_no_model',
        })
        if match:
            covered.append((match[0], match[1]))
    residual = ctx.response_raw
    if covered:
        covered.sort()
        parts, pos = [], 0
        for s, e in covered:
            parts.append(ctx.response_raw[pos:s])
            pos = e
        parts.append(ctx.response_raw[pos:])
        residual = ''.join(parts)
    return actions, residual.strip()


def observed_facts(ctx):
    """Mechanically extracted observed facts from tool RESULTS only.

    A policy condition can never appear here (it is not a tool result).
    Spans are line anchors in the original prompt; values stay typed.
    """
    facts = []
    for result in ctx.all_tool_results():
        payload = result.payload if isinstance(result.payload, dict) else {}
        entity = payload.get('item_id') or payload.get('id')
        for field, value in sorted(payload.items()):
            facts.append({
                'field': field, 'value': value,
                'entity_id': entity if field not in ('item_id', 'id') else value,
                'tool': result.name, 'result_id': result.result_id,
                'call_ref': result.call_ref, 'in_target': result.in_target,
                'source_span': {'line_no': result.line_no, 'raw': result.payload_raw},
                'time': payload.get('current_time') or payload.get('timestamp'),
            })
    return facts


def atomize_text(llm, model, text, *, caller):
    """Model atomizer for the TEXT portion only; per-atom demotion, not
    whole-inventory invalidation; explicit coverage-gap semantics."""
    if not text:
        return {'status': 'EMPTY_NOTHING_TO_ATOMIZE', 'atoms': [], 'issues': [],
                'coverage': 0.0, 'raw': None,
                'coverage_gap': False, 'inventory_complete_model_claim': False}
    answer = llm.chat(model, [{'role': 'system', 'content': TEXT_ATOM_PROMPT},
                              {'role': 'user', 'content': json.dumps({'TEXT_PORTION': text}, ensure_ascii=False)}],
                      max_tokens=1800, temperature=0, transport_retries=0, caller=caller)
    raw = answer
    if answer.get('error') or answer.get('content') is None:
        return {'status': 'TRANSPORT_FAILED', 'atoms': [], 'issues': ['transport_failure_degraded_not_atomizer_model'],
                'coverage': 0.0, 'raw': raw, 'coverage_gap': True,
                'transport': {'error_type': answer.get('error_type'), 'http_status': answer.get('http_status')}}
    value = llm.extract_json(answer.get('content'))
    atoms, issues = [], []
    if not isinstance(value, dict) or not isinstance(value.get('atoms'), list):
        return {'status': 'MODEL_INVALID_INVENTORY', 'atoms': [], 'issues': ['invalid_atom_inventory'],
                'coverage': 0.0, 'raw': raw, 'coverage_gap': True}
    covered = set()
    for i, atom in enumerate(value['atoms']):
        if not isinstance(atom, dict):
            issues.append(f'atom:{i}:not_an_object')
            continue
        quote = atom.get('target_quote')
        if (not isinstance(atom.get('text'), str) or not atom['text'] or
                not isinstance(quote, str) or not quote or quote not in text or
                atom.get('kind') not in {'FACT', 'PERMISSION', 'INTENTION', 'UNCERTAINTY', 'OTHER'} or
                not isinstance(atom.get('entity_ids'), list)):
            issues.append(f'atom:{i}:invalid_source_or_shape')
            continue
        bad_entities = [e for e in atom['entity_ids'] if not isinstance(e, str) or not e or e not in text]
        if bad_entities:
            # demote ONLY this atom: derived/non-literal entity IDs are an
            # explicit partial failure, never a silent deletion
            issues.append(f'atom:{i}:nonliteral_entity_ids:{bad_entities}')
            continue
        start = text.index(quote)
        covered.update(j for j in range(start, start + len(quote)) if text[j].isalnum())
        atoms.append(dict(atom, start=start, end=start + len(quote),
                          status_marker=atom.get('status_marker') or 'none'))
    needed = {i for i, c in enumerate(text) if c.isalnum()}
    coverage = len(covered & needed) / max(1, len(needed))
    empty_with_verifiable_move = not atoms and bool(needed)
    status = 'MODEL_PROPOSED'
    if not atoms:
        status = 'COVERAGE_GAP_EMPTY_INVENTORY' if needed else 'EMPTY_NOTHING_TO_ATOMIZE'
    elif issues:
        status = 'PARTIAL_INVALID_ATOMS_DEMOTED'
    return {'status': status, 'atoms': atoms, 'issues': issues, 'coverage': coverage,
            'raw': raw, 'coverage_gap': empty_with_verifiable_move,
            'inventory_complete_model_claim': value.get('inventory_complete') is True}


def propose_requirements(llm, model, ctx, *, caller):
    """Model-proposed applicable requirements/exceptions; quotes verified by code."""
    answer = llm.chat(model, [{'role': 'system', 'content': REQUIREMENT_PROMPT},
                              {'role': 'user', 'content': json.dumps({'SOURCES': {
                                  'policy': ctx.policy_text, 'catalog': ctx.system,
                                  'history': ctx.prompt_raw},
                                  'TARGET': ctx.response_raw}, ensure_ascii=False)}],
                      max_tokens=1600, temperature=0, transport_retries=0, caller=caller)
    if answer.get('error') or answer.get('content') is None:
        return {'status': 'TRANSPORT_FAILED', 'requirements': [],
                'transport': {'error_type': answer.get('error_type'), 'http_status': answer.get('http_status')}}
    value = llm.extract_json(answer.get('content'))
    sources = {'policy': ctx.policy_text, 'history': ctx.prompt_raw, 'catalog': ctx.system}
    requirements, issues = [], []
    if not isinstance(value, dict) or not isinstance(value.get('requirements'), list):
        return {'status': 'MODEL_INVALID', 'requirements': [], 'issues': ['invalid_requirements_shape'], 'raw': answer}
    for i, r in enumerate(value['requirements']):
        if not isinstance(r, dict):
            issues.append(f'requirement:{i}:not_an_object')
            continue
        quote, source = r.get('quote'), r.get('source')
        if (not isinstance(quote, str) or not quote or source not in sources or quote not in sources[source]):
            issues.append(f'requirement:{i}:quote_not_verbatim')
            continue
        start = sources[source].index(quote)
        requirements.append(dict(r, span={'source': source, 'start': start, 'end': start + len(quote)}))
    return {'status': 'MODEL_INVALID' if not requirements and issues else
            ('PARTIAL_BAD_REQUIREMENTS_DEMOTED' if issues else 'MODEL_PROPOSED'),
            'requirements': requirements, 'issues': issues, 'raw': answer}


def build_proposal_contract(ctx, action_atoms, text_inventory, requirements, facts):
    """The unified proposal contract (§6). Advisory only; the verifier sees
    the full original and can reject any part of it."""
    claims = [a for a in text_inventory.get('atoms', [])]
    verifiable_move = bool(action_atoms) or bool(claims) or bool(
        re.findall(r'\w', ctx.response_raw))
    coverage = {
        'text_char_coverage': text_inventory.get('coverage', 0.0),
        'action_atoms_mechanical': len(action_atoms),
        'text_atoms_model': len(claims),
        'inventory_status': text_inventory.get('status'),
        'empty_inventory_with_nonempty_verifiable_move': bool(
            not action_atoms and not claims and verifiable_move),
        'demoted_atoms': text_inventory.get('issues', []),
        'note': 'coverage gap is explicit; empty inventory never means perfect groundedness',
    }
    return {
        'schema': 'proposal-contract/1',
        'target': {
            'actions': action_atoms,
            'claims': claims,
            'mixed_target_split': bool(action_atoms) and bool(claims),
            'raw': ctx.response_raw,
        },
        'applicable_requirements': requirements.get('requirements', []),
        'requirement_proposal_status': requirements.get('status'),
        'observed_facts': facts,
        'unresolved_bindings': [
            {'what': f['entity_id'] or f"result:{f['result_id']}", 'reason': 'value present but semantics not resolved'}
            for f in facts if f['field'] in ('status', 'current_time') and f['in_target']],
        'assumptions': [],
        'coverage': coverage,
        'semantics': {
            'observed_facts_source': 'mechanical tool-result payloads only; policy conditions excluded by construction',
            'advisory_only': 'model proposals are hints; the checker sees the full original and may reject them',
            'formal_program': 'checked separately from the text form; not attempted here',
        },
    }


def verify_atoms(llm, model, ctx, atoms, facts, *, caller):
    """Full-original verification (advisory); quotes and completeness checked by code."""
    if not atoms:
        return {'status': 'NOTHING_TO_VERIFY', 'checks': [], 'all_checked': True}
    answer = llm.chat(model, [{'role': 'system', 'content': VERIFY_PROMPT},
                              {'role': 'user', 'content': json.dumps({
                                  'FULL_PRECEDING_SOURCE': ctx.prompt_raw,
                                  'CANDIDATE_ATOMS': atoms,
                                  'OBSERVED_FACTS_MECHANICAL': facts}, ensure_ascii=False)}],
                      max_tokens=2000, temperature=0, transport_retries=0, caller=caller)
    if answer.get('error') or answer.get('content') is None:
        return {'status': 'TRANSPORT_FAILED', 'checks': [], 'all_checked': False,
                'transport': {'error_type': answer.get('error_type'), 'http_status': answer.get('http_status')}}
    value = llm.extract_json(answer.get('content'))
    if not isinstance(value, dict) or not isinstance(value.get('checks'), list):
        return {'status': 'INVALID', 'raw': answer, 'checks': []}
    checks, issues = [], []
    for item in value['checks']:
        if not isinstance(item, dict) or type(item.get('index')) is not int or not 0 <= item['index'] < len(atoms):
            issues.append('invalid_atom_index')
            continue
        relation = item.get('relation')
        quotes = item.get('quotes')
        if (relation not in {'SUPPORTS', 'CONTRADICTS', 'INSUFFICIENT'} or
                not exact_quotes(quotes, {'prompt': ctx.prompt_raw}) or
                (relation != 'INSUFFICIENT' and not quotes)):
            issues.append('invalid_quote_or_relation')
            continue
        checks.append(item)
    if sorted(c['index'] for c in checks) != list(range(len(atoms))):
        issues.append('not_every_atom_checked_exactly_once')
    return {'status': 'INVALID' if issues else 'MODEL_JUDGED', 'raw': answer, 'checks': checks,
            'issues': issues, 'all_checked': value.get('all_checked') is True and not issues}


def run_case(llm, model, row, *, caller_prefix='modular/atomic-v2'):
    """Full v2 pass for one case: mechanical actions -> text atoms ->
    requirement proposals -> unified contract -> verification."""
    from structural_v02 import parse_case_v02
    ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
    action_atoms, residual_text = mechanical_target_atoms(ctx)
    text_inventory = atomize_text(llm, model, residual_text, caller=f'{caller_prefix}/text')
    requirements = propose_requirements(llm, model, ctx, caller=f'{caller_prefix}/requirements')
    facts = observed_facts(ctx)
    contract = build_proposal_contract(ctx, action_atoms, text_inventory, requirements, facts)
    atoms_for_verification = (
        [{'kind': a['kind'], 'text': a['text'], 'entity_ids': a['entity_ids'],
          'status_marker': a['status_marker'], 'provenance': a['provenance']} for a in action_atoms]
        + [{'kind': a['kind'], 'text': a['text'], 'entity_ids': a['entity_ids'],
            'status_marker': a.get('status_marker', 'none'), 'target_quote': a['target_quote']}
           for a in text_inventory.get('atoms', [])])
    verification = verify_atoms(llm, model, ctx, atoms_for_verification, facts,
                                caller=f'{caller_prefix}/verify')
    return {'contract': contract, 'verification': verification,
            'atomizer_text_status': text_inventory['status'],
            'requirement_status': requirements.get('status'),
            'verifier_status': verification['status'],
            'coverage_gap': contract['coverage']['empty_inventory_with_nonempty_verifiable_move']}
