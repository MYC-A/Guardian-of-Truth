# Code facts: K0, K1 and K2

Independent source/logic review of the eight K/C augmentation calls, with the exact saved I4 replies reused as K0/C0. Machine-readable audit: `outputs/hybrid_mechanisms_v1/augmented_causal_logic.json`. Inputs are two known valid46 development cases and disclosed oracle-selected original source spans. No original gold or frozen prediction was changed.

## What code actually verifies

The mechanical facts attach original actor/kind metadata, native receipt pairing, explicit system time, exact typed raw-field equality and calendar-date comparisons. These are checkable relations on immutable text. They do not establish that a given field is the policy's semantic condition, that a past receipt remains current state, or that all exceptions have been excluded.

| Fact | Telecom selected K2 evidence | Remaining semantic work |
|---|---|---|
| Target actor/kind | t0 assistant/call | Whether that call is governed by the norm. |
| Receipt pairing | h5/h6, h9/h10, h33/h34 | Whether a receipt is authoritative/current for the regulated role. |
| Clock | q7 `2025-02-25T12:08:00-05:00` | Applicability of the policy date convention. |
| Raw identity | h6.customer_id = t0.customer_id; h10.line_id = t0.line_id | Cross-source semantic aliases and ownership binding. |
| Raw date order | h10.contract_end_date `2025-01-31` precedes clock | Select this date, rather than DOB or other earlier dates, as the prohibition condition. |
| Other earlier dates | DOB, last plan change, last SIM replacement, bill dates | Being earlier alone is not a violation. |

The K2 selection is generic raw target-operand overlap plus necessary clock/metadata, not a business rule for a particular tool or row. All original source evidence still remains in the packet. K1 includes more mechanical facts; K2 focuses those facts. On the bank case there are no native typed tool receipts at all. K1 provides an empty receipt-pairing record and unresolved system time; K2 drops the empty pairing record. Thus this negative cannot test whether selecting a correct line receipt helps authentication: no such receipt exists in the current move.

## Observed outcomes

| Case | Reused I4/K0 | K1 all facts | K2 selected facts | Causal interpretation |
|---|---|---|---|---|
| Telecom positive | ERROR admitted | ERROR admitted | ERROR admitted | All recognize expired contract despite payment. The baseline was already right; no binary repair. |
| Bank negative | raw NO_ERROR, actor admission failure | NO_ERROR admitted | raw UNKNOWN, actor admission failure | K1 repairs admission once by preserving assistant KB actors. K2 adds unsupported upfront-verification uncertainty and repeats false system KB actors. |

Bank K1's correct admitted negative is useful operationally, but its raw label did not improve over I4. Its reason still generalizes business-only q1 to business/personal or personal procedures. This is not evidence that K1 closed semantic grounding or improved valid46 F1. The before/after is an actor-admission repair on one known negative.

Bank K2's UNKNOWN invokes uncertainty about whether requesting the listed verification data upfront is permitted. Both account-opening documents start with verification; q0 supplies the two-of-four fields; t0 says subsequent eligibility checking follows verification. Missing later account eligibility data does not leave this current information request without a known action stage. Its uncertainty should be counted separately from technical admission failure, and UNKNOWN-to-0 is only an explicitly declared binary projection, not proved compliance.

Telecom K1 preserves the decisive ban but introduces a requirement to verify restoration **before** resuming, whereas q17's restoration check follows permissible suspension lifting. K2 retains the correct narrow expiry relation without that auxiliary temporal error. This is component quality on an already-correct case; it is not a measurable binary gain.

## Independent proof ceiling

`outputs/hybrid_mechanisms_v1/oracle_supported_proof.json` deliberately supplies an independent source audit of policy scope, target binding, native state convention and exception closure. Under that qualification the generic proof adapter returns ERROR from FORBID/YES/TRUE/FALSE plus admissible original sources. Without qualification, or with a model's self-declared qualification dictionary, it returns UNKNOWN. This zero-HTTP oracle test establishes a conditional executable ceiling for a correctly grounded relation. It does not establish automatic semantic grounding, a blanket latest-receipt rule or measured F1 improvement.

The default boundary remains: code supplies reliable literal facts; the semantic reviewer decides their applicability against original evidence; unresolved semantic closure stays visible. Expanded fact inventories can distract or induce uncertainty, so more code facts cannot be assumed to improve the final judgement.
