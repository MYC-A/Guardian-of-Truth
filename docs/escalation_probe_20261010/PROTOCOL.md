# Escalation / refusal probe — protocol (written before any generation)

## Hypothesis
B2 misses "premature escalation / false refusal": the agent transfers to a human or says it cannot help while
an available tool could handle the user's request. A narrow question with a checkable answer catches these
without new false positives.

## Trigger (code only, domain-independent)
Current assistant turn either
- calls a catalog tool whose name matches `transfer|escalat`, or
- makes no tool call and its text contains a refusal / hand-off phrase (RU regex: не могу / не смогу /
  не имею возможности / невозможно / перевед…|передам…|соедин… на/с специалист|оператор|сотрудник|человек).
Untriggered rows: decision = B2, byte-identical.

## Probe (one model call per triggered row, greedy, JSON)
Input: the row prompt (policy + catalog + history) and the current turn. Question: "Name ONE tool from
[AVAILABLE TOOLS] (not a transfer tool) that the agent could have called now to make progress on the user's
latest request, which the agent has not already called with the same arguments; give arguments taken from the
visible history, a verbatim history quote supporting them, and a verbatim policy quote showing this tool is
allowed for this request. If no such tool exists, or policy requires the transfer/refusal, answer null."

## Code verification (all must pass, else abstain)
1. tool ∈ parsed catalog, not a transfer tool; catalog parse not abstaining (contract-lint parser).
2. arguments pass contract-lint schema check (required present, types, enums, no unknown params).
3. (tool, canonical args) not already called in history.
4. every scalar argument value occurs verbatim in the history part of the prompt (not only in the catalog/policy).
5. history_quote and policy_quote occur verbatim (whitespace-normalised, ≥20 chars) in the prompt.
Verified → ERROR. Final = B2 OR verified. The probe never turns ERROR into NO_ERROR.

## Evaluation
- Rows: all triggered rows across decision pools (ext_tau2 … frozen) + valid46, deduplicated (expected ~19).
- 3 independent probe repeats (same server, separate passes).
- Report per repeat: fires, true/false fires, new TP / new FP vs B2 per pool family; valid46 F1 of
  (tb1..tb3 + UNKNOWN_TOOL HARD) ± probe, i.e. 3×3 combinations.

## Acceptance (fixed now)
- New FP: at most 0 on the majority-of-3 probe over ALL triggered negatives (decision pools + valid46), and no
  single repeat with >1 new FP.
- Gain: ≥2 new TP in the majority-of-3 probe on all triggered rows.
- Otherwise REJECT. No post-hoc changes to prompt/verification; any amendment is reported as post-hoc and needs
  a fresh 3-repeat run.
