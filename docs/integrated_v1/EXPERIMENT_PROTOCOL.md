# Integrated v1: experiment protocol (frozen before inference)

The machine-readable freeze is `FREEZE.json`. It holds the code and prompt hashes, models, endpoints, budgets, the matrix and the decision rule. It is written by `scripts/integrated_freeze.py`, which refuses to overwrite. Code, protocol and freeze are committed and pushed **before** any phase-2/3 call. Results are published only after that.

## Data
- **valid46** (`valid.parquet`, 23/23): this is development data. It has been seen in earlier phases and while repairing defects, so it is not a holdout.
- **SYN-M1 lockbox** (`outputs/multipacket_v1/suite_syn_m1`, 46 cases, 23/23). It is an authored synthetic suite whose inputs and gold were frozen in the multipacket phase, and it was already evaluated there (seen). Every case derives from a valid46 row (twin groups = base row). Its CALL_ARG_ID and FACT_NUMBER operators overlap the new ARG_VALUE_PROVENANCE and PROSE_VALUE relations by construction. A gain on SYN-M1 is therefore evidence that the mechanism works on its own construct, not evidence of transfer. No independent external holdout exists in this phase.
- Inference reads only `prompt`/`response`. Gold (`label`, `explanation`, `operator`) is read only by `experiments/integrated_v1/score.py`.

## Arms (one mechanism added per step, same packets, same rows)
| Arm | Definition | Extra calls |
|---|---|---|
| A1 | corrected U2 20k packet + I4 direct reviewer (`profile=baseline`) | 1 |
| A2 | A1 model decision + declaration guard overlay (MECHANICAL_PROOF ERROR wins) | 0 |
| A3 | A2 + deterministic scoped relation facts and their exact cited spans in the request (`profile=integrated`, first review) | 0 vs A1 (a different request) |
| A4 | A3 + at most one conditional verification pass (`profile=integrated`, final) | ≤1 |

The A3 and A4 numbers come from the same integrated run: A3 is the first review, A4 is the final decision. A2 is computed from the A1 run. A3 changes two things jointly: the facts and the cited spans added to the packet. Both come from the same relation module. Oracle arms are not run (see METHOD_FIT/RESULTS for the reason).

**Controller trigger (frozen):** the first review is ADMITTED, and either its decision is UNKNOWN, or it is NO_ERROR while ≥1 decisive relation fact exists. A technical failure never triggers it. If the second pass is admitted it is final; otherwise the first decision stands (`fallback_after`).

## Models and interfaces
- **Mistral:** `ministral-14b-2512` @ `https://api.mistral.ai/v1/chat/completions`, `json_schema` strict with source-ID enums. With A1, the request is byte-identical to the historical I4 body for the same packet (test).
- **Gemma:** `gemma4:31b` @ `https://ollama.com/v1/chat/completions` as the **reviewer**. Its interface is native `json_object` with the same schema text in the system prompt. The preflight showed that `json_schema` is not honoured: the model returned a non-schema object. Gemma wraps replies in a single ```json fence; admission unwraps exactly one whole-reply fence (`FENCE_STRIPPED`, counted) and repairs nothing else. The two families' requests are not claimed to be byte-identical; they share meaning, enums and admission code.
- Common settings: temperature 0, max_tokens 1700, 20 000-byte U2 budget.
- No model or provider substitution. One HTTP attempt per call. A transport failure is re-sent at most once on resume (`retry_failed=1`, logged). There is no backoff loop.
- **Cause judge:** `gpt-oss:120b` (Ollama) with the unchanged historical JUDGE_PROMPT. It runs only on predicted-ERROR, label-1 rows and gold explanations. Cause-correct = SAME + PARTIAL; a guard-owned TP counts as mechanically cause-correct, because its finding is a sourced schema violation. It is reported separately.

## Matrix and budget
| Phase | Family | Profiles | Reps (attempt = rep−1) |
|---|---|---|---|
| valid46 | Mistral | baseline, integrated | 1, 2, 3 |
| valid46 | Gemma | baseline, integrated | 1, 2 |
| syn_m1 | Mistral | baseline, integrated | 1, 2, 3 |
| syn_m1 | Gemma | baseline, integrated | 1 |

Estimate: ≈ 46 calls per baseline rep and ≈ 46–60 per integrated rep, i.e. ≈ 620 Mistral and ≈ 310 Gemma reviewer calls, plus ≈ 300 judge calls. Request size averages ≈ 4–9k prompt tokens.

Caps:
- Mistral: 900 calls / 6M tokens.
- Gemma: 600 calls / 4M tokens.
- Judge: 600 calls.

Counters are rebuilt from the attempts ledger after a restart. When a budget is exhausted, the remaining rows are recorded as `BUDGET_EXHAUSTED` → technical null; they are not dropped. If one Gemma transport is blocked (402/429/timeout) after a bounded attempt, the family is reported UNAVAILABLE/NOT_EXECUTED and is never replaced by another model.

## Scoring
- **Binary projection:** ERROR→1. NO_ERROR, UNKNOWN, rejected, invalid JSON, transport/budget failure and skipped all → 0, and each is counted separately. All 46 rows stay in the denominator.
- Per run: TP/FP/FN/TN, P/R/F1, cause-correct TPs, projection counts, calls, prompt/completion tokens, model seconds, controller triggers and fence normalizations.
- Per arm: the mean, min and max over reps.
- **Paired transitions vs A1:** per-rep flips, plus the majority-over-reps correctness per row with a two-sided sign test. With n=46 these are indicative; twins are clustered by row by construction.
- **Decision rule (pre-registered):** A3 or A4 replaces A1 as the default only if all of the following hold:
  - on both Mistral and Gemma valid46, mean F1 is higher and cause-correct TPs are not lower;
  - the pooled paired sign test has p<0.1;
  - SYN-M1 is not worse.

  A2 is adopted independently if it adds no FP on any run. Otherwise A1 stays the default and the technical repairs are kept independently.

## Historical comparability
- Frozen historical U2 replies match the corrected request hash for only 4/46 rows (5/46 even at the base checkout, because they were produced by an earlier packer). Fresh baselines are therefore mandatory, and no historical reply is reused.
- Historical numbers (U2_20k F1 0.684/0.727/0.700; Guardian OR Granite 0.889) are cited only as context.

## Amendment 1 (recorded during the run, before any scoring or judge call)
1. **Gemma/Ollama blocked.** During Gemma valid46 rep 1, Ollama Cloud returned `429 "you have reached your monthly usage limit"`. Completed at that point:
   - Gemma valid46 **baseline rep1**: 46/46 sent (43 admitted, 3 technical nulls).
   - Gemma valid46 **integrated rep1**: 16/46 executed, 30 rows HTTP 429.
   - Gemma rep 2 and Gemma SYN-M1: all 429, or stopped.

   The runner was stopped; there were no retry loops.
2. **Fallback Gemma transport, one bounded smoke.** AI Horde `google/gemma-4-31b` was the pre-listed alternative. It was tested with one `/models` discovery and one review request (200 in 7.6 s), but the reply was **truncated at 931 characters** with `finish_reason=stop` (worker output cap), so it is invalid JSON under the frozen 1700-token contract. This transport is therefore not usable without changing the contract and was not used.
3. **Gemma family status:**
   - valid46 baseline (rep1): COMPLETE.
   - valid46 integrated (rep1): **PARTIAL 16/46, 30 PROVIDER_LIMIT slots**, kept in the 46-slot inventory.
   - Paired Gemma results are reported only on the 16 rows completed under both profiles, labelled as a pilot. They are never substituted with Mistral.
   - Resume command: RUNBOOK (`retry_failed=1` re-sends each limited slot once).
4. **Cause judge.** `gpt-oss:120b` is on the same exhausted Ollama account. It is replaced by the pinned `mistral-medium-2604` (Mistral API) with the unchanged JUDGE_PROMPT and a 600-call cap. Caveats:
   - It is a different model from the reviewer (`ministral-14b-2512`) but the same vendor family.
   - Cause counts are not directly comparable to historical gpt-oss judgements.
5. The Mistral matrix and every other frozen element are unchanged.

## Amendment 2 (post-hoc, recorded after the valid46 Mistral scores, before any judge call or SYN-M1 scoring)
**Observation.** Relation facts (A3) lowered Mistral valid46 F1 compared with A1. Most changed rows had **no decisive fact**: they received only reassuring `OBSERVED_BEFORE_MOVE` confirmations. This is diagnosed as a reassurance/dilution effect.

**Post-hoc variant `integrated_gated` (arms A3g/A4g):**
- Relation facts are sent **only when ≥1 decisive fact exists**, and then only the decisive facts and their cited spans.
- Otherwise the request is byte-identical to A1. On valid46 the exact cache therefore reuses the A1 replies for those rows: same request, same attempt index.
- Everything else is unchanged: the controller trigger, the guard and admission.

**Matrix.** Mistral valid46 reps 1–3, then Mistral SYN-M1 reps 1–3. It runs after the frozen SYN-M1 runs, under the same budget caps. Gemma is not run (provider limit).

**Status.**
- A3g/A4g were designed after seeing valid46 results, so valid46 numbers for them are **development/post-hoc** and cannot satisfy the pre-registered decision rule.
- SYN-M1 is the only check, and it is authored and seen, with operators that overlap the decisive relations.
- The variant can therefore be recommended at most as a **shadow candidate** pending a new independent lockbox.

## Amendment 3 (cause judge, before any judge verdict was obtained)
- `mistral-medium-2604` returned `429 Rate limit exceeded` (code 1300) on every call, including after a cooldown. The same happened for `mistral-small-latest` and `magistral-*`, while `ministral-14b-2512` stayed available.
- The judge is therefore `ministral-14b-2512`: the same model as the Mistral reviewer, with the unchanged JUDGE_PROMPT.
  - **Self-judging bias:** cause counts may be inflated for Mistral reasons. They are comparable across arms of the same reviewer, but not with historical gpt-oss counts.
  - Gemma reasons are judged by a different model.
- Mitigation: CAUSE_AUDIT.md adds a manual source-level audit of every row that changes between arms.
- The 135 rate-limited judge attempts are kept in the judge ledger. The cap is raised to 900 attempts, failed ones included.
