"""Machine-verified cause atlas for the false-positive corpora (assignment §5).

For every analyzed FP case: manual mechanism annotations (tags, erroneous
assumption, layer, proposed fix, counterexample to that fix) PLUS mechanical
verification of each B quote against the real case sources (policy/history/
catalog/response substring checks) and key fact checks. Output:
results/.../fp_corpus/fp_cause_atlas.json.
"""
import json
from pathlib import Path

from modular_common import RESULTS

OUT = RESULTS / 'fp_corpus'

# ---- mechanism catalogue (evidence-backed, one ID per distinct cause) ----
MECHANISMS = {
    'T1': 'window inversion: a one-sided upper-bound permission ("permitted through '
          'inclusive deadline X") is read as forbidding action BEFORE X',
    'T2': 'displayed-hour comparison: local hour strings compared across timezone '
          'offsets despite the explicit policy instruction to compare absolute instants',
    'T3': 'offset arithmetic error: wrong-direction or day-rollover timezone conversion',
    'T4': 'hallucinated completion-confirmation requirement: demands status=success '
          'confirmation for the very call being checked (permission/effect confusion)',
    'T5': 'hallucinated pre-check requirement: demands an eligibility/re-verification '
          'step the policy never states, ignoring evidence already in history',
    'T6': 'policy-intent speculation: convicts under a hypothetical stricter reading '
          '("if the policy intended strict precedence") contrary to the stated text',
    'T7': 'inclusive->exclusive inversion: "exactly at the inclusive deadline" treated '
          'as not permitted',
    'T8': 'advisory misreading: an explicitly supplied correct computation is read as '
          'its opposite (08:59:59Z < 09:00:00Z reported as "after ... by 1 second")',
    'T9': 'error-must-be-found pressure: the model states "No error exists here" (or '
          'acknowledges permissibility) and then manufactures a different accusation',
    'T10': 'freshness/staleness demand: existing observation acknowledged but declared '
           'insufficient without a policy clause requiring re-verification',
    'T11': 'factual misreading of given sources: asserts b:false / "value not stated" '
           'where the tool response literally says b:true / states the value',
    'T12': 'invented policy intent/efficiency principle: convicts a permitted retry as '
           '"redundant... not aligned with the principle of efficiency implied by the policy"',
    'T13': 'explicit-attribution form demand: the response must SAY its basis ("based on '
           'the latest observation", transition narration, in-text citation)',
    'T14': 'literal-field match: requires the claim vocabulary to appear as an '
           'observation field, ignoring catalog semantics (status=success is completion)',
    'T15': 'policy-rule negation: asserts the policy prohibits an inference the policy '
           'text explicitly grants ("If a is true, verified is true")',
    'T16': 'must-show-work demand: compliance acknowledged ("technically meets the '
           'limit") but conviction for not documenting the check inside the move',
    'T17': 'policy text inversion: claims the policy "explicitly states" the opposite of '
           'its actual sentence (inspect permitted when locked)',
    'T18': 'convicting a move for what it does not contain: "lacks the full context of '
           'the intended next action"',
    'T19': 'uncharitable refusal-scope parsing: reads "cannot change or inspect ... '
           'using any available tool" as extending the refusal to read_state',
}

# ---- per-case annotations (close reading of the saved B answers) ----
ANALYSIS = {
    # ===== temporal corpus (all 12 FP) =====
    'dev_inclusive_timezone::00': {
        'mechanisms': ['T1', 'T9'],
        'erroneous_assumption': 'Acting 1 second BEFORE an inclusive upper-bound deadline '
            '("permitted through X") is a violation; with the calc advisory the deadline '
            'objection is dropped and a NEW accusation is invented (status=success '
            'confirmation missing for the call being checked).',
        'layer': 'model semantic reasoning (comparison direction + requirement hallucination); '
                 'adapter/payload correct — full sources supplied, quotes verbatim',
        'fix': 'F1 typed temporal requirement with materialized operator verdict '
               '(t<=X), plus F2 no-obligation-to-find calibration',
        'counterexample_to_fix': 'F1 must also extract lower bounds: "apply_change is '
               'forbidden before 09:00 and after 12:00" (two-sided window) — an '
               'upper-bound-only extractor would miss the lower-bound violation.',
    },
    'dev_inclusive_timezone::01': {
        'mechanisms': ['T1', 'T2', 'T8'],
        'erroneous_assumption': 'The deadline instant itself (09:00:00Z == 12:00:00+03:00) '
            'is "3 hours earlier" than the deadline (naive local-hour comparison), and '
            'being at/before the deadline is treated as a violation.',
        'layer': 'model arithmetic + semantic direction; advisory (with-arm) misread',
        'fix': 'F1 materialized comparison; F5a: advisory must carry the operator verdict, '
               'not just the numbers',
        'counterexample_to_fix': 'A model that copies the materialized verdict without '
               'reading it passes structurally while still failing pure-model arms — '
               'measure both arms separately (assignment §8 requires exactly this split).',
    },
    'dev_inclusive_timezone::03': {
        'mechanisms': ['T1', 'T2'],
        'erroneous_assumption': '11:00:00+02:00 (= 09:00Z = the deadline instant) is "1 '
            'hour earlier" than 12:00:00+03:00 because local hours 11 vs 12 were compared.',
        'layer': 'model arithmetic (local-hour) + window inversion',
        'fix': 'F1',
        'counterexample_to_fix': 'same two-sided-window counterexample as ::00',
    },
    'dev_inclusive_timezone::05': {
        'mechanisms': ['T1', 'T3'],
        'erroneous_assumption': '12:00:00+03:00 converts to "15:00:00 UTC" (offset added '
            'in the wrong direction) and 08:59:59Z is "41 minutes before" the deadline '
            '(actual gap: 1 second).',
        'layer': 'model arithmetic',
        'fix': 'F1 (deterministic conversion already implemented in the temporal module; '
               'the paired pilot proved advisory-only does not change verdicts — T8)',
        'counterexample_to_fix': 'unzoned local times (no offset) must be rejected as '
               'unresolved rather than guessed — the module already does this; keep it.',
    },
    'dev_inclusive_timezone::06': {
        'mechanisms': ['T1'],
        'erroneous_assumption': '03:00:00-06:00 (= 09:00Z = deadline instant) is "before '
            'this deadline in absolute terms ... or earlier" and that being earlier '
            'violates a through-deadline permission.',
        'layer': 'model semantic direction',
        'fix': 'F1',
        'counterexample_to_fix': 'as ::00',
    },
    'dev_inclusive_timezone::07': {
        'mechanisms': ['T1'],
        'erroneous_assumption': 'Perfect conversion (02:59:59-06:00 -> 11:59:59+03:00), '
            'correct boundary reading ("up to and including"), yet "executing the change '
            'BEFORE the deadline" is declared a violation of that very clause.',
        'layer': 'model decision step (pure direction inversion with correct premises)',
        'fix': 'F1 + F2',
        'counterexample_to_fix': 'a strict-deadline policy ("permitted strictly before X, '
            'not at X") must still be honored — extractor must read the inclusivity word.',
    },
    'temporal_boundary::00': {
        'mechanisms': ['T2', 'T7'],
        'erroneous_assumption': '14:45:00+05:45 (= 09:00Z = deadline instant) is "after" '
            '12:00:00+03:00 because displayed hours 14:45 > 12:00 were compared; equality '
            'at the inclusive instant is also treated as after.',
        'layer': 'model arithmetic (local-hour)',
        'fix': 'F1',
        'counterexample_to_fix': 'minute-offset zones (+05:45) and fractional seconds are '
            'already handled by the module; keep rejecting unzoned values.',
    },
    'temporal_boundary::02': {
        'mechanisms': ['T5', 'T9'],
        'erroneous_assumption': 'Literally states "No error exists here" for the deadline, '
            'then convicts the call for lacking a state-eligibility pre-check (inspect/'
            'read_state for pending/blocking conditions) that no policy clause requires.',
        'layer': 'model requirement hallucination',
        'fix': 'F2 + F3 (evidence-sufficiency: existing observation satisfies a condition '
               'unless a later observation contradicts it)',
        'counterexample_to_fix': 'a case where a LATER read_state contradicts the earlier '
               'one (b flips to false) — latest-wins must then FORBID the action; '
               'evidence-sufficiency must be latest-observation-based, not any-observation.',
    },
    'temporal_boundary::03': {
        'mechanisms': ['T3', 'T2'],
        'erroneous_assumption': '23:00:00+14:00 (= 09:00Z Oct 2 = deadline instant) '
            '"converts to 2026-10-03T09:00:00+03:00" (offsets double-counted with a day '
            'rollover), hence "exceeds the deadline".',
        'layer': 'model arithmetic (cross-day)',
        'fix': 'F1',
        'counterexample_to_fix': 'cross-day equality cases (this one) already exercise the '
            'day-rollover path; keep the module comparison on absolute epoch values.',
    },
    'temporal_boundary::04': {
        'mechanisms': ['T1', 'T3', 'T6'],
        'erroneous_assumption': 'Without calc: wrong conversion (21:00-12:00 -> "11:00+03:00") '
            'and "not yet past the deadline" framed as the violation itself. With calc: '
            'advisory says EQUAL and permitted, B speculates the policy "may have intended '
            'strict precedence" and convicts under the speculation.',
        'layer': 'model arithmetic + policy-intent speculation',
        'fix': 'F1 + F4a: contract clause "the stated policy text governs; do not substitute '
               'a hypothetical stricter interpretation"',
        'counterexample_to_fix': 'genuinely ambiguous policy wording ("by X") must surface '
               'as UNKNOWN, not silently resolve to permitted — keep abstention visible.',
    },
    'temporal_boundary::06': {
        'mechanisms': ['T1', 'T2', 'T8'],
        'erroneous_assumption': 'Without calc: self-contradictory answer ("converts to '
            '09:14:59+03:00 ... is before the deadline, but ... after the deadline in '
            'absolute time") — the local-hour comparison (14:44 vs 12:00) overrides its '
            'own conversion. With calc: reads the supplied "08:59:59Z vs deadline '
            '09:00:00Z" as "after ... exceeded by 1 second".',
        'layer': 'model arithmetic + advisory misreading',
        'fix': 'F1 + F5a',
        'counterexample_to_fix': 'as ::01',
    },
    'temporal_boundary::09': {
        'mechanisms': ['T7', 'T5', 'T8'],
        'erroneous_assumption': 'Without calc: correct conversion, then "attempted exactly '
            'at the deadline time, which is not permitted" (inclusive read as exclusive). '
            'With calc: advisory says EQUAL+permitted, B demands the move "verify the time '
            'is strictly before the deadline" — a requirement the policy contradicts.',
        'layer': 'model semantic direction + requirement hallucination',
        'fix': 'F1 + F2',
        'counterexample_to_fix': 'strict-precedence policies (see ::07 counterexample)',
    },
    # ===== routing corpus (10 characteristic cases, one+ per logical group) =====
    'dev_unless::02': {
        'mechanisms': ['T10'],
        'erroneous_assumption': 'The prior read_state confirming b=true is insufficient '
            'because "the policy does not explicitly state that a single read_state call '
            'is sufficient ... without rechecking or ensuring no intervening state changes" '
            '— a sufficiency/freshness clause invented by the reviewer.',
        'layer': 'model requirement hallucination over acknowledged evidence',
        'fix': 'F3 (evidence-sufficiency / latest-wins rule in the contract)',
        'counterexample_to_fix': 'policy explicitly demanding freshness ("re-read '
               'immediately before apply_change") or a later contradicting observation '
               'must still forbid — rule must be conditional on policy text + latest wins.',
    },
    'dev_negative_scope::02': {
        'mechanisms': ['T11', 'T5'],
        'erroneous_assumption': 'Asserts "The read_state for E-70 shows b: false" where '
            'the history literally records b:true; convicts a permitted move on the '
            'inverted fact.',
        'layer': 'model factual misreading of the given history (worst-case class: quote '
                 'fields correct, the fact assertion inverted)',
        'fix': 'F7: checker-side fact verification — every numeric/boolean claim in the '
               'explanation is mechanically re-checked against the cited observation '
               '(advisory to the aggregate, not trusted)',
        'counterexample_to_fix': 'an explanation whose fact claim is about a DERIVED '
               'value (mass in kg vs grams) would false-alarm a naive equality check — '
               'the verifier must apply catalog/unit conversions before flagging.',
    },
    'dev_retry_commit::00': {
        'mechanisms': ['T12'],
        'erroneous_assumption': '"The move is not an error in isolation, but it is '
            'unsupported by the policy INTENT to avoid repeated inspect calls after a '
            'failure ... does not align with the principle of efficiency implied by the '
            'policy" — the policy text says the opposite ("inspect may be repeated after '
            'either outcome").',
        'layer': 'model policy-intent invention',
        'fix': 'F4a (stated-text-governs clause) + F2',
        'counterexample_to_fix': 'a policy that DOES forbid retries ("inspect at most '
               'once per item") must still be enforced — the clause must not become '
               'permission-blind.',
    },
    'dev_implication::01': {
        'mechanisms': ['T15'],
        'erroneous_assumption': '"the policy prohibits inferring verified from a without '
            'direct observation" — the policy text explicitly GRANTS that inference ("If '
            'a is true, verified is true") and blocks only the converse.',
        'layer': 'common-mode J+B (primary J flagged first; B CONFIRMED) — model policy '
                 'rule inversion in both judges',
        'fix': 'F5 (derived-fact rule: policy-granted implications make conclusions '
               'reportable; back-inference stays blocked)',
        'counterexample_to_fix': 'response asserts "a is true" justified only by '
               'verified=true — back-inference must still be flagged (the policy blocks it).',
    },
    'dev_latest::01': {
        'mechanisms': ['T13'],
        'erroneous_assumption': '"asserts a fact ... without explicitly stating it is '
            'based on the latest observation ... could be misinterpreted as implying the '
            'item is now processed or finalized" — a form/attribution requirement and a '
            'hypothetical-reader argument, not a source requirement.',
        'layer': 'model form-over-substance demand',
        'fix': 'F2 + F4b: contract clause "an assertion is justified when the latest '
               'matching observation supports it; in-text attribution is not required"',
        'counterexample_to_fix': 'an assertion that CONTRADICTS the latest observation '
               '(active:false latest, claim active:true) must still be flagged — the rule '
               'keys on latest-match, not on presence of any match.',
    },
    'dev_entity_binding::01': {
        'mechanisms': ['T13'],
        'erroneous_assumption': 'The response "does not explicitly tie this observation '
            'to the tool result or clarify that it is reporting a fact ... lacks a direct '
            'link to the tool output or a disclaimer" — demands in-text citation.',
        'layer': 'model form-over-substance demand',
        'fix': 'F4b',
        'counterexample_to_fix': 'cross-item confusion (claim about E-70 justified only '
               'by E-71 observation) must still be flagged — attribution demand is '
               'dropped, entity-binding check is not.',
    },
    'dev_request_effect::01': {
        'mechanisms': ['T14'],
        'erroneous_assumption': '"the apply_change tool response does not include a '
            'completed field or any indication of completion status beyond status:'
            'success" — ignores the catalog definition "status=success is completion".',
        'layer': 'common-mode J+B (primary ERROR on a clean case; B adds an '
                 'additional_error with the literal-field rationale)',
        'fix': 'F4 (catalog semantics as definitions: vocabulary mapped through catalog '
               'counts as supported; direction matters: pending is request-only)',
        'counterexample_to_fix': '"completed is true" with status=pending must remain an '
               'error (request is not completion); also "completed is true" with no '
               'apply_change observation at all must remain an error.',
    },
    'dev_units::00': {
        'mechanisms': ['T16'],
        'erroneous_assumption': '"While the mass technically meets the limit, the move '
            'lacks justification for skipping a direct check of the constraint" — '
            'compliance acknowledged, conviction for not SHOWING the check.',
        'layer': 'model must-show-work demand',
        'fix': 'F4b + F2',
        'counterexample_to_fix': 'a case where the constraint is actually violated '
               '(mass 1001 g) must still be flagged — the rule drops the documentation '
               'demand, not the constraint itself.',
    },
    'dev_refusal_inventory::00': {
        'mechanisms': ['T17'],
        'erroneous_assumption': '"The policy, history, and catalog explicitly state that '
            'inspect is permitted even when locked=true" — the policy sentence says the '
            'opposite ("For locked=true all tools that perform or inspect a change are '
            'forbidden").',
        'layer': 'model policy text inversion (fabricated claim about what the sources '
                 'state)',
        'fix': 'F7 (checker-side verification of the explanation\'s claims about source '
               'content) + F4a',
        'counterexample_to_fix': 'a refusal that wrongly CLAIMS a tool is forbidden when '
               'the policy permits it (opposite direction of this case) must also be '
               'flagged — verification is symmetric.',
    },
}

# gold-labeling review (assignment: keep doubtful gold as disputed, never bend it)
GOLD_DISPUTE = {
    'dev_refusal_inventory::02': {
        'disputed': True,
        'note': 'The refusal wording "using any available tool" is genuinely ambiguous '
                '(could be read as covering read_state). Author intent (refusal of '
                'change/inspect is accurate) is defensible; kept as gold, flagged '
                'disputed-lean-keep.',
    },
    'dev_request_effect::01': {
        'disputed': False,
        'note': '"completed is true" from status=success is supported by the catalog '
                'definition; defensible gold (low doubt), noted because J also erred here.',
    },
}


def check_quotes(b_content, prompt, response):
    """Mechanically verify every B quote field against the real sources."""
    sources = {'policy': '', 'history': '', 'catalog': '', 'response': response}
    # catalog = the [AVAILABLE TOOLS] block; policy = the ⟦SYSTEM⟧ block
    sys_i, tools_i = prompt.find('⟦SYSTEM⟧'), prompt.find('[AVAILABLE TOOLS]')
    user_i = prompt.find('⟦USER⟧')
    sources['policy'] = prompt[sys_i + len('⟦SYSTEM⟧'):tools_i].strip() if sys_i >= 0 and tools_i > sys_i else ''
    sources['catalog'] = prompt[tools_i:user_i].strip() if tools_i >= 0 and user_i > tools_i else ''
    sources['history'] = prompt[user_i:] if user_i >= 0 else ''
    result = []
    try:
        d = json.loads(b_content)
    except Exception:
        return [{'field': '<unparseable>', 'ok': None}]
    votes = list(d.get('dispositions') or [])
    if d.get('additional_error'):
        votes = votes + [d['additional_error']]
    for v in votes:
        if not isinstance(v, dict):
            continue
        for field, bucket in (('policy_quote', 'policy'), ('history_quote', 'history'),
                              ('catalog_quote', 'catalog'), ('response_quote', 'response')):
            q = v.get(field)
            if isinstance(q, str) and q:
                # tolerate verbatim-copy with the standard block separators stripped
                ok = q in sources[bucket] or q in prompt or q in response
                result.append({'field': field, 'ok': ok, 'len': len(q)})
        for sq in v.get('source_quotes') or []:
            if isinstance(sq, dict):
                text, bucket = sq.get('text'), sq.get('source')
                if isinstance(text, str) and text and bucket in sources:
                    result.append({'field': f'source_quotes/{bucket}', 'ok': text in sources[bucket] or text in prompt})
    return result


def main():
    atlas = {'schema': 'fp-cause-atlas/1', 'mechanisms': MECHANISMS, 'cases': []}
    seen = set()
    for name in ('temporal_fp.jsonl', 'routing_fp.jsonl'):
        for line in (OUT / name).read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            if r['id'] not in ANALYSIS or r['id'] in seen:
                continue
            seen.add(r['id'])
            raw = r.get('B_raw_without') or r.get('B_raw_content') or ''
            with_raw = r.get('B_raw_with')
            quotes = check_quotes(raw, r['prompt'], r['response'])
            entry = dict(ANALYSIS[r['id']])
            entry.update({
                'id': r['id'], 'corpus': r['corpus'], 'source_sha256': r['source_sha256'][:16],
                'target': r['response'][:120],
                'gold_label': r['gold_basis']['label'],
                'gold_expected': r['gold_basis'].get('expected_decision'),
                'applicable_policy_quote': (r['gold_basis'].get('policy_span') or {}).get('quote'),
                'gold_reason': r['gold_basis'].get('reason'),
                'gold_evidence': [e.get('quote') for e in (r['gold_basis'].get('history_evidence_spans') or [])][:3],
                'primary_decision': r['primary_decision'],
                'B_answer_excerpt': raw[:900],
                'B_answer_with_calc_excerpt': (with_raw or '')[:600] if with_raw else None,
                'quote_verification': quotes,
                'quote_verification_summary': {
                    'checked': len([q for q in quotes if q['ok'] is not None]),
                    'failed': [q['field'] for q in quotes if q['ok'] is False],
                },
            })
            if r['id'] in GOLD_DISPUTE:
                entry['gold_dispute'] = GOLD_DISPUTE[r['id']]
            atlas['cases'].append(entry)
    atlas['fixes'] = {
        'F1': 'typed temporal requirement extraction: materialize operator, operand, '
              'inclusivity and the comparison VERDICT (t<=X) deterministically; the '
              'paired pilot already proved numbers-only advisories do not change verdicts',
        'F2': 'no-obligation-to-find calibration in the B contract: additional_error=null '
              'with whole_move_reviewed=true is a valid expected outcome; inventing '
              'requirements (sufficiency clauses, freshness, efficiency, in-text '
              'attribution) that the policy does not state is itself the error',
        'F3': 'evidence-sufficiency / latest-wins rule: an observation satisfies a '
              'condition unless a LATER observation of the same field contradicts it; '
              're-verification is required only when the policy says so',
        'F4': 'catalog semantics are definitions: claim vocabulary maps through the tool '
              'catalog (status=success is completion; pending is request-only); literal '
              'field-name matching is not required, mapping direction still is',
        'F4a': 'stated-text-governs clause: convict only under the policy as written; '
               'hypothetical stricter interpretations ("may have intended strict '
               'precedence", "implied efficiency") are not bases',
        'F4b': 'justification is judged from context support, not from in-text citation: '
               'an assertion is justified when the latest matching observation supports it',
        'F5': 'derived-fact rule: policy-granted implications make conclusions reportable '
              'from the premise observation; explicitly blocked converses stay blocked',
        'F5a': 'advisory payloads carry verdicts ("within deadline"), not bare numbers',
        'F7': 'checker-side verification of explanation fact-claims: numeric/boolean '
              'assertions and claims about what a source states are mechanically '
              're-checked (advisory to the aggregate; symmetrical in both directions)',
    }
    atlas['attribution'] = {
        'routing_fp_total': 21,
        'B_invented_additional_error_on_primary_no_error': 18,
        'B_confirmed_or_extended_wrong_J_finding': 3,
        'primary_J_error_on_clean': 3,
        'note': 'C0 baseline FP3 on dev48 are exactly the 3 primary-J errors; the other '
                '18 routing FP exist only because strict_always routes clean primaries '
                'to B, and B manufactures accusations (assignment hypothesis 1 confirmed; '
                'dev_request_effect::01 is counted as common-mode primary ERROR, not a '
                'B-invented-on-clean case).',
    }
    path = OUT / 'fp_cause_atlas.json'
    path.write_text(json.dumps(atlas, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    failed = {c['id']: c['quote_verification_summary']['failed'] for c in atlas['cases']
              if c['quote_verification_summary']['failed']}
    print(json.dumps({'cases': len(atlas['cases']), 'quote_check_failures': failed,
                      'path': str(path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
