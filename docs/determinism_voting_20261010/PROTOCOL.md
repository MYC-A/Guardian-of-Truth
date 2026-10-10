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
