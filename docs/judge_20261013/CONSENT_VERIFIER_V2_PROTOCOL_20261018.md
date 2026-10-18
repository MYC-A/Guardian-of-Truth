# Direct authorization verifier v2 — frozen pilot, 18 October 2026

Research only. No production changes, no LoRA training, no automatic veto.
Freeze this protocol before new quality results. The rejected v1 remains unchanged.

Stage 1 asks an affirmative question: does the history clearly authorize the exact
action in the current call? YES requires matching action, object, quantity and
price, with no withdrawal or unresolved alternatives. Earlier unchanged approval
can remain valid. NO means authorization is not established, not that an entire
turn is necessarily wrong. Eligibility is explicitly a separate question.
Use exact log P(YES)-log P(NO), including the existing approved token aliases.
The preregistered zero boundary produces a MODEL_HYPOTHESIS, never a proof.

Stage 2 evaluates the WHOLE current turn under the existing full judge definition
and checklist, with this hypothesis appended. It retains independent checks of
eligibility, arguments, policy, unsupported claims, tool results and refusals.
The judge can disagree with the verifier. Approval never directly changes a label.
Compare a fresh matched final without this new hypothesis to a fresh augmented
final. For real cases the baseline is the byte-identical saved strict final;
existing notes are retained in both arms. Stage 1 sees only its saved source,
without the old allegation. Source context is never trimmed to add the hypothesis.
Oversize or inexact new scores preserve the original score for that row; do not
silently regenerate NO or replace successful rows with overall.

Pilot: all 98 previously inspected synthetic controls, including revoked consent
and independent eligibility failures; plus ALL 20 real cases selected by the
frozen v1 label-blind eligibility rule. This includes both previously lost TP.
No new gold is read by the runner. At most 354 one-token requests plus the exact
scoring probe, one Qwen3.6 AWQ loading, same eager/APC/batch16 configuration.
Record source, rendered input and token hashes, exact coverage and timings.

Analysis reads gold separately. On synthetic controls report authorization
accuracy against the construction oracle independently of whole-turn errors;
report whole-turn zero-logodds diagnostics and ranking, not a tuned threshold.
For real cases compare fixed quotas .30/.40 with hard overrides. Unselected
scores are frozen originals in both arms: this is a conditional paired replay,
not a fresh full397 repeat. Report newly lost/gained TP and FP, not just net F1.
Report valid46 as a subset only if affected cases exist; never count it twice.

Gate before any larger run: no newly missed synthetic violations, all explicit
no-consent/revocation/object/value/action/changed-offer controls remain detected,
no lost real TP at either fixed quota, and at least one corrected real FP at .40.
These are exploratory screening conditions, not production acceptance. If the
pilot fails, stop this version, publish the exact failures and do not tune a new
prompt on the same cases and present that as independent confirmation. dev520
has zero eligible actual tool calls and cannot validate this binding mechanism.
eval1893 stays untouched until a justified broader candidate exists.
