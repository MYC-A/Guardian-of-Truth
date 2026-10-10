# B2 pipeline with Gemma 3 27B FP8 instead of Qwen (one pass, valid46, token budget)

Adapter: `scripts/gemma_vllm_adapter.py` (copy of the Qwen adapter; only model identity, quantization check and
`--limit-mm-per-prompt {"image":0}` changed). Run 782 s, rc 0, 46/46 rows.

| | TP | FP | FN | F1 |
|---|---|---|---|---|
| Gemma B2 + token budget | 5 | 1 | 18 | .345 |
| Gemma B2 + token budget + UNKNOWN_TOOL lint | 8 | 1 | 15 | .500 |
| Qwen B2 + token budget + lint (tb1) | 16 | 1 | 7 | .800 |

**Not a fair quality comparison:** 36/46 rows have `INVALID_JSON` technical gaps (26 in the pre-pass, 10 in the
primary review) — the pipeline's prompts/output contract are tuned for Qwen, and Gemma's replies do not parse,
so most rows fall back to 0. Making B2 Gemma-compatible is engineering work (output contract / parsing), not a
model swap. Not pursued now.
