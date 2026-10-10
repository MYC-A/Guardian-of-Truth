# Prosecutor → Judge — protocol (written before any generation)

## Hypothesis
Remaining misses are judgement calls where the model sides with the agent. Splitting the roles — a prosecutor that
must build the strongest concrete case, and a judge who may acquit only with verifiable textual grounds — recovers
some misses without many false positives.

## Pipeline (only adds violations: final = base OR fire)
Input for both roles: the row prompt with the escalation-probe history compression (policy + catalog intact,
tool responses ≤1200 chars, history ≤30000 chars) and the current turn.
1. Prosecutor (greedy JSON): one strongest violation committed IN THE CURRENT TURN, with `violation_type`
   (forbidden_action | missing_precondition | wrong_arguments | unjustified_refusal_or_transfer |
   unsupported_claim | tool_misuse | other), `policy_quote` (verbatim, policy/instructions/catalog part),
   `turn_quote` (verbatim from the current turn), optional `history_quote`, `argument`; or `violation: null`.
   Code check: policy_quote ≥20 chars in the pre-history part, turn_quote ≥8 chars in the current turn,
   history_quote (if given, ≥12 chars) in the history (whitespace-normalised). Failing → no accusation.
2. Judge (greedy JSON), only for checked accusations: same context + the accusation. Output `verdict`
   (VIOLATION | NO_VIOLATION), `rebuttal_type` (rule_not_applicable | turn_complies | exception_permits | null),
   `rebuttal_quote` (verbatim from prompt or current turn), `reasoning`.
Decision rules (both fixed now, both reported):
- R1 (plain): fire iff verdict == VIOLATION.
- R2 (burden of proof): fire iff verdict == VIOLATION, or verdict == NO_VIOLATION with a rebuttal_quote that is
  missing/shorter than 12 chars/not verbatim in prompt+turn.

## Rows
- Decision pools (ext_tau2 … frozen), deduplicated, rows where stored B2 Q8 rep1 = 0: 158 (132 negative,
  26 positive). One pass (time). Base = B2 Q8 rep1.
- valid46: all 46 rows, 3 passes. Base = each of tb1..tb3 + UNKNOWN_TOOL HARD (3×3 combinations).

## Acceptance (per rule; a rule is accepted only if ALL hold)
- Decision pools: new FP ≤ 3 of 132 negatives AND new TP ≥ 5 of 26 AND fire precision ≥ 0.7.
- valid46: mean F1 over the 3×3 combinations ≥ base mean + 0.03 AND no pass with > 1 new FP.
If both rules pass, R1 is preferred (fewer assumptions). No post-hoc changes; amendments are reported as such
and require a fresh run.

## Time
Measured: stage seconds per pass; production estimate = rows with base 0 × 2 calls.

## Result (2026-10-10, code 4eb2ad63) — REJECT (both rules)
Time: startup 80 s; pass 0 (206 rows) prosecutor 411 s + judge 109 s; valid46 passes: prosecutor 100–124 s +
judge 33–34 s for all 46 rows (production, base-0 rows only: ≈1.5–2 min). 0 transport errors.
Prosecutor checks (pass 0): ok 55, null 95, unparsed 16, history_quote 25, policy_quote 8, turn_quote 7.
Judge: R1 and R2 identical (every acquittal carried a verbatim rebuttal quote).

| criterion | required | R1 = R2 | pass |
|---|---|---|---|
| decision pools new FP (of 132 negatives) | ≤ 3 | 5 | ✗ |
| decision pools new TP (of 26 misses) | ≥ 5 | 15 | ✓ |
| decision pools fire precision | ≥ 0.70 | 0.75 | ✓ |
| valid46 mean F1 vs base .800 (tb+lint) | ≥ .830 | .733 | ✗ |
| valid46 max new FP per pass | ≤ 1 | 3–4 | ✗ |

- valid46: fires are stable across passes but recover no remaining miss; they hit rows the base already flags plus
  3–4 stable false accusations (airline_10 t21, airline_3 t4, airline_24 t14, one telecom mms negative).
- Decision pools (base = llama.cpp B2 Q8): 15/26 misses recovered at 5 FP — a real signal against a weaker base,
  but it does not transfer to the vLLM base on valid46. Typical FPs: "did not confirm price", "did not verify
  availability", "promised follow-up" — plausible-sounding procedural requirements the policy does not impose
  at that point.
