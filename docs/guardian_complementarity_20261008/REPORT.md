# Complementarity study: result (2026-10-08)

One auditor, self-review, labels unchanged. Protocol and four amendments were committed before the held-out results
(8ca78858 → b7cc07c7). Local only: A100, Qwen3.8-27B Q8_0 llama.cpp, Granite Guardian 3.3-8B transformers. No paid API.

## Main result
**H1 is rejected.** `Qwen B2 OR Granite` doesn't improve the strongest local reviewer on data where the combination wasn't chosen.

| Pool | Qwen B2 | Granite | Qwen∨Granite | Qwen∧Granite |
|---|---|---|---|---|
| valid46 (where the idea came from) | 13/1/10 .703 | 16/2/7 .781 | **20/2/3 .889** | 9/1/14 .545 |
| **primary**: ext_tau2+tau2h+holdout2 (191 labelled) | **117/7/24 .883** | 79/21/62 .656 | 129/26/12 .872 | 67/2/74 .638 |
| secondary: lb2_long+lb3_long (103) | **50/2/1 .971** | 33/17/18 .653 | 50/17/1 .855 | 33/2/18 .767 |

(TP/FP/FN F1.) Primary ΔF1 for OR: bootstrap 95% CI [−.048, +.026]. +12 TP and +19 FP, so ΔTP ≥ 2·ΔFP fails.
OR helps only on ext_tau2 (.835→.895). It hurts on tau2h (.895→.843), holdout2 (.918→.870), lb2 (.978→.830) and lb3 (.966→.862).
lb_long was stopped at 39/57 per the stopping rule and isn't scored.

**Why the valid46 gain was illusory.** Granite was picked as a "complement" based on valid46 results. On valid46 Granite alone gets 2 FP;
on the other sets it gets 5–9 FP per set. With a 12k-character budget it sees only head+tail of the history (4,800 characters out of ~46k), which is a coarse
groundedness signal. The +7 TP on valid46 is a property of that particular development set (selection), not something that transfers.

**The more important finding.** Qwen3.8-27B B2 alone is strong on held-out data: primary .883 at 7 FP/191, lb2 .978, lb3 .966.
That's above local Ministral B2 everywhere it was run (ext_tau2 .835 vs .778, lb2 .978 vs .933, lb3 .966 vs .897).
The low valid46 score (.703) is mostly a property of valid46 (the longest, real rows). Recall there is the bottleneck, not precision.

## H2: delivering the blind analysis (wire cap 60 KB → 80 KB)
On valid46, 14/46 rows didn't get the blind analysis only because of the self-imposed byte cap. A 60 KB request is about 8.5k tokens, far below the 32k slot.
At 80 KB, 13/14 rows were delivered: +1 TP (banking_task083, correct cause: an undeclared discoverable tool was called directly) and +1 FP
(airline__10::t19, an absence claim judged as an unsupported fact). Net zero; the success criterion is **not met**. The cap is still worth raising as a technical
defect (it doesn't cost quality), but it isn't the source of the valid46 FNs.

## Other findings
- Old (c1d8d785) and current code build **byte-identical** review requests on valid46. So the local-vLLM vs API Ministral
  gap (FP 9 vs 3) comes from serving/weights, not from the contract fixes.
- Local llama.cpp decoding at temperature 0 under parallel slots is **non-deterministic**: none of the 14 fresh pre-passes matched the baseline text.
  Single-run differences of ±1–2 rows on 46 are noise.
- The committed first-circle caches have no response bodies, so they can't be replayed. Any rerun is a new sample.
- All 75 saved valid46 systems (`valid46_matrix_scores.txt`): the old claims/DF/witness/pool arms of universal_repair are identical to R_fix on valid46.
  Integrated relations/graph lower F1 (.389–.714). No old component beats R_fix on valid46 except v6fix layers (.78–.84, tuned on this same set).

## Recommendation
- Keep Qwen3.8-27B B2 as the main local reviewer. Don't add Granite through OR/AND.
- Raise the wire cap to the real slot size (with token-based accounting rather than bytes) as a technical fix, not as a quality gain.
- The remaining weakness is recall on long real dialogues (valid46: all 10 FN have no candidate at all). The next sensible step is
  generating candidates for material claims in tool-call arguments, with an equal-cost control (see method_synthesis §6, item 2),
  checked on held-out data at once, not on valid46.

## Artefacts
`outputs/guardian_complementarity/combine_primary.json`, `combine_secondary.json` (row classes, flips, CIs), `valid46_matrix*`,
`requests_*.json` (request equality), aborted_* (archived interrupted attempts); Granite records: `outputs/research_granite_guardian/compl_*`;
Qwen runs: `outputs/guardian_local_a100/llamacpp/qwen3.8-27b@…/runs/{ext_tau2,hold_tau2h,hold_holdout2,lb*_long,valid46/B2x_rep1.jsonl}`.
