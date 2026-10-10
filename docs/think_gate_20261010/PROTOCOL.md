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

## Result
Time: Qwen THINK A 1411 s, B 1427 s (64 requests × 3 samples each; 13 / 9 of 192 samples hit 12288 tokens);
Gemma startup 120 s, 64 requests × 3 in **108 s** (mean 116 tokens/sample, 0 truncated). 0 request errors.

| rule | pools TP/26 | pools FP/132 | prec | valid46 mean (base .800) | new FP/pass | verdict |
|---|---|---|---|---|---|---|
| Qwen A ≥2/3 [prereg] | 16 | 1 | .94 | .834 | 2,3,2 | reject (FP) |
| Qwen B ≥2/3 [prereg] | 15 | 1 | .94 | .827 | 2,3,3 | reject |
| Qwen A AND Gemma [prereg, amendment 1] | 5 | 0 | 1.00 | .820 | 0,0,0 | reject (valid gain) |
| Gemma ≥2/3 [diag] | 7 | 0 | 1.00 | **.848** | 0,0,0 | passes all criteria — diagnostic, not prereg |
| Gemma ≥1/3 [diag] | 7 | 0 | 1.00 | .875 | 0,0,0 | passes — diagnostic |
| Qwen A OR Gemma [diag] | 18 | 1 | .95 | .859 | 2,3,2 | reject |

Narrow context (B) ≈ A: not the cause. Qwen's valid46 FPs are stable (banking_081, banking_063, airline_10 t19);
Gemma never fires on them. Qwen and Gemma find mostly different positives (OR: 18 pool TP), so AND is too strict.
Gemma's valid46 gain comes from 2 rows (banking_005 t6: 3/3,3/3,2/3; retail_48 t4: 2,1,3), both missed by Qwen.
**Status:** "Qwen-score gate (p ≥ .005) → Gemma ≥2/3" is the best candidate so far, cheap (~4 min incl. model load),
but it was a diagnostic rule and its valid46 gain rests on 2 rows → needs a preregistered confirmation run
(fixed rule, fresh samples; ideally unseen data) before production.

## Amendment 2 (before generation): confirmation + Gemma as the lead model
Gemma server as round 1. Jobs (`experiments/think_gate_20261010/gemma2.py`), evaluator `evaluate2.py`:
- **C (primary, confirmation):** fresh samples of exactly the round-1 rule — Qwen score p ≥ .005 → Gemma ≥2/3.
  Same acceptance criteria. If C fails, the round-1 Gemma result is treated as a lucky draw.
- **L1:** Gemma ≥2/3 on every base-0 row (no Qwen gate).
- **L2:** Gemma's own 1-token score as the gate: t chosen on decision pools only (max pool TP with pool FP ≤ 3,
  ties → higher t), then Gemma ≥2/3.
- **L3 (diagnostic):** Gemma ≥2/3 alone instead of the base, valid46 F1 per pass vs .800.
  Replacing the full B2 pipeline model by Gemma is a separate, larger step, considered only if L3 is close to base.

## Result of amendment 2
Gemma: startup 80 s; gconf 64×3 in 110 s; gscore 298 in 209 s; gall 298×3 in 336 s; 0 errors, 298/298 scores parsed.

| rule | pools TP/26 | pools FP/132 | prec | valid46 mean | new FP/pass | verdict |
|---|---|---|---|---|---|---|
| **C: Qwen gate p≥.005 → Gemma ≥2/3 (fresh samples) [prereg]** | 6 | 2 | .75 | **.839** | 0,0,0 | **ACCEPT** (round 1: 7/0, .848) |
| L1: Gemma ≥2/3 on all base-0 rows, no gate | 5 | 12 | .29 | .854 | 0,0,0 | reject (pool FP) |
| L2: Gemma own score gate | — | — | — | — | — | no t with pool FP ≤ 3 → reject |
| L3: Gemma alone instead of the base | — | — | — | .545 (.56/.61/.47; FP 0, FN 13–16) | — | far below .800 |

Reading: the Qwen score gate is essential (removes ~10 Gemma pool FPs); Gemma alone is precise but very lenient.
Gemma-as-lead-judge is rejected; the cascade (Qwen base + Qwen gate + Gemma verdict) is confirmed on fresh samples
(same rows; still needs unseen data). Full B2 with Gemma as the pipeline model: separate run (gemma_b2_20261010).

## Amendment 3 (before generation): 40 GB archive limit
Archive today ≈ Qwen 29 GB + runtime 5.4 GB + code → ~5.5 GB free; Gemma 27B (28 GB) does not fit.
Same gated rows (Qwen score p ≥ .005), rule ≥2/3, same criteria; **two independent replicates per arm, ACCEPT only
if both pass** (round 1/2 showed sample variance).
- **Q-CoT:** Qwen itself, enable_thinking=False, short reasoning + VERDICT line, n=3, max_tokens 4096,
  T .7 / top_p .8 / top_k 20 (Qwen non-thinking recommendation). 0 extra GB.
- **G4B:** Gemma 3 4B-it FP8 (RedHatAI/gemma-3-4b-it-FP8-dynamic, 5.4 GB), request identical to the Gemma-27B arm.
