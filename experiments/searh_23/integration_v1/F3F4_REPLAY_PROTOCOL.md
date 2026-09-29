# W1 scope guard regression on existing F3/F4

Frozen before the guarded graph replay. Branch `codex/integration-eval-20260929`.
Code under test: `w1_pipe3.py` and `scope.py` at `6775305e`; no changes to
model prompts, frontend files, graph scoring, or existing v10 outputs.

Inputs:

| Suite | Cases | SHA256 of frozen JSON |
|---|---:|---|
| F3 | 5 | `9937692879423293ae94791e5b0ae47b64a5bbdb791cf66eebf13d40637edb5c` |
| F4 | 5 | `57a08403f07abd5c7bf0569fe995e2675a3b34e8444e86dc14e6ef3eea42a8d1` |

Run only guarded `LLM_SG` with `W1_SCOPE_GUARD=1` and a fresh output root
separate from v10, one `LF_SUITE` at a time. Use the server configured Mistral
model and the same local reranker/frontend intermediates. Score every case
with the existing strict `w1_score.score_case`, comparing casewise with the
saved original v10 `W1_DOWN10_LLM_SG`. Record correct/extra/missing, typed,
exact graphs and every changed edge. Retain raw graph outputs and model
caches outside the volatile Vast instance.

These suites and their labels are already visible in this repository; this is
a regression test, not a new independent holdout. Do not alter the guard after
reading results and call the same suite a fresh confirmation.
