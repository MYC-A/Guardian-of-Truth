# Native Goal/Plan v2 — completed frozen experiment

Current authoritative status: COMPLETE, NOT_PROMOTED. Session 99992 terminated
successfully. All 22 cases (11 distinct semantic inputs) are predicted and sealed;
`goal_plan_v2_results.json` and its full failure audit exist. Goal-layer status is
22/22 UNRESOLVED, zero definitive verdicts and null certificate validation rates.
Transport=190/190; schema=176/190; tokens=361883; cost NOT_AUDITED.
Latency p50=14123.487 ms, p95=39617.261 ms.

The supplementary receipt audit finds 19 raw null declared-goal proposals and
ZERO parser-changed declared-goal values. Fourteen schema-invalid requests affect
twelve cases; eleven are extra-constraint tasks. No fresh activation was invented.
Diagnostic binary on 20 annotated cases: TP=0, FP=0, FN=18, TN=2, F1=0,
identical to fixed X0; fallback zero is not proof of safety.

All 113 frozen sources, v2 inputs, prompts and results remain unchanged. T2 v1
subsequently completed 18/18 cases. The frozen Policy stage is next. Goal v3 is
a separate hypothesis described in GOAL_PLAN_V3_DESIGN.md, implemented after
the planned Policy stage and its audit. Full Core/blind evaluation remains pending.

## Historical running checkpoints (superseded by completion above)

Implementation: `a9150076a445d7cf86eac70500aa259f058a9209`.
Freeze: `outputs/vnext/goal_plan_v2_freeze.json`.
Runner: `scripts/evaluate_vnext_goal_native_v2.py`.

At this checkpoint one of 22 controlled cases is complete (`gp:in_scope:0`).
All nine native frontend requests succeeded and passed schema validation.
Four readings are retained, including unknown goal-source/actor/action/drift
fields. The frontend correctly exposes those unresolved candidates; operational
binding generation therefore remains blocked, and the Goal-layer verdict is
UNRESOLVED. This is not evidence of semantic correctness or downstream gain.

The process remains active and is continuing sequentially. Do not launch a
second runner or resume while it is alive. The currently tracked execution
session is 99992. Subsequent cases may be inspected through safe telemetry.
Final scoring/audit happens only after all predictions have been sealed.
No original benchmark activation contract was invented; no blind labels opened.

Full project units: 968 passed. Protocol, regression inputs, trusted T1 sources,
100 frozen Claim v1 source hashes and native Goal v2 sources verified unchanged.
Production, Cycle1 and Cycle2 heads are unchanged. Checkpoint v9 corrects only
v8's T1 report filename reference, preserving both unit snapshots.

Latest execution checkpoint: the same process (session 99992) is confirmed live
with 14 of 22 cases complete, through `gp:reordered_step:1`. Completed case and
request/result receipts are committed independently of the final prediction seal.
No final v2 report exists yet; no final semantic metrics are inferred. The exact
113 frozen source files have been archived before further development. Source
hashes remain unchanged. A later unit/integrity checkpoint records 1059 passed
under `python -m pytest -q`, zero integrity errors and unchanged protected heads.
Checkpoint v10's narrower `pytest tests -q` receipt (1053) is preserved and its
scope clarified by v11; neither is a model-stage result.

The 104-case observed-dev Policy program comparison is independently frozen,
NOT_RUN. Its native requests and exact P1 semantic baseline share one throttle;
no parallel API batch has been started. T2 remains frozen and NOT_RUN, next only
after this Goal process terminates and its full report/failure audit is complete.

Next: finish and audit this v2 report before any v3 prompt/source repair;
then complete policy/T2/binding model stages, general Core integration,
development regressions/ablations and the separately frozen blind evaluation.
The whole vNext goal remains incomplete; nothing is promoted.
