# V18: pre-update runtime reduction within the user's fixed deadline

V17 v2 passed source/token and longest9525-token gradient/memory checks. Its
first three rows required199 seconds. No optimizer update was committed.
That throughput endangers the two-hour limit including final evaluation.
Stop before the first update, preserve the zero-update failure and initial
weights, and reduce data by a fixed prefix of the existing TRAIN selection.
This is a runtime decision, with no evaluation result or label involved.

Use24 complete native SFT pairs (48 rows), all16 fixed role TRAIN rows, and8
complete disjoint native BCE replay pairs (16 rows). Total80 rows /10 optimizer
updates /one epoch. Keep original hard-first then round-robin order and all
eight bounded TRAIN false-accusation pairs; fail if the eight-error gate or two
native-domain condition does not hold. Replay selection is the first8 pairs
of the already specified original-preference then SHA order. No duplicates.
All original source, no-eval, quote, teacher-boundary and gradient checks remain.

Recipe identifier V18_NATIVE_COMPACT_RATIONALE_V1. Other model/loss/optimizer
settings unchanged from V17. Same absolute deadline19:11:35MSK; no extension or
reset. No smaller fallback if this fails. Archive partial runs honestly. Evaluate
only the complete final checkpoint using the fixed comparison. Original V15's
sixteen-error gate remains failed. This small, human-unreviewed objective test
is exploratory and does not establish private gains or acceptance.
