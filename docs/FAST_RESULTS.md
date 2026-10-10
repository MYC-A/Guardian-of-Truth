# Guardian speed study (ministral-14b-2512 via Mistral API, 2026-10-10)

Code: `experiments/guardian_fast/` (`run_fast.py`, `hook_fast.py`, `postverify.py`, `score_fast.py`). Same rows/gold as `guardian_local_a100`.

## Findings
1. **v6fix model layers (F/S/P) never changed a decision**: `binary == binary_rfix` in 1908/1908 saved rows (all local runs). They cost ~2 calls/row. N0 drops them.
2. **blind2 pre-pass was wasted on long rows**: on valid46 it was generated (≈1650 completion tokens, ~20 s) and then discarded in 17/46 rows because the review request exceeded the 60 000-byte wire cap (blind sources were sent twice). C1/C2 do not resend sources and skip the call before it is made if it cannot fit.
3. **Pre-pass gave no gain with this model** (F1; N0 = R_fix only, C1 = compact quote-grounded pre-pass ~250-550 tokens, B2 = old pre-pass):

| set (rows) | N0 | C1 | B2 |
|---|---|---|---|
| valid46 (46) | 0.70 (0.77 on an identical earlier run: API noise) | 0.65 | 0.62 |
| lb2_long (47) | 0.957 | 0.936 | 0.889 |
| ext_tau2 (68) | 0.831 | 0.787 | – |
| lb3_long (56) | 0.947 | 0.929 | – |

Cost per row (completion tokens / calls): N0 ≈ 920-1340 / 1.4-1.9; C1 ≈ 1460-1820 / 2.4-2.9; B2+layers ≈ 3100+ / 4.4 (valid46).
4. Tried and rejected: terse review (-40% tokens but lb2 FP 1→8, F1 .957→.808); verify-the-positives with the narrow verifier (removes FP but kills TP: lb2 .957→.909 lenient / .857 strict, valid46 .70→.55/.35); C2 (+entities/computed) worse than C1 on valid46.
5. Repair components (DF4/Ems/AT + verify) flipped 2 rows to correct and 0 to wrong on valid46; kept.

## Caveats
Single run per cell; identical N0 on valid46 varied .70-.77 (temperature 0 is not deterministic on the API), so differences <0.05 are noise. Local-vLLM wall-clock was not measured (compute server unreachable). Older local ministral-3-14b runs showed B2 > AM by +0.01..+0.12 on 4 of 5 sets; that gain does not reproduce with the API model.

## Round 2 (blocked): retrieval hint RF, from-scratch grounded reviewer S1/S1F
Code is in `experiments/guardian_fast/{retrieval,s1,score_s1}.py` and variant `RF` in `run_fast.py`. The Mistral API returned HTTP 402 (budget exhausted) mid-run, so **RF has no valid result** (failed calls look like NO_ERROR in a naive score; files kept as `*.partial_402.jsonl`) and S1/S1F finished only ~22 of 46/47 rows per set (not a random subset).
Partial S1 (rows that completed, valid46 / lb2): raw verdict flagged ERROR on ~21 of 22 rows in both sets (FP 10 of ~12 clean rows, F1 .71/.65); quote grounding keeps the FP (the quotes exist but do not prove a violation). Output is ~200 tokens/row, i.e. ~3.5x shorter than the R_fix review, but this version over-flags and is not a candidate. Rerun after budget top-up.
