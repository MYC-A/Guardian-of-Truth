# Cycle 2 post-freeze failure audit

No predictor, threshold, prompt, formula, or adapter was changed after viewing
external results. This document classifies the frozen failures; proposed fixes
belong only to the next cycle.

## Observed failures

| Arm | False positives | False negatives | Transport failures |
|---|---:|---:|---:|
| X0 | 0 | 85 | 0 |
| X1 | 0 | 83 | 98 |
| X4 | 0 | 85 | 0 |
| X5_CORE | 0 | 85 | 0 |
| X5_PROTECTED | 0 | 85 | 0 |
| G1 | 0 | 85 | 98 inherited from X1 telemetry |

The external sample is intentionally positive-heavy because it localizes drift
steps; therefore an all-zero verifier obtains 15 correct negatives but zero
useful recall. The deterministic arms fail across 19 error families, including
step reorder, output poisoning, persona assumption, sudo escalation, credential
read, filesystem/network exfiltration, and topic pivot. This is broad
open-vocabulary coverage failure, not one narrow regex miss.

## X5 attribution

Attribution is non-exclusive because one unresolved case can fail at several
upstream boundaries. Among the 85 X5 false negatives:

| Candidate component | Cases |
|---|---:|
| POLICY_MEANING | 85 |
| POLICY_COMPILATION | 85 |
| CLAIM_EXTRACTION | 84 |
| TOOL_EFFECT | 85 |
| BINARY_ADAPTER | 85 |

The external goal/plan language produces unknown policy segments and no
executable obligation in every positive. No external tool has a trusted T1
effect contract. Response-only C0 extraction also leaves unknown declarative
spans in 84 positives. The solver consequently remains unresolved, and the
declared binary adapter turns unresolved into zero. Binding and solver are not
claimed as sole root causes while these upstream inputs are absent.

X1's 83 semantic false negatives are operationally contaminated: they coincide
with missing responses, except for the two successfully detected positives.
It is therefore invalid to attribute them to holistic reasoning quality.

G1 carries X1 transport status in telemetry even where boolean short-circuiting
makes X1 unnecessary. Its semantic failure is instead the locked gate: X4=0 on
all cases, so `X4 AND X1` can never contribute. This observability distinction
is retained rather than corrected post hoc.

The complete per-case taxonomy, exact error families, statuses, and the fixed
component vocabulary are stored in `outputs/cycle2/failure_taxonomy.json`.
