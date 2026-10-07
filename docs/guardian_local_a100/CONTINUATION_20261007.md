# Fast-circle continuation

User transferred publication ownership on 2026-10-07. Existing Distill inference
is preserved. No new Ministral, no paid LLM API, no production/default change.

Finite supervised job `guardian-fast-circle` waits for the existing Distill shell
using Linux pidfd (maximum three hours, no model polling). It offline-scores all
70 rows for AM/A/M and B2, saves and pushes receipts, verifies remote SHA, and
only then stops the exact Distill model server. Already downloaded weights are
retained: no download or deletion is necessary for this continuation.

Next: Lynx IQ4_XS, pinned revision 581017200918d887e8171efc4b083979a74444ab,
native document/question/answer JSON with REASONING and SCORE, 8000-token context
per slot, 1024 completion reserve, same 20k-byte source view. Template/tokenizer
preflight refuses inputs that do not fit. No context shifting or silent trimming.
Two native clean/error smoke inputs must pass before the 70-row grounding lane.
Current turns and Distill A/B2 accusations are separate checks. Factual support
is not policy compliance; TP row membership is not proof of a correct cause.
Source-view incompleteness is retained in receipts. This is a new wire/version;
the old unused Lynx adapter and historic outputs remain unchanged.

Fixes required before execution: old Lynx uses nonexistent Executor.starmap and
parses first-token PASS/FAIL instead of the native JSON model-card contract.
New implementation uses map, full JSON validation, receipt failure gating,
exact request packets, durable per-row writes and phase-checked resume. Saved
AM and B2 accusations are loaded separately, rather than overwriting each other.

The untracked predecessor comparison double-counts rows and would make full
coverage 0.5. It is preserved. New offline first_circle_qa counts each row once,
requires all three sets and reports common valid46 coverage. `extra_pass` is an
overlapping verdict diagnostic, not another row. Missing or technical rows stay
visible. Existing PLAN did not state whether A or B2 valid46 F1 was primary;
both diagnostic rankings are reported. No retrospective preregistration claim.
Output budgets/modes differ between historical model circles and must be shown;
this quick diagnostic cannot establish a universal model winner or transfer.

Sources: [official Lynx model card](https://huggingface.co/PatronusAI/Llama-3-Patronus-Lynx-70B-Instruct),
checked 2026-10-07 (native JSON prompt, primarily English, maximum 8000 tokens).
License in the original manifest was provisional; upstream declares CC-BY-NC-4.0,
so this research run does not establish commercial delivery suitability.

Run: `/workspace/guardian/venv/bin/python -m experiments.guardian_local_a100.continue_circle`
under supervisor, autorestart=false. Events/state/comparison:
`outputs/guardian_local_a100/continuation_20261007/`.
Log: `/workspace/guardian/logs/fast_circle_continuation.log`.
Each checkpoint completion and terminal technical failure is committed/pushed.
No checkpoint repeat or architecture sweep is scheduled by this finite job.
Architecture stage 2 requires the completed comparison and a separate frozen plan.

## Speed amendment before native inference

Owner requested faster execution. Existing Distill config and completed rows remain unchanged. Lynx is not yet executed: allocate 8 slots x 8000 context (64000 total), enable Flash Attention, workers 8, native completion reserve 600 (model-card example), replacing the earlier 4 slots / 1024 reserve. Full 70 inputs and accusation checks remain mandatory. No hidden sampling or mixing of inference modes. Actual latency/coverage are measured, not assumed faster. Complete JSON at length remains valid; incomplete outputs stay technical_unjudged. All source/context preflights remain enforced.

## Owner-directed immediate Lynx start

The owner explicitly stopped the remaining Distill B2 cell. Full AM and all completed B2 replies/caches are preserved. Exact partial coverage and missing IDs are in continuation_20261007/distill_stopped_by_owner.json. Missing reviewer rows are NOT_EXECUTED, not negatives. Lynx still processes all 70 current turns and every available A/B2 accusation; unavailable B2 accusations remain explicit reviewer gaps. New flag is frozen before native inference. Partial Distill is not ranked as a complete B2 candidate.

## Native object codec v3

First Lynx smoke produced correct complete PASS/FAIL objects, but with single-quoted REASONING strings and bare SCORE enum tokens. The strict JSON-only adapter rejected both. Original v2 smoke/receipts remain immutable. New phase lynx-native-object-v3 decodes complete objects through JSON or a restricted Python AST literal codec; only the direct SCORE value may be bare PASS/FAIL. No eval, substring search, missing-field inference, duplicate keys, or truncated object acceptance. Same exact two-field schema is checked after decoding and raw output is retained. This is native dialect normalization, not a new model-quality claim.
