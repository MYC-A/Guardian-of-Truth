# CAUSE_AND_GOLD_AUDIT — contract 5b (source-seeing cause judge)

Judge: `src/guardian_truth/repair/cause.py`, model `ministral-14b-2512` (**same family as the detector → not independent**;
Gemma/Ollama BLOCKED by HTTP 429 monthly limit; no second judge available). The judge sees the same budgeted source packet as the
detector, the accusation, and the frozen gold cause(s). Every positive prediction of V4r, R_fix and R_comb on all 13 set/reps was
judged once (dedup by set,id,accusation text): 377 judgements, 10 `technical_unjudged` (invalid category in a reply whose visible
fields all say `accusation_supported: no` → counted as not-correct in the lower bound, excluded in the upper bound).
Raw: `outputs/universal_repair/cause/judgements_a{0,1}.jsonl`, joined table `cause/cause_report.{json,md}`.

## Correct causes among label-TPs
| set (reps) | V4r TP → correct cause | R_fix | R_comb |
|---|---|---|---|
| LB1 | 22 → 22 | 22 → 22 | 23 → 23 |
| LB2 | 20 → 19 | 21 → 20 (G3e correct) | 21 → 20 |
| LB3 (2) | 52 → 49 | 52 → 49 | 52 → 49 |
| ext v2 (3) | 111 → 31 (+6 alt.) | 111 → 31 | 111 → 31 |
| holdout (3) | 85 → 32 | 85 → 32 | 85 → 32 |
| valid46 (3) | 44 → 1 correct, 16 alternative-supported (gold has no cause text) | same | 45 → 1 / 16 |
| **all 13** | **334 → 154 correct core**, 22 alternative/conflict, 148 unsupported, 10 unjudged | 335 → 155 | 337 → 156 |

Reading: on the lockboxes ~95 % of TPs have the correct cause; on tau2 (ext, holdout) only **28–38 %** do — most tau2 TPs are the
right row for a wrong or unsupported reason (typically a "missing confirmation" accusation where h-sources show the confirmation, or a
generic policy accusation instead of the gold one-call / wrong-argument cause). Repairs change correct causes by +1 (G3e, R_fix) and
+2 (R_comb). R_comb's −1 label-TP on ext#1 (`ext_ret_019`) was an *unsupported* accusation (the audit already showed h30/h31 contain the
details and the explicit Yes); its +1 label-TP on ext#2 is again unsupported → R_comb does not improve cause quality on tau2.

Preserved findings — all judged `supported_correct_core` under V4r/R_fix/R_comb where detected: H5e, CL3e, BK3e (both reps), TL3e,
and G3e (R_fix/R_comb only).

## Judge variance (separate from detection variance)
Re-judgement of 60 judgements (V4r, ext#1 + holdout#1, attempt 1, temperature 0): same category 52/60, same correct/not-correct
57/60 → the correct-cause counts above carry about ±5 % judge noise.

## Gold audit (no gold was changed)
* FPs the judge called "supported" (15 judgements, 11 rows): on reading the rationales, 8 are judge errors of the same kind as the
  detector's (they demand the confirmation be "in the tool call payload" or contradict their own rationale, e.g. lb3L_039, lb3L_034,
  hold_ret_041). Candidates for human adjudication only: `banking_knowledge__task_033::t2` (user asked for a human agent; policy
  says transfer), `hold_air_013` (compensation offered without the policy's precondition). These stay label 0.
* Known issues kept from the audit: `ext_ret_041` gold S contradicts visible orders/addresses; `ext_tel_004`/`ext_tel_047`: one-call
  violation real, partial accusations do not refute it; `ext_air_061`: gold v2 cause list incomplete. Old ext v1/v2, valid46 and
  LB1/2/3 remain diagnostic/development sets.
* Holdout gold (new, `outputs/universal_repair/holdout/tau2h/`): oracle reward/action diffs + policy annotation by this agent, frozen
  and committed (1442c4d1) before any arm ran; 15 rows dropped with written reasons (13 oracle errors whose only basis is the
  hidden user instruction while the visible user explicitly confirmed the values; 1 pure permutation). Single annotator, no independent
  adjudication.
