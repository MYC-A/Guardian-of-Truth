# SuperZ Full-Cycle Research Plan — 2026-09-20

Agent: Super Z (identity postfix `superz`; worktree `agent-workspace/Guardian-superz-fullcycle`,
branch `research/independent-fullcycle-20260920-superz`, base `origin/research/offline-20260919` @ `1755838`).

## Starting facts (verified from repo docs and server artifacts)

| Arm (source) | TP | FP | FN | TN | F1 | Status |
|---|---|---|---|---|---|---|
| Offline `--backend none` (923bb445) | 12 | 0 | 11 | 23 | .686 | REPRODUCED, offline baseline |
| Direct Mistral ministral-14b (API) | 20 | 10 | 3 | 13 | .755 | PUBLIC_SEEN BASE |
| A0 Mistral structured judge | 22 | 16 | 1 | 7 | .721 | HIGH RECALL, FP-heavy |
| A1 suspicions + strict grounding | 0 | 0 | 23 | 23 | 0 | REJECTED: 114/120 offset mismatch, 6 OOB; pre-grounding 21/20/2/3 |
| Granite Guardian fc (23 rows) standalone | 8 | 0 | 15 | 23 | .516 | diagnostic; OR-baseline 13/0/10/23 .722 (+1 TP, 0 FP) |
| NLI whole-context | 0 | 0 | 2 | 21 | 0 | REJECTED pairing |
| FullArch N5 exact-binding | 0 | 0 | 23 | 23 | 0 | all UNRESOLVED (sound) |
| B0–B3 five-case pilot | 0 | 0 | 5 | 0 | 0 | no formal gain; NuExtract repair declined |
| Full-line C1 union→formal (synth32) | 7 | 0 | – | – | .609 | precision 1.00, recall .44; A0-mistral .889 dominates on synth32 |

Environment constraints (verified):
- Gateway jobs: timeout 1–14400 s; stdout logs capped 256 KB; Files API ≤512 KB/file, relative paths only.
- Jobs run as `guardianagent`; `/mnt/data/guardian/secrets/` (Mistral key) is root-only → **Mistral API unavailable to this agent**.
- Replacements: keyless OpenAI-compatible APIs reachable from the server: llm7.io (`default`→minimax-m2.7, ~10 RPM), pollinations.ai (openai-fast→gpt-oss-20b, ~1 req/15 s), blockrun.ai (nemotron-3-super-120b, limits unknown).
- Local GPU: NVIDIA A10 23 GB; Granite Guardian 3.3 8B (~16.7 GB VRAM), NuExtract3-W4A16, GLiNER2.5, NLI DeBERTa, BGE-M3 cached.
- `mistral-7b-instruct-v0.3-c170c708` is an incomplete download (per HANDOFF) — verify before any use.
- GitHub push: NO credentials available (token redacted; server has none) → publish via commits in server repo + `git bundle` artifacts + local mirror. Flagged for the user.

## Hypotheses

- **H1 (E3a, A1R post-hoc):** The A1 loss is a producer/validator contract defect, not missing model signal. Re-anchoring the 120 frozen suspicions with a robust-but-strict anchor (unique verbatim quote; document auto-repair; emphasis-tolerant normalization; model offsets ignored) should recover a large part of the 21 pre-grounding TP at a strictly lower FP count.
- **H2 (E2, A0 cross-model):** Independent judges (minimax-m2.7, gpt-oss-20b, nemotron-120b) on the same label-free input produce different FP profiles; at least one non-Mistral judge reaches F1 ≥ .70 on public46.
- **H3 (E4, A2/A3/A4):** Independent per-suspicion verification (second model, fragment-scoped context) removes a meaningful fraction of A-family FP while keeping most TP (net F1 gain over unverified).
- **H4 (E5, ensemble):** A 2-of-N agreement rule or a verified-OR combination beats every single judge on F1 and exposes correlated-error structure (which pairs of judges fail together).
- **H5 (E6, external):** Judge ranking on AgentHallu DEV (488, external) is not identical to public46 ranking — measures overfit risk of public46-tuned conclusions.
- **H6 (E7, offline):** An offline candidate (baseline + Granite OR-rule) reproduces the 13/0/10/23 result from local weights in my worktree and accepts fresh unseen input.
- **H7 (E8, B mutual repair):** With two full generative models (instead of NuExtract-as-critic), reciprocal critique + repair produces at least one real semantic repair on the frozen 5-case B3 set (where NuExtract produced zero).
- **H8 (E9, robustness):** The suspicion pipeline's labels are stable under entity/ID/number renaming on a small paired set (no public46-specific memorization).

## Experiments and artifacts

All outputs under `outputs/superz_fullcycle/<exp_id>/` in this branch; scripts under `experiments/superz_fullcycle/`.
Statuses follow IMPLEMENTED / SMOKE_TESTED / MODEL_TESTED / E2E_TESTED / BENCHMARKED / INDEPENDENTLY_VALIDATED / CONTEST_READY.

| ID | Experiment | Data | Output dir |
|---|---|---|---|
| E1 | Offline baseline reproduction | public46 | `e1_offline_baseline` |
| E2 | A0 direct judge × {J1 llm7, J2 pollinations, J3 blockrun} | public46 | `e2_a0_cross` |
| E3a | A1R post-hoc re-anchor of frozen Codex A1 | public46 | `e3a_a1r_posthoc` |
| E3b | A1R live suspicion generation (repaired schema) | public46 | `e3b_a1r_live` |
| E4 | A3 fragment-scoped + A4 cross-model suspicion verification | public46 | `e4_a34_verify` |
| E5 | Ensemble/agreement analysis + correlated errors | public46 | `e5_ensemble` |
| E6 | External validation on AgentHallu DEV | agenthallu DEV 488 | `e6_agenthallu` |
| E7 | Offline candidate (Granite OR-rule) local reproduction + fresh-input smoke | public46 + fresh rows | `e7_offline_candidate` |
| E8 | B: two-full-model mutual critique on frozen B3 five-case set | b3 smoke | `e8_b_mutual` |
| E9 | Counterfactual robustness (rename/ID/number perturbations) | paired subset | `e9_robustness` |

## Publishing protocol (no GitHub credentials)

1. Commit after each completed experiment in `research/independent-fullcycle-20260920-superz`.
2. `git bundle` per milestone into `agent-workspace/superz-bundles/` (persistent server location).
3. Compact artifacts mirrored to the agent's local `download/` for the user.
4. User action required to actually publish: provide a GitHub token with push rights to `MYC-A/Guardian-of-Truth`.
