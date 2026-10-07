# Complementarity study: is Granite Guardian a missing component of the strongest local reviewer? (frozen before runs)

Date 2026-10-08. One auditor (self-review; no independent annotator). Labels are never changed.

## Why this hypothesis (offline evidence, 0 new calls)
`experiments/guardian_complementarity/matrix.py` builds a per-row matrix of all 75 saved valid46 systems.
- The strongest local reviewer Qwen3.8-27B B2 is a **high-precision / low-recall** detector (13/1/10; AM 9/0/14).
- Every one of its 10 FN is caught by several older API-Ministral systems. The positives no system catches reliably are
  banking_task003/task018 (task018 is gold-sensitive: see the synthesis report).
- Offline OR of Qwen B2 with **Granite Guardian 3.3** (a pre-existing frozen control from big_researh, not selected from this matrix):
  20/2/3, F1 .889 (+7 TP, +1 FP). The best post-hoc OR (MP:G4_S, .894) was chosen from 74 candidates, so it is not used as a hypothesis (selection bias).
- These numbers are on valid46, the long-used development set. **They are not evidence of generalisation.**

Side finding (diagnostic): the old (c1d8d785) and current (200b7304) code build **byte-identical** review requests on all 46 rows
(`capture.py`). So the local-vLLM vs API Ministral gap (FP 9 vs 3 with identical prompt and schema) comes from serving/weights, not from the contract fixes.

## H1 (only primary hypothesis)
On the held-out sets, never used to choose this combination (lb_long 57, lb2_long 47, lb3_long 56, ext_tau2 68 labelled, hold_tau2h 51,
hold_holdout2 72; pooled), `Qwen B2 OR Granite` has higher F1 than `Qwen B2`, with ΔTP ≥ 2·ΔFP.

## Arms (fixed)
- QB2: Qwen3.8-27B Q8_0 llama.cpp b11459, run_local `--variant B2`, unchanged code (worktree of d38a18d0), same flags and budgets as the first circle.
- QAM: the same model with `--variant AM`. Used for the equal-family second-opinion control.
- GR: Granite Guardian 3.3-8B, `experiments/offline_guardian/run_granite_guardian.py`, criteria=groundedness, max_context_chars 12000,
  max_new_tokens 16, backend transformers. That is exactly the big_researh control config; the binary is Yes = 1.
- Combinations (binary, offline): QB2∨GR (H1), QB2∨QAM (control: second opinion from the same family), QB2∧GR, GR alone; plus local Ministral B2∨GR where runs exist.

## Validity gates (before held-out)
1. Granite on valid46 must reproduce the saved per-row granite_flash in ≥44/46 rows. If not, H1 is NOT_EXECUTED, with the cause recorded.
2. A QB2 valid46 replay must be fully served from the existing cache (0 live sends), proving the identical wire. If not, record the reason.

## Metrics and reporting
TP/FP/FN/TN, P, R, F1 per set and pooled. Paired row flips. Bootstrap 95% CI of ΔF1 (rows resampled, 2000 draws, seed 0).
Technical failures are counted and never imputed as NO_ERROR; a row with a failure in one arm is reported separately.
Granite gives no cause, so OR-added TPs are binary only (cause NOT_ASSESSED). That is fine for the binary competition metric, not for explanation.
No tuning of thresholds, prompts or truncation after seeing held-out results.
