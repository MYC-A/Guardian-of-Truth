# Tool semantics — first partial frozen result

Status: T1_COMPLETE_T2_NOT_RUN. Role: controlled development extension, NOT blind
evidence or real-world contract coverage.

Source of truth: `outputs/vnext/tool_t1_results_v1.json`; predictions
`tool_t1_predictions_v1.json`; pre-prediction configuration/source hashes
`tool_t1_freeze_v1.json`. Implementation `8d2c532`, freeze checkpoint `af2e3ee`.
The 18-case benchmark and independent executable reference were frozen in `8e9c3fb`.

T1: 16 applicable cases, 16 exact matches; two cases lack any trusted contract and
are NOT_APPLICABLE_T1, not successful guesses. False no-effect proofs: 0.
False causal action confirmations: 0. No API requests; transport/schema model
reliability NOT_APPLICABLE to this offline stage.

Covered: conditional completion; no-op requiring prior state; partial success;
timeout/failed unknown effect; async accepted vs completed; incompatible versions
and schema hashes. A completed mutation may confirm a causal action; a no-op may
confirm state and no-effect but does NOT confirm that a new mutation occurred.

Predictions were persisted and hashed before development gold join. Per-case failure
classification is in the result JSON. No applicable T1 failures were observed.
No post-result changes to the evaluated T1 logic belong to this result version.

T2 model stage: NOT_RUN. T2 grounding/promotion rejection has unit tests, but effect
recall/precision, UNKNOWN behavior and semantic gains are NOT_ESTABLISHED.
Downstream value, unseen real-world tools and full tool-stage admission are also
NOT_ESTABLISHED. These small fixture results do not justify production promotion.
