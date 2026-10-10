# Determinism mode and majority voting — protocol

Committed BEFORE the runs.

## Why
Identical requests give different outputs: between two valid46 runs 44/46 byte-identical pre-analysis
requests got different texts (median first divergence at char ~840), and borderline review decisions flip
(e.g. retail_48: "retry of a failed call = violation" vs "user asked to retry = fine"). Single runs cannot
measure effects of ±1–3 rows. Model: Qwen3.5-architecture hybrid (full + linear attention), FP8, vLLM 0.19.1.

## Test A — batch-invariant mode (`experiments/determinism_20261010/replay.py`)
Replay the 92 recorded wires (46 pre_blind + 46 review) of the B2 graph16 valid46 run twice on one server,
order forward then reversed, 16 concurrent, prefix caching on (production flags).
Modes: `normal` (control) and `invariant` (VLLM_BATCH_INVARIANT=1, --attention-backend FLASH_ATTN).
Report: identical outputs pass1 vs pass2 per tag, errors, startup, pass time.
Success: invariant gives 92/92 identical with no errors; usable if pass time ≤ 1.5× normal.
(The hybrid linear-attention and FP8 kernels may not be covered by the mode; that is what we test.)

## Test B — majority vote of 3 runs (same config)
Config: B2 + `--token-budget`, graph16 settings, valid46. Run 1 = existing (c1ae1aad, `valid46_tb`);
runs 2 and 3 identical commands. Label = majority of 3. Report: each run's F1, majority F1, rows that are
not unanimous, and time (3 passes would be needed inside the 30-min budget → measured, not assumed).
valid46 is contaminated and small: this is a feasibility and variance measurement, not an adoption decision.

## Result (2026-10-10)

### Test A — batch invariance
- normal: 92 replayed requests, 0 errors, startup 75 s, passes 391/347 s; identical outputs review 9/46, pre_blind 1/46.
- invariant (`VLLM_BATCH_INVARIANT=1`, FLASH_ATTN): **engine failed to start**. Batch-invariant mode routes FP8
  linear layers to the Triton `w8a8_block_scaled_mm` kernel, which needs native fp8e4nv (Hopper/Ada, SM89+);
  A100 (SM80) only supports `fp8e4b15/fp8e5` (FP8 runs there via Marlin weight-only, not batch-invariant).
  → Not achievable for the FP8 checkpoint on A100. A BF16 dequantised copy would be a different model
  (quality re-check, ~2× memory, slower kernels) — **not pursued**: determinism does not raise expected F1,
  and it only makes the noise reproducible, not smaller, for prompt-level A/B changes.

### Test B — three identical B2 + token-budget runs
| run | F1 | TP | FP | FN | wall |
|---|---|---|---|---|---|
| tb1 | .7368 | 14 | 1 | 9 | 691 s |
| tb2 | .7368 | 14 | 1 | 9 | 641 s |
| tb3 | .7368 | 14 | 1 | 9 | 654 s |
| majority 2/3 | .7368 | 14 | 1 | 9 | — |
| any-of-3 (diagnostic only) | .7805 | 16 | 2 | 7 | — |

- Identical F1 hides different rows: 6/46 rows are non-unanimous (airline_10, banking_018, banking_057,
  banking_083, retail_29, telecom mobile_data t6). ~40 rows are stable.
- Majority vote gives **no gain** here, and 3 sequential passes (~33 min) do not fit the 30 min limit.
- vs graph16 B2 single run (.8205): banking_005, retail_48, telecom mms t7 are TP in graph16 and FN in all 3
  token-budget runs, with identical pre_blind prompt token counts. Undecided between "graph16 was a lucky
  draw" and a systematic downstream effect → two repeats of plain B2 on the same code (base2, base3) queued.
