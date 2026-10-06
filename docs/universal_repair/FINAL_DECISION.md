# FINAL_DECISION

## Pre-registered rule applied (PROTOCOL.md "Adoption rule")
| criterion | R_fix (A2) | R_comb (A2) |
|---|---|---|
| FP ≤ V4 on every set/rep (13) | ✓ (identical FP everywhere) | ✗ LB3#1 8 > 7 (lb3L_034) |
| TP ≥ V4 on frozen lockboxes | ✓ (LB2 +1) | ✓ |
| ext F1 ≥ V4 on ≥ 2/3 reps | ✓ 3/3 (equal) | ✓ 2/3 (#2 up, #3 equal, #1 down) |
| preserved findings kept (H5e, CL3e, BK3e Ems, TL3e) | ✓ (+ G3e recovered) | ✓ (+ G3e) |
| holdout: F1 ≥ V4, FP ≤ V4+1 (3 reps) | ✓ identical on all 3 reps | ✓ identical |

**Decision: R_fix (all deterministic fixes, flags `exec, evidence, df_scope, df_copy, df_entity, df_overflow`) is the
recommended default on the research branch. R_comb is not adopted**; `pool` and `witness` stay shadow/off.

## What this decision does and does not mean
* R_fix is adopted because it is *correctness-equivalent or better* on every measured set, not because it is measurably better:
  its only paired difference from V4 across 13 set/reps is G3e (+1 TP, correct cause). On the clean holdout it is identical to V4.
  Its value is that wrong arithmetic/time/evidence/entity/membership handling is now exact and receipted (21 unit tests).
* A1 and A2 were found on LB3 (development) — LB3 is no longer clean for R_fix. Only the holdout is clean (A1 holdout observed before A2).
* No end-to-end improvement is claimed: rep-to-rep variance (valid46 F1 0.649–0.791, holdout 0.750–0.811) is far larger than any
  arm effect.
* The dominant miss is upstream: 83/120 R_fix misses never reach a checker (NO_TRIGGER); on tau2 every missed semantic error is
  NO_TRIGGER and the NO_CANDIDATE misses are format-only rules. Cause quality on tau2 is low for every arm (28–38 % correct causes).
* `pool` adds candidates and +3 TP on dev but also +1 FP via a verifier error; `witness` removes some wrong-cause TPs (good for
  causes) but lowers the label metric. Both need a stronger verifier before adoption; they remain behind flags.

## Not executed / blocked
Gemma (Ollama Cloud 429 monthly limit → BLOCKED; AI Horde not used for a full rep), mistral-medium/small (0 req/min tier),
mistral-large (403), SSH host `new` (no key in sandbox → NOT_EXECUTED), independent code/logic review (no sub-agent tool → self-review
only), independent second annotator/judge for the holdout. Production merge is a separate reviewable step and was not done.

## Next steps (highest expected value first)
1. Upstream recall: structural checker for the policy-declared format rules (one tool call per turn, no text+call) through AT/policy
   binding, measured on a new holdout.
2. Verifier quality on confirmation semantics (the shared blind spot of detector and judge) before enabling `pool`/`witness`.
3. Independent (non-Mistral) cause judge and a second human annotator for the holdout.
