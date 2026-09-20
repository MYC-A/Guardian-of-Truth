# Super Z — Independent Architecture Research Log (Guardian of Truth)

Branch: `research/superz-20260920` (base `full-architecture-v1` @ `923bb44`).
Agent: Super Z. Period: 2026-09-20. Infrastructure: local container
(2 CPU, 4 GB RAM, no GPU, no SSH to ModelScope — the server is inaccessible
from this environment; all model calls via z-ai GLM API and Mistral API).

Models: **glm-4-plus** (z-ai, via Node SDK bridge) and
**ministral-14b-latest** (Mistral API, key shared by the user; never printed
or committed — stored in `experiments/superz_v1/.secrets/mistral.env`,
git-ignored). Clingo 5.8.2 via `/usr/bin/python3.13` subprocess bridge.
LangExtract (Google) with custom `ZaiLanguageModel` / `MistralLanguageModel`
providers — source-grounded extraction with byte-exact span verification and
whitespace-insensitive re-alignment for line-wrapped policies.

Datasets:
- `public46` (viewed-dev, diagnostics only; labels sealed in
  `data/public46/labels_local.json`, never in prompts).
- `synth_pairs_v1` — 16 pairs / 32 cases, 11 controlled error types,
  labels by construction (`data/synth_pairs/`). Independent of Codex's sets.

All runs are resumable; every LLM call is content-hash cached on disk
(`results/llm_cache/`). Raw per-case predictions with quotes/verdicts are
stored under `results/`. Reproduction: `python3 experiments/superz_v1/<arch>/<runner>.py`
(see command lines in each section).

---

## 1. Architecture A — direct judge baseline

| Config | Dataset | TP | FP | FN | TN | P | R | F1 |
|---|---|---|---|---|---|---|---|---|
| A0-glm direct 0/1 | public46 | 15 | 1 | 7 | 21 | .938 | .682 | **.790** |
| A1-glm suspicion-forced | public44 | 18 | 10 | 3 | 13 | .643 | .857 | .735 |
| B1-mistral suspicion-forced | public45 | 23 | 22 | 0 | 0 | .511 | 1.00 | .676 |
| B1-mistral suspicion-forced | synth32 | 15 | 14 | 1 | 1 | .517 | .938 | .667 |

Commands: `python3 experiments/superz_v1/arch_a/run_judge.py --variant A0|A1`
(public46); `results/arch_b/B1_mistral_*` for Mistral judges.

Findings:
- GLM-4-plus is a **high-precision conservative judge**; forcing it to
  enumerate suspicions with quotes (A1) flips it recall-heavy (+3 TP, +9 FP).
  Mistral is recall-heavy in both prompt modes (suspicions in ~every case:
  147 suspicions on public46, 22 FP).
- Historical Mistral-judge numbers (22 TP / 14 FP, F1 .746, other prompts)
  and Codex's fresh run (20/10, .755) are consistent with our B1-mistral
  behaviour — model character, not prompt artifact.
- 2 A1 cases (of 46) remained unjudged at the time of analysis (z-ai quota).

## 2. Architecture B — suspicion cross-verification

Pipeline: B1 judge suspicions → B2 quote grounding (byte-exact location in
response + claimed source) → B3 mechanical fact-ledger checks (entity-scoped
latest-value stale detection, failed-call claims) → B4 cross-review
(REVUTED requires positive counter-evidence; stale-direction rule; batched
1-call-per-case variant `batch_review.py`).

| Config | Dataset | TP | FP | FN | TN | F1 |
|---|---|---|---|---|---|---|
| B1-glm any-suspicion | synth30 | 15 | 9 | 0 | 6 | .769 |
| B2 grounded filter | synth30 | 15 | 9 | 0 | 6 | .769 (no change) |
| B4-glm v1 review (loose rules) | synth30 | 8 | 1 | 7 | 14 | .667 |
| **B4b-glm disciplined review** | synth30 | **12** | **1** | 3 | 14 | **.857** |
| B4b-glm (same 22-case subset) | synth22 | 12 | 0 | 3 | 7 | **.889** |
| Mistral→GLM cross-review | synth22 | 11 | 1 | 4 | 6 | .815 |
| B4b-glm self-review | public44 | 14 | 8 | 7 | 15 | .651 |
| B2 grounded filter (mistral sus) | public45 | 12 | 16 | 11 | 6 | .471 |
| Mistral self-review (batch) | public45 | 22 | 21 | 1 | 1 | .667 |

Findings:
1. **Quote grounding ≠ semantic correctness.** All 9 synth FPs were fully
   grounded (real quotes, wrong interpretation). On public46 the grounding
   filter applied to Mistral suspicions *destroys* recall (TP 23→12) —
   Mistral paraphrases quotes on true errors but sometimes grounds false
   ones. LangExtract-style anchoring is necessary for auditability, not
   sufficient for verification — exactly as the task directive warned.
2. **Reviewer decision rules dominate.** Same reviewer model, revised rules
   (REFUTED only with quotable counter-evidence; stale-direction
   disambiguation; explicit mechanical hints): synth F1 .667 → .857,
   recovering +4 TP at FP 1.
3. **Self-review of a noisy judge removes nothing** (Mistral→Mistral:
   22/21 vs 23/22; −1 TP −1 FP). Correlated errors confirmed.
4. **Cross-model review is not automatically better** — Mistral reviewing
   GLM's suspicions (synth .815) underperformed disciplined GLM self-review
   (.889) on short clean policies; the missing cell (GLM reviewing Mistral
   on public46, 43 reviews pending z-ai quota) is the decisive test for
   complex policies.
5. On complex real policies (public46) the whole GLM B-chain (F1 .651)
   underperforms the plain A0 direct judge (.790): judge and reviewer share
   policy misreadings. Hybrid E1 (A0 OR B4b-supported) = TP16 FP8 F1 .696 —
   the FP inheritance cancels the recall gain.

## 3. Architecture C — joint theory construction (LangExtract-centered)

Dual extraction with two personas (normative-complete vs
permissive-adversarial), clause-coverage registry, disagreement detection by
span-overlap, LLM arbitration with decisive quotes verified byte-exact.

| Policy (synth) | norm. clauses | cov A | cov B | cov union | disagreements |
|---|---|---|---|---|---|
| banking | 9 | 1.00 | 1.00 | 1.00 | 2 (same-model) / 1 (cross) |
| airline | 9 | 1.00 | 1.00 | 1.00 | 1 / 1 |
| telecom | 9 | 1.00 | 1.00 | 1.00 | 6 / 3 |
| retail | 9 | .89 | 1.00 | 1.00 | 1 / 0 |

Cross-model (GLM theory A vs Mistral theory B, same LangExtract machinery):
both models reach 100% normative clause coverage; 1/1/3/0 cross-model
disagreements per policy — fewer than same-model persona disagreements,
i.e. model families differ less than personas on these short policies.

Infrastructure findings (matter for any grounding pipeline):
- **Line-wrapped policies break byte-exact spans**: exceptions spanning
  line breaks were dropped as UNANCHORED until a whitespace-insensitive
  re-alignment was added (recovered 100% of previously dropped elements —
  incl. the critical `EXCEPT ...` clauses).
- The `<policy>` tag appears twice (instructions reference it); the parser
  must take the LAST tag pair or it captures instructions as policy.
- Coverage must be computed over NORMATIVE clauses only (headers/tool lists
  accounted as non_policy_with_reason), else coverage is diluted 2x.
- Arbitration verdicts with grounded decisive quotes: on completed reviews
  all were `element_faithful` — the disagreement set (hard classes only,
  span-overlap based) is conservative.

## 4. Architecture D — local formal hypothesis verification

LLM formalizes one suspicion into a typed template (trigger + conditions +
exceptions bound to concrete tool fields); Python resolves entity-scoped
evidence; Clingo re-verifies with explicit three-valued states; CONFIRMED
only when all conditions hold and every exception is positively absent.

| Variant | TP | FP | FN | TN | P | R | F1 |
|---|---|---|---|---|---|---|---|
| v1 permissive binding | synth | 1 | 0 | 14 | 9 | 1.0 | .067 | .125 |
| v2 mandatory binding | synth | 2 | 1 | 13 | 8 | .667 | .133 | .222 |
| v2 + claim-link guard | synth | 2 | 0 | 13 | 9 | **1.0** | .133 | .235 |

Local machinery gates (hand-built hypotheses): 7/7 PASS — exception applies
→ refuted; unknown premise → never confirmed; ASP agrees with the typed
resolver; stale claim_match distinguishes ok/err twins.

Findings:
- **The solver is never the bottleneck; NL→template binding is.** 16/26
  hypotheses unresolvable in v1 because the formalizer did not bind
  conditions to observable fields. v2 (mandatory binding + explicit
  OBSERVABLE FIELDS list) converts unknowns into resolutions but creates
  vacuous-condition FPs; the claim-link guard (statement-trigger hypotheses
  need a claim_match condition tied to the response) restores P=1.0.
- Soundness rules that survived: unknown ≠ confirmed; exception unknown →
  unresolved; entity scoping (same-name different-account) handled by
  scoped evidence preference; later-read preference with explicit seq.

## 5. Environment / transfer notes

- z-ai quota ≈ 30 requests / ~30–60 min (hard blocker; all runners are
  resumable, cache-first). Mistral quota shared with Codex's server runs —
  used in measured bursts.
- Background processes do not survive between shell sessions; everything is
  foreground-chunked with `--max-seconds` budgets.
- The z-ai→GLM path handles 130KB+ prompts with correct end-of-context
  recall (verified with markers).

## 6. Conclusions and next steps

1. Best current public46 configuration in this line: **A0-glm direct
   (.790)**; best synth configuration: **B4b disciplined review (.857)**.
2. The B-architecture works where the policy is short/clean; on long
   τ-bench-style policies the judge+reviewer correlation dominates. The
   pending experiment — GLM batch-reviewing Mistral's public46 suspicions
   (43 reviews, blocked by z-ai quota) — targets exactly this.
3. Architecture D is sound but binding-limited; the productive direction is
   C→D integration: formalize from the *repaired theory elements* (anchored
   rule quotes + verified conditions) instead of raw suspicions.
4. Negative results kept: B2 grounding filter (hurts Mistral), Mistral
   self-review (no-op), E1 union (FP inheritance), v2 binding without
   guard (vacuous conditions).

Unfinished / queued:
- B4x GLM→Mistral cross-review on public46 (43 calls, z-ai quota-blocked;
  runner ready: `arch_b/batch_review.py --out-name B4x_glm_review_mistral`).
- Cross-model arbitration reviews for C (5 calls pending; z-ai).
- A0-glm on synth32; C on public46 policies (8 LX calls); D on public46.
- AgentHallu own slice (dataset cloned locally, adapter not yet built).
