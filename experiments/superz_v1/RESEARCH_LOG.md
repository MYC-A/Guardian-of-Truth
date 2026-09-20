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

---

## 7. Architecture C END-TO-END (2026-09-20, session 2)

Goal (user directive): bring C to a full end-to-end experiment — not just
two-theory extraction, but their REAL mutual verification and correction
using original LangExtract fragments; measure preservation of modality /
conditions / exceptions / participants / temporal / scope; add consequence
checking with control situations; compare C0 / C1 / C2 / C3 on ONE dataset
with the SAME formal engine; count corrected FP AND lost TP AND new FP;
never let a missing exact quote auto-produce a negative label.

Pipeline (`arch_c/theory_case.py`, `run_c_e2e.py`): theory variant →
Mistral hypothesis generation tied to theory elements (element_index +
response_fragment) → SAME arch_d formalizer (typed templates, rule quote
forced to the byte-exact policy substring at the element's span-verified
position) → local resolver + Clingo → case label = 1 iff any CONFIRMED.
Hypothesis/formalizer providers held CONSTANT (mistral) across variants;
the only varying input is the theory. Element order is CANONICAL (document
position) for every variant — otherwise prompt-order noise masquerades as
theory differences (caught and fixed mid-experiment).

| Variant | TP | FP | FN | TN | P | R | F1 |
|---|---|---|---|---|---|---|---|
| C0 glm-theory | 3 | 0 | 13 | 16 | 1.0 | .188 | .316 |
| **C1 union (indep. extraction)** | **7** | **0** | 9 | 16 | **1.0** | **.438** | **.609** |
| C2m one-sided-aggressive | 3 | 0 | 13 | 16 | 1.0 | .188 | .316 |
| C3 +consequence flags (strict) | 6 | 0 | 10 | 16 | 1.0 | .375 | .546 |

Transitions (the user's requested cost accounting):
- **C0→C1: +4 TP (a2_refund_amount, b4_failed, r4_points, t2_port), 0 new
  FP, 0 lost TP.** The union of independent GLM+Mistral extractions more
  than doubles recall at unchanged P=1.0 — Mistral's elements closed real
  theory gaps; the formal layer absorbed the added noise.
- **C1→C2m: −4 TP, 0 corrected FP, 0 new FP.** Aggressive one-sided
  criticism (a single reviewer rejecting elements with no second side
  available) destroyed exactly the four detections the union had gained.
  The five `challenged_one_sided` elements carried real normative content.
- C2m→C3: +4/−1 — but the meaningful C3 comparison is vs its own base
  theory (C1/C2): **−1 TP (b1_stale), 0 corrected FP.** The consequence
  flag fired on the element («the new balance must always be re-read from
  get_balance») whose synthetic control-situation formalization failed,
  although the same element's formalization CONFIRMED the real b1_stale
  case correctly. A false alarm of the consequence mode — quantified, and
  the reason the lenient aggregation (report-only) is the default.

### Real mutual criticism (`arch_c/mutual_review.py`)

Criticism items = 5 span-disagreements (element in one theory only) + 6
modality conflicts (overlapping spans, different MODAL class: запрет vs
разрешение/обязанность — these change what counts as a violation; found by
a new mechanical scanner, 17 raw class overlaps of which 6 are modal).
Each item reviewed against the ORIGINAL clause with decisive-quote
verification by BOTH models (mutual, not a single arbiter). Repair rules
(recall-preserving): drop only when BOTH sides concede invention; one-sided
rejection → keep flagged `challenged_one_sided`; split → keep flagged
ambiguous; class corrections applied only when both sides agree.
Mistral side: 11/11 items reviewed (8 faithful incl. 3 modality
preferences, 5 span-invented challenges, verdicts verified quotes 5/8
grounded). **GLM side: BLOCKED — z-ai returned 429 for the entire ~3h
session; C2 both-sides completion is PENDING, honestly marked.** C2's
current theory therefore equals C1's element set (conservative rule keeps
everything criticizable), and the C2 row is intentionally absent above.

### Facet preservation audit (`arch_c/facet_audit.py`)

Independent reference: 52 facets extracted from the ORIGINAL policies
(modality/condition/exception/participant/temporal/scope/threshold),
quotes verified 49/52 after emphasis-tolerant matching. Audit (per facet:
is its information captured by some theory element?):

| Policy | C0 | C1 | C2m |
|---|---|---|---|
| banking | 1.00 | 1.00 | 1.00 |
| airline | 1.00 | 1.00 | 1.00 |
| telecom | .824 | .882 | .941* |
| retail | 1.00 | .909 | .909 |

*telecom C2m shows 0.941 only because the auditor's by-type table keeps
the union facets; its порог rate collapsed 1.0→0.0 (the «two failed
resolution attempts» threshold element was dropped by the one-sided
challenge) and retail's exception rate fell to .67 — the same semantic
loss that cost the 4 TPs. C0's telecom gaps (exception 0.0, threshold
0.0, scope .5) are recovered by the union (C1: exception 1.0, threshold
1.0) — the facet audit independently confirms the C0→C1 recall gain.
Caveat: single-auditor LLM judgments have ±1-facet noise (visible as
C1<C0 on retail despite C1⊃C0 — mechanically impossible, hence noise).

### Consequence checking (`arch_c/consequence.py`)

10 rules × 2 constructed situations (ok + err, ground truth by
construction): sources = theory divergences + independently discovered
facets missed by C0. TWO SEPARATE checks per situation:
1. FORMAL: rule → typed template (world facts as observable fields) →
   resolver + Clingo. Clingo computes consequences of THIS formalization
   only — it is never the judge of natural-language interpretation.
2. CORRESPONDENCE: LLM judges the situation against the ORIGINAL clause
   (decisive quote verified) — the semantic authority.
Result matrix: 10 ok-situations: formal 8 definitive & correct,
correspondence 9 correct; 10 err-situations: formal 4 correct, 3
unresolved (binding gaps — the known bottleneck), 3 wrong (exception
over-application); correspondence 9 correct, 1 ambiguous.
Flags: 4 elements flagged unreliable (formal wrong while correspondence
right — genuine formalization errors caught); 2 untested. Strict C3
applies the flags; lenient reports only. **On this dataset the flags
produced −1 TP and 0 corrected FP** (see above) — the mode is diagnost
ically valuable (it names WHICH formalizations diverge from the natural
reading) but not yet a safe label filter.

### C vs direct judge vs hybrids (same dataset, same providers)

| System | TP | FP | P | R | F1 |
|---|---|---|---|---|---|
| A0-mistral direct judge | 16 | 4 | .80 | 1.00 | **.889** |
| B1-mistral suspicion judge | 15 | 14 | .52 | .94 | .667 |
| B1-glm suspicion judge | 15 | 9 | .63 | 1.00 | .769 |
| C1 union→formal | 7 | 0 | **1.00** | .44 | .609 |
| Hybrid A0m OR C1 | 16 | 4 | .80 | 1.00 | .889 |
| Hybrid A0m AND C1 (C as filter) | 7 | 0 | 1.00 | .44 | .609 |

On short clean policies the direct judge is simply stronger; C's every
confirmation is a subset of the judge's positives, so OR-hybrids add
nothing and AND-hybrids trade recall for precision 1:1. C's value must
come from the regime where judges fail (long τ-bench policies: there
A0-glm F1=.790 while the whole B-chain collapses to .651) — the C run on
public46 is queued behind the GLM quota. Per the user's directive, no
additional mechanism enters the final Guardian until its standalone
contribution is measured on independent data.

### Infrastructure findings (session 2)

- **Canonical element order is mandatory** for variant comparisons: the
  same element set in different order produces different hypotheses
  (caught via a C3-vs-C1 flip that traced back to prompt-order noise).
- Mistral adds `**bold**` emphasis to quotes absent from the source —
  breaks byte-exact span checks; fixed by emphasis-stripping realignment
  (telecom theory B 0→8 anchored elements, coverage .89→1.00) and
  emphasis-tolerant quote verification in the facet audit.
- Mistral emits JS-style `//` comments and raw newlines inside JSON;
  robust per-object balanced-scan parsing with comment/trailing-comma
  cleaning recovered 100% of previously failed generations from cache
  (zero extra API calls).
- rule_quote for theory-derived hypotheses = policy substring at the
  span-verified element position (byte-exact by construction) — absence
  of a model-quoted citation can never auto-negative a case (user rule).
- Pair-file structure bug (outer container vs inner dict) fixed; retry
  markers prevent infinite regeneration loops.

Commands: `python3 experiments/superz_v1/arch_c/mutual_review.py
[--finalize]`, `.../run_c_e2e.py --variants C0,C1,C2m,C3`,
`.../facet_audit.py --stage reference|audit`, `.../consequence.py`,
`.../summarize_systems.py`. All runs resumable, all calls disk-cached.

### Pending (z-ai GLM 429 for the whole session — NOT done, not faked)

1. C2 both-sides mutual criticism (8 GLM reviews) + C2 e2e row.
2. A0-glm direct judge on synth32 (the GLM anchor for the judge comparison).
3. GLM-side facet reference (union reference) + GLM-side audits.
4. C on public46 policies (8 LangExtract calls) + C-e2e on public46.
5. B4x GLM→Mistral reviews on public46 (43 calls, secondary).
