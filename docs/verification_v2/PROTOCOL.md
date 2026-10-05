# Verification v2 — frozen protocol (written before any v2 mechanism code)

Branch `research/guardian-verification-v2-20261006`, based on integrated v1 `6dfd72ab`.
Question (from the post-integrated research summary, §19): **does a controlled counterfactual /
contrastive probe find real missed violations better than an ordinary second reviewer, and does a
narrow source-bound verifier filter false accusations?**

## 0. Hygiene done first (no semantics change)
- `ReviewConfig()` default == `ReviewConfig.profile('guard')` (A2); CLI default `guard`; package
  example `guard`; regression tests in `tests/verification_v2/test_hygiene.py`.
- `integrated`/`relations` marked FAILED experimental; `integrated_gated` SHADOW/post-hoc.
- RUNBOOK test count 42 → 44.

## 1. Fresh lockbox LB1 (built and hashed before mechanism code)
- Generator `experiments/verification_v2/lockbox/` → `outputs/verification_v2/lockbox/{short,long}/`.
- 6 new domains, none in valid46 (pharmacy, car rental, university registration, IT service desk with an
  explicit closed tool universe, home insurance, utility billing). 57 cases: 28 ERROR / 29 NO_ERROR.
  Most cases are minimal pairs (ERROR vs matched NO_ERROR control differing in one premise).
- Strata: same-looking IDs, wrong entity, stale value, newer state supersedes older lookup, failed tool
  then false success claim, later (2nd/3rd) current call violation, fabricated prose action,
  date arithmetic, cross-call arithmetic, prose arithmetic/number, missing/failed prerequisite,
  exception active/inactive, permission ≠ requirement, unavailable tool under explicit closed universe,
  actor swap (user claims approval), chronology (confirmation for a superseded plan), user correction
  supersedes, workflow omission (no confirmation), valid value conversion, optional args omitted,
  computed legitimate values.
- `long` (PRIMARY) adds a near-miss policy appendix and a benign earlier sub-task with large tool
  outputs (47/57 packets are SELECTED, not FULL_INPUT, at the 20 kB budget). `short` is SECONDARY.
- Inputs carry only opaque IDs; gold (label, family, target, cause, keys) is read only by the scorer.
- Limitation stated up front: authored by the same agent that designs the mechanisms (mitigated by
  freezing before mechanism code, minimal pairs, and reporting per-family results).

## 2. Arms (one model family: Mistral `ministral-14b-2512`, temperature 0, U2 packet 20 kB)
- **A** = A2 (`guard` profile): frozen integrated-v1 reviewer + mechanical guard. Baseline to beat.
- Escalation set E = rows where A's final decision is not ERROR (NO_ERROR, UNKNOWN, technical null).
  All extra mechanisms run only on E (matched calls: one extra proposer call per escalated row).
- **B** = A + ordinary second reviewer on E: same packet, generic skeptical re-review instruction,
  no new signal. ERROR if admitted ERROR.
- **C** = A + counterfactual/contrastive probe on E (code-built minimal variants of the current move;
  see §3). ERROR if the probe's admitted original-move status is VIOLATING.
- **Bv / D** = B / C with every candidate checked by the narrow source-bound verifier (§4); ERROR only
  if SUPPORTED with mechanically verified verbatim quotes.
- **Av** (shadow) = verifier applied to A's own ERROR accusations (FP filter). Reported, never default.

## 3. Counterfactual probe (code controls the intervention; the LLM is the measured system)
For every current target, code builds at most 10 minimal variants, each changing ONE thing:
- call argument leaf → an alternative value of the same type class (number, date, ID-like token, short
  string) observed earlier in the conversation, ranked: same key name > same JSON object neighbourhood
  as a target value > user-stated; ≤3 per leaf, newest first;
- OMIT_CALL: the call is not made (assistant replies to the user instead);
- prose: a number/ID/date in the prose → same-type alternative observed earlier (closest magnitude);
  OMIT_SENTENCE for each prose sentence that asserts a completed action or a stated value.
The model sees the same U2 packet plus the original move and the variants and must classify the
original and each variant as COMPLIANT / VIOLATING / UNCLEAR with enumerated source IDs. Variants are
explicitly described as mechanically generated and possibly all worse. A candidate = admitted
VIOLATING original with a valid target, policy source and evidence. Variant-original consistency is
recorded as a diagnostic (not used for the decision in C).

## 4. Narrow source-bound verifier
Input: the candidate (target, claimed violated requirement, reason), the exact text of the current
target(s), the cited policy source(s) plus the 2 BM25-nearest other policy chunks to the claim, the cited
evidence sources, and the last 4 history events. Output: SUPPORTED / REFUTED / UNRESOLVED with a verbatim
`policy_quote` and `evidence_quote`. Code checks both quotes are substrings (whitespace-normalised) of
the provided texts; SUPPORTED without verified quotes is downgraded to UNRESOLVED (recorded).

## 5. Metrics (scorer reads gold only after all inference)
Binary P/R/F1 (UNKNOWN and nulls project to 0); TP gained / FP added vs A (paired transitions);
**cause-correct TP** (LLM judge, amendment-3 style prompt vs gold cause; plus target-ID match when the
gold target is a call); pair accuracy (both members of a minimal pair correct); per-family recall;
candidate count and candidate precision; verifier rejections of true/false candidates; extra calls,
tokens, escalation fraction.

## 6. Frozen decision rule (LB1-long primary)
The counterfactual direction is **supported** only if D vs A gains ≥3 cause-correct TPs with ≤1 new FP
AND D's net (cause-correct TP gain − new FP) exceeds Bv's by ≥2. Otherwise: not supported on this
lockbox. The verifier is **useful** if, across B and C candidates, it rejects ≥50% of false candidates
while keeping ≥70% of true cause-correct candidates. valid46 and SYN-M1 are development/secondary
sets only (A2 already tuned there).

## 7. Budget / execution
Mistral only (Ollama quota exhausted). ≤900 model calls total, ≤1 req/s pacing for the judge,
≤4 workers for reviewers. Exact-equivalence cache; every attempt in the ledger; no hidden retries
except the transport's frozen retry policy. One repetition per arm (rep 2 of A and D if budget allows).

## Amendment 1 (2026-10-06, after LB1-long phase-1 results, before any new mechanism code)
- Phase-1 LB1 results were inspected (see RESULTS.md). Any mechanism designed after this point is
  development work on LB1 and is evaluated on **LB2**, a second fresh lockbox frozen here:
  4 further new domains (hotel, fitness club, event tickets with explicit closed tool universe,
  courier), 47 cases (23 ERROR / 24 NO_ERROR), one minimal pair per §18 stratum, long variant only,
  hashes in `outputs/verification_v2/lockbox2/long/MANIFEST.json`.
- LB2 was authored by rotating through the summary §18 strata list (not chosen per mechanism).
- On LB2 every arm is reported against both A (frozen A2) and A_adm2 (admission v2).

## Amendment 2 (2026-10-06, before any LB2 inference; LB2 frozen in commit 9d170784)
New post-LB1 mechanisms, designed on LB1 failure analysis (development only on LB1):
- **E — requirement checklist with deterministic date table.** E1 (verdict-free): extract the
  applicable requirements from the policy with verbatim quotes (code-verified substrings) given the
  move. E2: check each requirement against the packet plus a code-computed CALCULATIONS table
  (calendar days / hours from the policy's "current time", weekday, age in years). A requirement is
  VIOLATED only with a verified evidence quote; a stated computation that contradicts the table
  becomes UNRESOLVED. 2 calls per row. **Ev** = E candidate kept only if the narrow verifier
  returns SUPPORTED (+1 call per candidate).
- **Primed arms** B', Bv', C', D', E', Ev' = the same candidates added on top of the A_adm2 base
  (admission v2 replay of A, no extra calls) instead of frozen A.
- Budget raised to ≤1400 model calls (runner hard cap).
- **Pre-registered LB2 rules** (LB2-long primary, 1 rep):
  1. Admission v2 is adopted as default iff on LB2 A_adm2 vs A adds ≤1 FP and loses no TP.
  2. E' is **supported** iff vs A_adm2 it gains ≥3 cause-correct TP with ≤1 new FP AND its net
     (cause-correct TP gain − new FP) is ≥2 above the better of B' and Bv'. Same rule for Ev'.
  3. The counterfactual D' and C' are re-reported on LB2 with the frozen §6 rule (on A_adm2 base).
  4. Verifier usefulness re-tested with the §6 criterion on LB2 candidates of B, C and E.
- LB1 results for E are development results and are not evidence for rule 2.
- Development log for E on LB1-long (before LB2, recorded here): smoke run (3 rows) → iteration 1 (57 rows:
  E' vs A_adm2 +1 cause-correct TP, +2 FP) → fixes of generic defects only: policy-quote check tolerant to
  list markers / trailing punctuation / stitched list items / near-verbatim (ratio ≥0.9) wording, since
  E1 quotes only ground requirements; numeric comparisons ("30 < 48") recorded as a diagnostic only
  (models flip their order) → iteration 2 = final frozen E (E' +1 cause-correct TP, +3 FP vs A_adm2;
  Ev' +1, +1 FP). No further LB1 iteration. E code is frozen in the commit that adds this line.
- Opt-in profile `guard_adm2` (= guard + admission v2) added to the integrated pipeline; the v2 runner
  pins frozen A to admission v1. Whether it becomes the default is decided by rule 1 on LB2.

## Amendment 3 (2026-10-06, after LB2 results; offline audit, no new model calls)
Code audit of the LB2 results found post-processing gates of the same class as admission v1. Rules below are fixed
before the replay is run; they reuse existing generic code and are written without consulting gold. Because LB2
was already inspected, every result of this amendment is **post-hoc development evidence**, not a lockbox claim;
adoption of anything here needs a fresh lockbox (LB3).
- **Q2 — verifier quote admission v2.** `policy_quote_ok` = `quote_fragments_ok` (the E1 rule: list markers,
  trailing punctuation, stitched pieces of one source, near-verbatim ratio ≥0.9) against any provided policy text;
  `evidence_quote_ok` = `quote_fragments_ok` against any provided evidence / current-move / declaration text.
  Minimum quote length unchanged (8). Sensitivity variant Q2s (reported, not primary): an evidence quote shorter
  than 8 chars is admitted if it equals a complete JSON string value of a provided source.
  The verifier input is rebuilt with `narrow()` and must hash to the stored `request_sha256` (else the row is
  reported as NOT_REPLAYABLE). Raw verdicts are unchanged; only the downgrade decision is recomputed.
- **Q2 also applies to the E2 evidence-quote gate** (VIOLATED needs a verified evidence quote).
- **G_E — E consistency gate.** A VIOLATED item whose `computation` contains a numeric comparison that evaluates
  false becomes UNRESOLVED (`COMPARISON_FALSE`). If this changes E's first VIOLATED item, the new candidate has no
  verifier call: E uses it, Ev counts it as not SUPPORTED and the count is reported (`needs_verifier_call`).
- **C_dir — directional counterfactual (diagnostic arm).** C candidate kept only if the original is VIOLATING and
  at least one variant is COMPLIANT. On the A_adm2 base: C_dir′; with verifier: D_dir′.
- Re-computed: all arms on LB1-long, LB1-short, LB2-long, valid46; §6 verifier criterion; plus a per-FN
  capability matrix for LB2 (evidence present / candidate generated / verifier raw→final / gate / variant touched
  the gold target value / missing capability).
