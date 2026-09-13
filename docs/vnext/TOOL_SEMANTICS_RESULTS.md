# Tool semantics — first partial frozen result

Status: T1_COMPLETE_T2_COMPLETE. Role: controlled development extension, NOT blind
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

## T2 v1 — separately completed candidate experiment

Source: `outputs/vnext/tool_t2_v1_results.json`; implementation
`1a5bdba9606adf0d7e4cbbea4efeb26164525e20`. All 18 predictions were sealed before
reference scoring. Inputs include independently documented fixture semantics and
declared prior state; this is not real-provider contract validation.

Transport=18/18, schema=18/18. Known-true candidate recall=1/4 (25%); restricted
positive reference precision=1/8 (12.5%). Full candidate precision is NOT_ESTABLISHED:
unknown reference states remain unadjudicated, not false. Three grounding
rejections are retained in the raw/accepted audit. Aggregate statuses:
AMBIGUOUS_EFFECT=9, UNKNOWN_EFFECT=9; neither status is a trusted fact.

Unsafe trusted candidates=0/19; ledger pollution=0 cases; false state/completion/
causal support=0 in actual primitive probes with no T1 authority. This proves the
tested trust boundary, not downstream usefulness or guaranteed arbitrary-tool
behavior. Candidate recall is weak and does not justify promotion.

Latency p50=11983.532 ms, p95=14819.903 ms; tokens=22052; cost NOT_AUDITED.
Full per-case taxonomy: `tool_t2_v1_failure_audit.json`. Downstream value and
unseen real-world tool coverage remain NOT_ESTABLISHED.
