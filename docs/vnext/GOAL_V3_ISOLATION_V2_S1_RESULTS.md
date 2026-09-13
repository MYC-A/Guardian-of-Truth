# Goal v3 isolation v2 — partial S1 result

Authoritative run outcome: **BUDGET_STOP / USAGE_UNVERIFIABLE**, not KEEP,
REJECT, or a completed preregistered REJECT_EARLY. Session 85340 terminated
with exit code 0. The runner attempted 10 of 12 S1 cases, sealed that exact
prefix, then scored it. S1's final 2 cases, S2's 36, and S3's 12 are NOT_RUN.
No provider/prompt/schema/benchmark/gold/scorer/gate was changed after inference.

## Exact implementation and integrity

```text
Goal v3 evaluated implementation:
commit = ba437965a99ece855eb5589a6b5c690728924b1f
prompt/schema version = guardian-goal-v3-isolation-frontend-v2
provider/model = Groq / qwen/qwen3.8-27b
prompt SHA256 = acff1427839280d828cb520fb95bd1807f2a734f56ecfd17c7a25cb76c8646ba
schema SHA256 = b88ff0c9abff4c78520dda02eb57398e385dd2cbb3dd3702151ffcf4c9ca55cc
```

The 60-case inputs, independently authored gold, stage inventory, source
hashes and full configuration were frozen and committed before the first
external request. Complete freeze SHA256:
`1a9b3428dff6693e7cd8e4d7ee24af91a0330b5d441dcd1a4205cd9a206bf82a`.
S1 prediction seal SHA256:
`16e31126f7e817bdeea620e1023b4f11df6c9165ff8b57072492a7b0af71ec74`.
Both the frozen runner's replay and a separate gold-free physical receipt
audit validate lineage and the one permitted identical-payload transport retry.
The independent audit makes no model calls and opens no gold.

Corpus scope: 24 pairs/48 core cases across F1–F16 plus 12 composition/NL
stress cases. Development-aware controlled license scenarios, not a blind
holdout or competition distribution. Seven cases are outside the exact USER
parser; four retain definitive behavioral gold. They were not relabelled to
improve coverage, but none of these stress/unknown-language cases was reached.

No Policy input/parser/verdict/features contributed to this isolation path.
Legacy Detector modules are passively imported by package initialization;
they do not execute a Policy semantic evaluation here. General Core and
real competition trace integration remain absent.

## Historical baselines, unchanged

Historical Goal/Plan v2: 22/22 UNRESOLVED, zero definitive certificates,
190 physical requests, 361,883 reported tokens; financial cost NOT_AUDITED.
Goal v3 isolation v1 S1: 12 cases, 12 requests, 9/12 candidate status matches,
0/12 under its frozen full-behavior scorer, zero certificates, 69,142 tokens.
These use different cases/contracts and cannot establish a paired improvement.
Historical code, frozen inputs, results and v1 stored admission are unchanged.

## Cost and capture

| Measure | Observed |
| --- | ---: |
| Semantic cases attempted / S1 requested | 10 / 12 |
| Admitted physical requests / transport retries | 11 / 1 |
| Successful deliveries | 9 |
| Raw / postrepair schema-valid deliveries | 0 / 0 |
| Reported input / output / total tokens | 9,092 / 5,121 / 14,213 |
| Usage complete | No |
| Financial cost | Not provided; not estimated |

Reported totals cover available successful-response usage, not a verified
total for all 11 physical requests. Tokens/case is null in the authoritative
cost receipt because usage is incomplete. Reported successful output lengths
range 362–833, all below the configured 2,048 allowance. No output cap overrun
was observed; no measured caching savings are available.

The user relaxed external-token economy before freeze. Cost ceiling
enforcement was disabled; **no numerical token-spend limit caused this stop**.
The separate missing-usage integrity gate remained enabled. `V2P13:b` received
two `rate_limit` errors (HTTP-category mapping), separated by the frozen
2-second retry backoff, with no reported usage. The runner therefore stopped
before the next case. Whether this was per-minute, daily, shared-account or
another provider limit cannot be determined from sanitized receipts.

## Metrics and gates

All nine delivered objects were rejected with `SCHEMA:TYPE_MISMATCH`.
Issue counts by case: 9, 9, 12, 2, 2, 6, 6, 2, 8. Repair code was NONE;
exact JSON decoded, but its typed structure was unusable. No semantic retry,
coercion, corrective model prompt, challenger or judge was used.

Consequently, all 10 **effective capture statuses** are UNRESOLVED. This is
not evidence that the LLM itself judged every goal ambiguous. Proposals are
null after schema rejection, and no calculus/semantic certificate was obtained.
The sealed scorer records behavioral/status correctness 0/10, resolution and
certified coverage 0, and no unsafe definitive outputs. That safety is a
fail-closed capture property, not demonstrated semantic competence.
Gold-UNKNOWN preservation is 0/1 because invalid capture earns no credit;
it must not be interpreted as an observed unsafe model judgement.

| Frozen gate | Evidence / decision |
| --- | --- |
| S1 usable schema ≥10/12 | 0 of 10 attempted; not evaluated as complete S1 |
| S1 status matches ≥6/12 | 0 of 10 attempted; not evaluated as complete S1 |
| S1 incorrect definitive proposals =0 | None usable; safety only by abstention |
| Optimistic core pairs ≥22/24 | Post-seal bound ≤14/24; complete pairs 0 |
| Usage integrity | FAIL; formal BUDGET_STOP |
| S2 core safety/coverage/certificate floor | NOT_RUN |
| S3 stress ≥80% readiness signal | NOT_RUN |

Ten distinct sampled pair members cannot be correct under the frozen scorer,
so even perfect remaining members could yield at most 24−10=14 correct pairs.
This is an offline implication, **not** permission to relabel the formal stop:
the frozen smoke gate evaluates its semantic admission only at 12 cases, and
the accounting stop takes precedence. No pair accuracy was measured because
no complete pair was inferred.

Families reached: F1 1, F2 1, F3 1, F5 1, F6 1, F8 1, F9 1, F10 2, F11 1.
All have zero usable behavioral matches/certificates. F11's attempted case
failed transport. F4/F7/F12/F13/F14/F15/F16 were not measured. The frozen
summary includes null empty-family entries for F13/F14; null is not failure.
Actor-attribution accuracy 0/2 reflects unusable capture on tool-annotated
guard cases, not a verified actor-confusion mechanism. Failed-effect and
intent/completion rates are null, not zero.

## Dominant failures and capture limitations

Confirmed: a systemic typed-output boundary failure, plus an accounting
stop on provider rate limits. The prompt lists keys/enums but does not embed
the full JSON schema or spell out every distinction between four-valued
truth strings, Boolean closure flags, empty objects and arrays. These are
plausible causes to test in a **separate** version, not established actual
field-level errors: invalid raw objects were deliberately not retained, and
saved diagnostics contain codes without paths. Their exact offending fields
cannot be reconstructed from completion hashes.

Offline DTO and synthetic-provider tests were green (1,477 full project
tests), but tested already-correct typed objects, not this model's real
output-format adherence. They do not override the external failure.
No frozen JSON is repaired/rescored now; no unseen labels are used to
silently revise Goal semantics.

## Q1–Q8 and verdict

- Q1: Alternate-path and auxiliary cases were attempted, but schema failure
  prevents proving that the external frontend avoids invented mandatory plans.
- Q2: An explicit prerequisite was attempted; preservation is unproven externally.
- Q3: A future deadline was attempted; the distinction is covered offline,
  not established by usable external output.
- Q4: Independent violation plus unrelated UNKNOWN failed transport; unmeasured.
- Q5: A decisive unknown guard was delivered but schema-invalid; unproven externally.
- Q6: Wrong-entity/guard cases were unusable; agent/user, intent and failed-effect
  cases were not reached. Offline tests are not external coverage evidence.
- Q7: No certified coverage gain over historical v2; no paired comparison.
- Q8: Not ready for Goal+Policy/Core composition. Immediate blockers are
  typed model output and the failed-request usage stop; general NL authority
  and real trace linkage remain separate integration limitations.

Formal verdict: **BUDGET_STOP / INCOMPLETE**. No semantic KEEP/REVISE/REJECT
is justified for a completed Goal experiment. The current candidate is not
promoted. A new extraction-contract experiment could preregister explicit
schema/types, value-free path/type diagnostics and a clarified failed-request
accounting rule. It must be separately frozen; it cannot restart/retry or
overwrite these sealed cases. Such a next experiment requires direction.

This proves exact capture/retry/seal reproducibility and failure-closed
behavior of this run. It does not prove Goal v3 semantic correctness,
general-language authority, contest score gain, or whole-Core readiness.
