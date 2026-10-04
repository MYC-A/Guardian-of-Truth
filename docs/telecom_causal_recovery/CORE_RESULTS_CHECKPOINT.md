# RAW_INFERENCE and POST_HOC_CAUSAL_AUDIT checkpoint

Frozen inference source/protocol preparation commit `fd8efa9f`. No model prompt,
schema, packet selection or inference module changed after that freeze.
All five executed requests returned the pinned model `ministral-14b-2512`, HTTP
success, finish_reason stop, strict shape and source/actor admission.

| Job | Emitted decision | Explanation recovers requested cause/contrast | Complete original cause recovery | Known tokens |
|---|---|---|---|---:|
| A | NO_ERROR | Yes, explicitly identifies current expired-contract violation | No: label contradicts explanation | 7,178 |
| B | ERROR | Yes, same correct current cause | Yes, disclosed oracle retrieval | 8,325 |
| C | NO_ERROR | Yes, explicitly says current action is not permitted | No: label contradicts explanation | 8,621 |
| read control | NO_ERROR | No invented current resume | Not an official original row | 7,987 |
| future contract control | NO_ERROR | No expired-contract accusation | Not an official original row | 8,580 |
| payment control | No answer | Unmeasured | BUDGET_STOP | 0 |

Total **5 inference HTTP / 40,691 known=charged tokens**, zero unknown usage,
retry/fallback. Remaining limit: 19,309 tokens; payment reservation 20,876 does
not fit. That is a technical stop, not semantic UNKNOWN or a failed model answer.

Exact raw reply objects equal the saved reply objects. The original provider
strings for A/C already contain NO_ERROR; the decoder/admission copies the enum
unchanged. Every request uses the same ERROR/NO_ERROR/UNKNOWN enum and neutral
review prompt. Raw SHA256 matches the durable ledger. Byte-identical offline
replay reproduced all predictions with unchanged ledger and no network/credentials.
Thus the observed label/explanation conflict is present in the model output;
there is no demonstrated decision inversion or cache association error in code.
Whether decoding constraints, this provider/model, or the task framing caused
it cannot be isolated with one sample per arm.

Do not rewrite A/C decisions from their prose or report them as correct overall
verdicts. Semantic cause content and binary decision are separately audited. B
is a local independent correctly decided cause recovery. The arm contrast is not
a causal estimate of the benefit of mechanical facts: A already understood the
same cause, and no repeated/independent trials establish that B facts fixed the
decision. C supplies no demonstrated improvement and introduces another observed
inconsistent final field.

The current AUTO gate is pre-registered as a **cause-discovery** gate: admitted A
and human A_cause_correct; it does not require A's ERROR. Any subsequent narrow
AUTO diagnostic must explicitly retain A's binary failure and independently score
retrieval, meaning and final field. No overall A success can be inferred from
that gate. Complete mechanism conclusions still require all criteria, controls
and the missing payment contrast. This checkpoint precedes any AUTO answer.
