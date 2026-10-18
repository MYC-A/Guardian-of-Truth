# Freeze class-balance repair before any optimization, 2026-10-18

The first deterministic freeze failed before writing a frozen dataset:1672 rows,
672 positives(40.1914%), exceeding the unchanged40% upper bound. Source caps
and hard-negative checks passed. Preserve the failure, original executed code,
empty output directory and logs. Pilot completed10 actual longest inputs with
zero optimizer updates. No training or evaluation result has been opened.

Keep the existing component/entity split, source caps, stable pair ordering and
token budget. Correct only the selected TRAIN class mixture before freezing:
while positives exceed40%, remove an entire selected pair with positive fraction
above the current mixture. Prefer highest pair-positive fraction, then existing
stable pair hash; require the remaining source40% and hard-negative30% checks
to hold after each removal. If no feasible removal exists, fail. Never add rows,
alter labels, split twins, weaken a gate or use model/evaluation scores. Record
every removed pair, its rows/source/positive count, original selection counts,
final counts and executed-source SHA256. Final positive30-40% check stays binding.

Write the corrected freeze to NEW hours-frozen-v2. Retain failed hours-frozen-v1
and FREEZE.log; use a distinct phase log for the corrected freeze. Reuse completed
pilot only after checking its candidate and trainer-script hashes. L1 still starts
fresh in hours-l1-v1, which must not exist before launch. All controller stages
retain the original deadline2026-10-19T02:18:43Z. No production/ZIP changes.

Original human/long/volume acceptance gates remain failed; EXPLORATORY_ONLY.
