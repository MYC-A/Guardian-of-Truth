# THINK cascade (score-gated, 3-sample vote) — protocol, written before generation

## Motivation (post-hoc, from the four-arms data — stated honestly)
In four arms, single-sample THINK found 15/26 decision-pool positives with 3 FP, but on valid46 its FPs were all
1-of-3-pass noise; almost all THINK hits sit at Qwen score P(YES) ≥ 0.005 (pools: think∧p≥.005 → 15 TP / 1 FP).
GATE = 0.005 and the 2-of-3 vote were chosen after seeing that data. This run tests them with **fresh samples**
(new sampling, larger token budget). The 2-of-3 vote has never been measured on the decision pools.

## Cascade (all domains, no gold, no per-domain rules)
1. Base: B2 + token budget + UNKNOWN_TOOL HARD (unchanged).
2. Qwen 1-token score p = P(YES)/(P(YES)+P(NO)) (stored from four arms; same prompts).
3. Gate: base = 0 and p ≥ 0.005.
4. THINK on gated rows: one request, n = 3 samples, max_tokens 12288, T 0.6 / top_p 0.95 / top_k 20, thinking on.
   Fire iff ≥ 2 of 3 samples end with `VERDICT: VIOLATION` (finish=length or no verdict = not a vote).
Arms: **A** full context (as four arms); **B** narrow context — instructions/policy/history verbatim, full tool
schemas only for tools whose name occurs in the history or the current turn, other tools listed by name only.
Diagnostics only (not candidates): ≥1-of-3 and 3-of-3.

Gated: 34 decision-pool rows (pass 0) + 30 valid46 row-passes (rows already positive in all three bases skipped —
their prediction cannot change). 128 requests × 3 samples. Server: max-num-seqs 48, max-model-len 40960.

## Acceptance (unchanged from four arms / prosecutor-judge)
- Decision pools: new FP ≤ 3 of 132, new TP ≥ 5 of 26, precision ≥ .70.
- valid46: mean F1 over 9 combinations (3 bases × 3 passes) ≥ .830 (base .800), no pass with > 1 new FP.
- Time: measured; production estimate must fit the 30-min limit with a deadline guard (THINK by descending p,
  stop before the deadline; unprocessed rows keep the base answer).
Because the gate and the vote were inspired by the same data, an ACCEPT here is still to be confirmed on unseen data.

## Amendment 1 (after arm A results, before arm B results and before any Gemma generation)
Arm A: pools 16/26 TP, 1 FP; valid46 mean .834 but new FP per pass [2,3,2] → **reject** (FP rule). The valid46 FPs are
consistent, not noise: banking_081 t35 and banking_063 t8 (both `transfer_to_human_agents`; Qwen argues the tool
description requires a knowledge-base search to pick the reason) and airline_10 t19.
Second family to veto consistent single-model errors: **Gemma 3 27B-it FP8** (RedHatAI/gemma-3-27b-it-FP8-dynamic,
file sizes verified against HF) on the same gated rows, same question, full context, explicit reasoning + final
VERDICT line, n=3, T 1.0 / top_p .95 / top_k 64, max_tokens 4096.
Primary rule (prereg): fire iff Qwen-A ≥2/3 AND Gemma ≥2/3. Diagnostics: Gemma alone, pooled ≥4/6, Qwen-A OR Gemma.
Same acceptance criteria. Note: the veto idea is motivated by the valid46 FPs seen above → confirm on unseen data.
