# V17: limited native rationale experiment after V15 data gate failure

V13 found 12 direct-binary false accusations among 1112 native TRAIN rows, only
in airline cancellation and compensation. The bounded family/template selection
contains eight. V15's original minimum of 16 is NOT passed. Preserve that result
and do not claim V15 success or that these errors explain external failures.

The user explicitly requested starting final training within one to two hours.
This separate limited experiment tests whether native rationale supervision
with an explicitly weighted verdict transfers better than V7 abstract examples.
It does not establish enough native error diversity for the original V15 gate.
No external evaluation rows, losses or error categories select training samples.

Freeze before optimization: apply original family/template-capped TRAIN
selection; stable-prioritize its pairs with positive correct-twin mining scores,
then retain its original round-robin order. Exactly 32 complete native pairs,
at least eight observed TRAIN false accusations and two source domains. Add
the fixed 16 TRAIN-only role rows and 32 balanced original BCE replay rows:
112 rows / 14 optimizer updates / one epoch. No replacement of failed source,
quote, isolation, tokenizer, loss, gradient or memory checks. No filler.

Everything else remains V15: original V5 warm start on pinned 35B, last16
layers, rank16/alpha32/dropout.05, LR2e-5, batch8, equal row weight, joint
.5 rationale CE + .5 verdict BCE, final checkpoint only. No test-driven retry.
The data manifest explicitly records original_v15_sixteen_error_gate_passed.

Keep the SAME absolute deadline from ALLOCATION_V4.json (two hours from the
earlier launch); do not restart the time budget. Training maximum5400 seconds,
evaluation reserve900 seconds. Preserve partial checkpoints, never report them
as a completed epoch. Evaluation compares fixed V12 control, base verifier and
previous V7 against the complete final V17 checkpoint. V16 regression receives
only time remaining within that same absolute deadline.

Human review unavailable. Exploratory only; no production/ZIP promotion or
guaranteed private improvement. All native examples repeat known tasks under a
new objective except the 16 constructed role cases; this is not new task data.
