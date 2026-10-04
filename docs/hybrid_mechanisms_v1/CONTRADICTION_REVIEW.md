# Contradiction metadata and previous-judge opinion

C0 reuses the exact frozen I4 reply. C1 adds factual metadata about source references made by an old judge without supplying its verdict. C2 supplies the full old judge opinion and labels it a model hypothesis. The base original packet is preserved. Machine-readable independent audit: `outputs/hybrid_mechanisms_v1/augmented_causal_logic.json`.

## What the metadata proves

Telecom C1 reports h27 as a historical assistant make_payment attempt, h30 as a historical USER make_payment call, and t0 as the current assistant call. Bank C1 reports h3 as a historical assistant KB search. Original actors and current/historical positions are code-verifiable. A historical source citation can legitimately establish a prerequisite, and an old reference list does not state which actor/action its accusation binds. Consequently `POTENTIAL_ACTION_SCOPE_OR_ACTOR_CONFLICT_ONLY` is appropriate: this metadata is not a proved semantic contradiction and does not authorize changing a verdict.

## Observed replies

| Case | C0 reused I4 | C1 metadata, no verdict | C2 old opinion | Source-based finding |
|---|---|---|---|---|
| Telecom | ERROR admitted | ERROR admitted | ERROR admitted with old ERROR opinion | Current reply replaces a wrong historical payment cause with the correct expiry cause; no new binary gain. |
| Bank | raw NO_ERROR, actor failure | raw UNKNOWN, actor failure | raw NO_ERROR, actor failure | C1 adds avoidable uncertainty; C2 agrees with a correct old negative but cannot identify whether that agreement was anchoring. |

Telecom C1 reasons from h10 expiry, h34 payment and q7 prohibition. It does not substitute the historical failed assistant payment or successful USER payment as the current violation. The actual old C2 telecom opinion is ERROR, but wrongly charges historical make_payment actions and says current line resumption was correct. New C2 also emits ERROR while replacing that historical-payment cause with the correct current expiry cause. This is one observed cause replacement under a same-label anchor; it does not establish binary-label resistance or general robustness. There are no repeated trials.

Bank C1's reason categorically says the request is permitted and violates no prohibition, while the field is UNKNOWN and the gap ledger asks whether the account is personal/business or whether verification data may be requested. The current request is common to both opening procedures and q0 explicitly supplies the requested verification fields. This is a negative explanation paired with an uncertainty label and a residual gap ledger; it is not the historical pure ERROR/NO_ERROR reversal. Its KB evidence also labels assistant sources q1/q2 as system, so it fails actor admission independently.

Bank C2's raw NO_ERROR has the correct request-versus-completed-verification reason and agrees with the old NO_ERROR opinion. Agreement with a correct anchor cannot distinguish source reasoning from anchoring. q1 is again generalized beyond its business-only scope and q1/q2 have false system actors, so the reply remains technically inadmissible. Showing an old judge opinion did not repair that failure.

## Implication for a checker

Validate literal source metadata and show potential conflicts as review cues, with explicit current-move binding. Do not treat every historical citation as an accusation or force a violation merely because its actor differs from the current assistant. Keep old verdicts out of an independent default review unless conducting an explicitly declared anchoring experiment. These two cases do not establish a universal benefit from contradiction cues or a general correction rate.
