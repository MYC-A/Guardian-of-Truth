# Results: local cause recovery, inconsistent final decisions

The correct Telecom cause was independently explained in A, B and C without the
previous D0 verdict/explanation. **Only B also emitted the correct final ERROR.**
A/C's NO_ERROR contradicts their own correct violation reasoning; it was not
changed by decoding or scoring. All review arms used oracle-selected sources.
This is not evidence of improved valid46 F1 or unseen-domain generalization.

Historical D0 is a post-hoc reference only: it emitted the correct binary ERROR
while charging historical/user payment calls and calling current resume correct.
The new B improves that local causal explanation, not the already correct label.
Historical D0/P3 content was never input to A/B or AUTO.

| Job | Emitted verdict | Correct core cause/contrast | Target / policy / source IDs | Admission | Inference HTTP | Known tokens |
|---|---|---|---|---|---:|---:|
| A independent | NO_ERROR | Yes in explanation; full recovery fails | Correct | Pass | 1 | 7,178 |
| B + code facts | ERROR | Yes; full local recovery | Correct | Pass | 1 | 8,325 |
| C + factual conflict | NO_ERROR | Yes in explanation; full recovery fails | Correct | Pass | 1 | 8,621 |
| Read-only synthetic | NO_ERROR | Avoids inventing current resume | Correct | Pass | 1 | 7,987 |
| Future-contract synthetic | NO_ERROR | Avoids expired-contract accusation | Correct | Pass | 1 | 8,580 |
| Payment synthetic | No answer | Unmeasured | Unmeasured | BUDGET_STOP | 0 | 0 |
| AUTO source plan | No semantic verdict | Relevant norms found, actual line receipt omitted | Valid plan IDs | Pass | 1 | 4,398 |
| AUTO final review | No answer | Unmeasured | Unmeasured | BUDGET_STOP | 0 | 0 |

All five review replies have empty open_questions, including A/C despite the
contradiction. Admission checks schema, native target, source namespaces and
actors; it does not prove applicability or internal semantic consistency.
Separate source-grounded human assessments and rationales for all ten requested
criteria are in [causal_score.json](../../outputs/telecom_causal_recovery/v1/causal_score.json)
and [annotations](../../outputs/telecom_causal_recovery/v1/causal_annotations.json).
`cause_correct` assesses explanatory content; `complete_original_cause_recovery`
also requires the correct emitted decision and all criteria. Synthetic contrast
success never receives an invented official binary gold.

## What did and did not help

A already identified the correct expired-contract prohibition, original line,
date comparison and independent payment scope. B's final field matches that
meaning in this trial. This does not establish that mechanical facts caused
the improvement or first revealed the rule: one sample per arm is insufficient.
C shows no added benefit over B and another inconsistent final field. Neither
A nor B saw D0/P3, official gold, explanation or other-arm output. C received
only original actor/currentness conflicts, not the old semantic answer.

Read/future controls passed their specific negative contrasts. The future copy's
NO_ERROR is not a certified global whole-move negative: unrelated prerequisites
and other bill statuses were not independently relabeled. The payment contrast
was not measured; no claim of robust payment invariance across variants follows.
Original B does correctly say paid bills do not waive the independent ban.

## Automatic source discovery

The automatic planner saw the full code-owned section/event catalog and original
declarations, not the oracle evidence set. It selected complete reads of q7, q9,
q17, q10, q11, q12, q15 and q24. q7/q17 contain the relevant norm and explicit
system time. It selected **zero history events**, so h9/h10 line identity/receipt/
contract date and latest user intent were not retrieved. This is an observed
incomplete evidence-selection plan, not a negative semantic reviewer result.

The final review was not sent: its reservation was 25,498 against remaining
14,911. Normative source discovery succeeded locally; complete causal evidence
discovery failed in this plan; final automatic semantic correctness is
**NOT_MEASURED_BUDGET_STOP**. A single <=8-operation plan cannot establish the
limits of adaptive search or a future graph retriever. The AUTO gate used the
pre-registered A explanatory-cause success, explicitly retaining A's wrong label;
it was not a retrofit declaring A fully successful.

## Cost, integrity and reproduction

Total **6 successful inference HTTP calls / 45,089 known=charged tokens**.
No unknown usage, retries, fallback, 402/429, hidden truncation, model weights or
local inference server. One metadata GET was separate from inference; public
tokenizer cache required no download. The payment request reservation was 20,876
against 19,309 before AUTO, so it stopped before credentials/network. Budget
stops have `decision: null`, not model UNKNOWN.

Raw provider strings, exact bodies and source packets remain in the research
output directory. A/C raw NO_ERROR is preserved. Core predictions stayed
byte-identical after AUTO; the ledger only gained the one AUTO plan entry.
All inference code, templates and input hashes still match preparation commit
`fd8efa9f`; tools/docs after it are post-hoc, outside inference source.
The earlier zero-call preparation is also preserved.

174 relevant tests passed before inference, and subagents independently reviewed
code and logical source interpretation. Offline replay reproduces core and AUTO
predictions exactly with unchanged ledger and zero network/credential access.
Both Windows and server replay passed; a reviewer independently repeated replay
on a temporary copy.
See [runbook](RUNBOOK.md), [failure analysis](FAILURE_ANALYSIS.md) and
[final decision](FINAL_DECISION.md). No production, prior research source/results,
original valid.parquet or original gold was changed.
