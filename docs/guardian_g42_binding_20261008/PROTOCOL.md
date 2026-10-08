# Phase: Granite 4.2-30B + Qwen argument-binding audit (frozen before scoring)

Base: research/guardian-complementarity-20261008 @ 4172683b. Same worktree code (d38a18d0), same labels, same scorer (combine.py).

## Systems
- QB2: Qwen3.8-27B Q8_0, variant B2 (existing runs, unchanged).
- G42: ibm-granite/granite-4.2-30b, official GGUF Q4_K_M (INT4; no AWQ / "-instruct" repo exists), llama.cpp b11459,
  thinking off, same B2 variant/prompt/packet as Qwen. Arms: G42 alone, QB2 OR G42, QB2 AND G42.
- H3 binding audit: one extra Qwen call per row whose current_targets contain a tool call (experiments/guardian_binding/audit.py).
  Model claims MISMATCH with source ids + verbatim quotes; CODE verifies (used value in target, established value differs,
  both quotes verbatim in non-assistant non-target sources, established value inside its quote). Rule: final = QB2 OR VERIFIED_MISMATCH.
  No benchmark ids, tool names or domain rules.

## Data split
- Development (errors already inspected): valid46, ext_tau2, hold_tau2h, hold_holdout2.
- Clean test (only aggregates seen before): lb2_long, lb3_long, lb_long (lb_long completed by resume; Qwen B2 run).
- Primary metric: F1 on clean test pool; secondary: dev pool. Paired bootstrap 95% CI (10k, rows), delta vs QB2.

## Decision
- An arm is "accepted" only if clean-test F1 delta CI lower bound > -0.01 AND point delta > 0, and dev delta not negative.
- Otherwise reported as rejected/neutral; FP cost and changed rows (with causes) reported in all cases.
- Granite 4.2 runs on clean test only if time permits; if not run, listed NOT_EXECUTED (no extrapolation).
