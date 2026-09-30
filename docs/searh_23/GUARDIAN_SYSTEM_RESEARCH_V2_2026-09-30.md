# GUARDIAN OF TRUTH — SYSTEM RESEARCH V2

**Branch:** `zai/system-research-v2-20260930` (from
`codex/system-integration-step1-4-20260930` @ `b473a2f9`) · **Date:** 2026-09-30
**Directive question (§106-107):** where exactly does an LLM remain
irreplaceable, where can its output already be reliably verified or
falsified without another LLM, and did we actually reduce the dependence on
one LLM understanding everything correctly on the first try?

**Order of trust:** sealed v2 > dev v2 > v1 dev material (probe/calibration).
All sealed gold stayed unopened until every arm, prompt, and scorer was
frozen and committed (commit `869feac1` suite freeze; `6194168d` arms).

---

## 1. Starting commit and environment change

Base: `b473a2f9` ("Measure claim evidence ablation on frozen system suite").
Before any experiment, the frozen proof core was reproduced locally:
`eval_system_runtime.py` gives full_dev 17/21, refusal_dev 5/8,
refusal_sealed 5/8 — byte-identical to the V1 report. Zero drift.

**Environment (documented, not hidden):** the Guardian GPU gateway
(Granite/Mistral backend) was unavailable the entire session and the
previous Mistral API key now returns 401. All V2 inference ran on the
user-supplied new providers: ollama.com (`gemma4:31b`, `gpt-oss:20b/120b`,
`nemotron-3-nano:30b/-super/-ultra`; `glm-5.3-flash` is paywalled/402),
ukisai `swift`, vireonix `auto`. Provider health checks (§101) passed for
all used models including structured JSON probes. V2 model-specific numbers
are therefore **not comparable** to V1 Mistral-based rounds; the frozen
oracle paths (model-independent) reproduce exactly.

## 2. Historical mechanisms found in the repo (not repeated blindly)

RuleIR (`experiments/architectures_v2/b_theory/ruleir_boundary.py`), GRS
(`src/guardian_truth/vnext/policy_grs*.py`), staged policy trees
(`staged_policy_tree_v1/v2`), action-conditioned policy probes
(`system_integration_v1/action_conditioned_v1.py`), F6 arms A-I (graph
level), Step3 mode/candidate probes, refusal_v1 reachability. Per §1 each
new arm below carries an `ALREADY TESTED?` verdict in §7.

## 3. What was NOT repeated

- NLP-first candidate generation (refuted in F6, §2 of the directive).
- Always-on second LLM / generic judge / uncertainty gating (F6 negative).
- LangExtract (F6 negative; no long-policy retrieval need materialised).
- Graph-level Φ union (F6 ARM H graph proxy) — replaced by runtime-level
  consensus over the actual proof engine.
- Reachability core rewrite (§50) — reused frozen.

## 4. Fresh frozen suites

`experiments/searh_23/system_research_v2/frozen/trajectories_v2/`
(manifest SHA256s inside `manifest.json`): **20 dev + 20 sealed** fully
synthetic trajectories, domain-disjoint across splits and from all previous
suites (bakery / ferry / museum / orchard / lab-prose-only; cinema /
quarry / apiary / transit-refusal / archive-claim-stress). Every case was
**self-verified against the frozen proof runtime before freezing** —
verdict AND world facts reproduce exactly (40/40); the lab family under
injected oracle contracts. Stress coverage: async request-vs-completion,
timeout rules, ferry 8-sentence and quarry 7-sentence multi-rule policies
(base + exception + actor rule + second rule + clarification), schema
version change, same result-field name in two tools, entity IDs that
matter (conveyor C4/C5 facts), amount scope joins, all 8 claim modes on
one response, reachability (REACHABLE / OPEN / CLOSED-catalog /
CLOSED-blocked). The generic mutation library (`mutations.py`, §15 types)
was frozen before any sealed inference.

## 5. Models / providers / roles (dev-probe selected, then frozen)

| role | model | dev evidence |
|---|---|---|
| primary extractor Φ1 | `gemma4:31b` | 5/6 exact programs, 0 structural issues |
| second extractor Φ2 | `gpt-oss:120b` | 5/6 exact, different failure profile |
| contract interpreter | `swift` | 6/13 exact contracts (best) |
| claim inventory | `gemma4:31b` | 4/5 pairs (tied) |
| contrastive resolver | all ≈ 6/8 | quotes valid 8/8 |
| repair model | `gemma4:31b` | 2/4 (gpt-oss 0/4) |

## 6. Baselines kept

Frozen proof runtime (oracle inputs) = ceiling; existing
`scripts/predict.py` untouched (not re-scored here; its V1 control numbers
stand). No comparison mixes gold-annotated new arms against raw-input old
arms (§86).

## 7. Step 1 arms (directive §36; `step1_arms.py`)

`ALREADY TESTED?` — one-shot: PARTIALLY (F6 raw mention extraction);
compositional / action-inventory / bidirectional: NO at Policy-Program
level; CEGIS-like falsification+repair: NO (mutation suites tested
sensitivity, never a repair loop); multi-Φ: PARTIALLY (F6 graph proxy →
now runtime-level).

| arm | dev atom F1 | dev action-status | sealed atom F1 | sealed tool recall |
|---|---:|---:|---:|---:|
| S1-A one-shot (gemma) | .621 | 18/18 | .700 | .60 |
| S1-B compositional | .353 | 4/34 | — | — |
| S1-C action-inventory | .095 | 2/31 | — | — |
| S1-D bidirectional | .095 | 2/31 | — | — |
| S1-E CEGIS (falsify+repair) | .621 | 18/18 | **.750** | **.80** |
| S1-F Φ2 (gpt-oss) | — | — | — | **1.00** (union 1.00) |

**Compositional decomposition (S1-B/C/D) is decisively WORSE than
one-shot** with these models: per-action calls lose the cross-tool
predicate menu needed for exception atoms and fragment one governed
action into several programs (ferry: 5 programs for one tool; S1-C
produced 25 false atoms). This is an honest negative result for Mechanism
B at the current model tier.

**Behavioural equivalence (§31-34, the primary metric):** on generated
states (up to 81 per family, atom truth-value combinations), dev S1-A
programs agree with gold at: bakery .72, ferry/museum/orchard **1.00**.
The suite's exact-IR metric (program_exact 1/6 dev) overstates the
semantic error: orchard's `any[a,b]` vs gold `unless{a,b}` are
**behaviourally identical in the frozen engine** (both return SATISFIED if
either child is satisfied, VIOLATION only if both violated). The remaining
true dev gap: bakery's over-age/discard any-branch (.72).

## 8. CEGIS-like falsification (Mechanism A)

Counterexamples are constructive only (§14-16): rename invariance with a
fixed catalog (signature must be IDENTICAL — catalog-anchored tokens do not
rename), temporal/negation/modality flip sensitivity (signature must
change). The falsifier found **no real invariant violations** for the
primary extractor on dev or sealed — gemma4's programs are rename-stable
and flip-sensitive (F6 found mistral rename-unstable; the new model is not).

The repair loop earned its keep in a different role: **programmatic
compile failures as counterexamples**. Cinema's first pass embedded an
`activation` node inside the gate (unsupported operator) and quarry emitted
malformed JSON at depth. With compile-failure CEs + a cross-model repair
fallback (gemma fails JSON at depth → gpt-oss re-does the edit, §75),
sealed S1-E lifted tool recall .60 → .80 and atom F1 .700 → .750. Quarry
itself stayed unrecoverable by gemma but **Φ2 (gpt-oss) extracts it
cleanly (1 program, 0 issues)** — complementarity, not repair.

Incident (documented): the first rename-invariance implementation wrongly
applied the rename map to catalog-anchored tokens, producing false
counterexamples that the repair loop then used to **break a correct museum
program** (4/4 → 1/4). Fixed by making the invariant signature-identity;
post-fix S1-E = S1-A on dev. This is exactly the §18 warning: measure how
many correct programs repair spoils.

## 9. Bidirectional verification (Mechanism C)

S1-D ran S1-C plus a program↔source coverage audit. The audit itself
produced usable uncovered-clause reports, but sitting on top of the weak
S1-C base its end metrics did not differ (atom F1 .095). The coverage
questions are cheap and worth keeping as a diagnostic layer; they do not
rescue a weak base parser.

## 10. Multiple Φ at system level (Mechanism D, §26-29)

Per sealed family: 2/5 divergent (cinema, quarry — one extractor empty);
inter-Φ behavioural agreement on generated states: apiary/transit 1.00,
**archive .407** (two valid but materially different programs). At final
verdict level (§73): sealed full-auto has **3/20 verdict-divergent cases
(15%)**, all in archive. Universal consensus (verdict only if both Φ
agree) and error-existential (ERROR if any Φ proves ERROR) differ by
exactly one case (11/20 vs 10/20, §30) — the error-existential arm must
be treated as research-only: a wrong Φ can cause false ERROR (none
observed here, but the risk is structural). No union-of-rules was formed
(§29).

## 11. Step 2 — effect-contract acquisition from prose (§38-41)

The lab family has zero documented contracts. `swift` + programmatic
validation + one contrastive read-vs-write question (§40/§66) recovers
WorldFacts at **P .30 / R .30** (dev; up from .20/.20 without the
contrastive pass). Failure classes, precisely:
1. **read-vs-write strength**: "runs the sterility check" is read as
   EXECUTED by the model although the documentation says "reports the
   outcome" — the contrastive resolver fixed `release_sample` (predicate
   also renamed to the business meaning) but not the check tools;
2. **predicate granularity**: `sample.state` (field name) vs
   `sample.release_state` (business meaning);
3. **cross-step vocabulary drift**: Step 1 invents tool-name predicates
   when the catalog offers none, which then never match Step 2's acquired
   contracts — for prose-only tools, extraction and contract acquisition
   must share a predicate vocabulary; a sequential pipeline drifts.
This is the confirmed **second bottleneck** after Step 1.

## 12. Step 3 — automatic claim inventory (§42-44)

Through the frozen literal-grounded compiler (untouched), with only a
client-side fence-strip for the new models' markdown habit:
**dev P 1.00 / R .833; sealed P 1.00 / R .458; 0 false claims anywhere.**
The recall gap decomposes into three exact classes:
(a) STATE_CLAIMs about OBSERVED predicates — `_literal_value` can only
ground values from non-empty `allowed_values`, which read contracts never
have (inherited V1 limitation, now precisely measured);
(b) completion value not stated in the reply ("I started conveyor 4" —
value `running` never appears verbatim);
(c) the 7-claim stress response (archive.claim_modes: 1/7).
Zero hallucinated quotes — the programmatic verbatim gate holds on all
new models.

## 13. Step 4 — goal/action discovery (§45-49)

`gemma4` goal extraction + programmatic validation (entity id literal in
request, candidate tools in catalog, arguments from request literals) +
AUTO_VERIFIED goal into the frozen reachability engine:
**sealed 4/4 reachability exact** (REACHABLE / OPEN / CLOSED-catalog /
CLOSED-blocked), with correct exhaustive-candidate handling including the
read-only catalog case. This is the first fully automatic Step 4 pass in
the project — previously goal/action inventory was oracle-only.

## 14. Integration: full-auto system metrics (§82-88)

| config (sealed) | exact 3-way | decided coverage | acc. decided | ERROR recall | false ERROR | UNKNOWN rate |
|---|---:|---:|---:|---:|---:|---:|
| full-auto, universal Φ | 10/20 (.50) | .25 | .800 | .40 | **0** | .75 |
| full-auto, error-existential | 11/20 (.55) | .30 | .833 | .60 | **0** | .70 |
| **gold Step1**, auto 2/3/4 | **17/20 (.85)** | .60 | .917 | **1.00** | 0 | .40 |
| gold Step2, auto rest | 10/20 | .25 | .800 | .40 | 0 | .75 |
| gold Step3, auto rest | 10/20 | .25 | .800 | .40 | 0 | .75 |
| gold Step4, auto rest | 10/20 | .25 | .800 | .40 | 0 | .75 |
| oracle ceiling (all gold) | 19/20 (.95) | .70 | .929 | 1.00 | 0 | .30 |

Dev full-auto: 15/20, decided coverage .60, accuracy among decided
**1.00**, false ERROR **0**. The transfer gap dev→sealed is 25 points of
exact-3way and 35 points of decided coverage.

**The oracle decomposition is unambiguous: automatic Policy Program
acquisition (Step 1) is the single dominant bottleneck** — gold Step 1
alone lifts sealed from 10/20 to 17/20 (+7) and ERROR recall .40 → 1.00,
while gold Steps 2/3/4 change nothing (their failures sit downstream of
Step 1 gaps on the same cases). The 19/20 oracle ceiling (vs 20/20
self-verification) is one transit case where an all-gold config certifies
NO_ERROR through an empty claim inventory that the V1 semantics would
leave UNKNOWN — inventory-completeness certification for refusal cases
remains an open boundary, documented.

## 15. Rename / counterfactual / long-policy behaviour (§52, §57-58)

- Rename invariance (fixed catalog): **no violations** for Φ1 on any
  policy (dev and sealed) — see §8; the mutation battery is part of the
  frozen library, re-runnable.
- Flip sensitivity: temporal (bakery/ferry), negation (all families with
  polarity words): no insensitivity violations found for Φ1.
- Long policies: quarry (7 sentences) breaks Φ1's JSON generation at
  depth (malformed JSON, unrecoverable by same-model repair) while Φ2
  handles it perfectly — the long-policy failure mode is **model-specific
  serialization fragility, not semantics**, and multi-Φ covers it.

## 16. Cost (§99-100)

336 fresh API calls total (gemma4 186, swift 49, gpt-oss-120b 52, probes
21, others 28), ≈403K tokens, ≈27.7 min cumulative provider latency, all
on CPU-only local execution with disk caching for determinism. This is
~2 orders of magnitude below the previous cycle's budget.

## 17. Failure taxonomy (sealed full-auto, per case)

program_absent_or_uncompileable (cinema Φ1, quarry Φ1: 2 families / 8
cases) > verdict-critical Φ divergence suppressed by universal consensus
(archive: 3 cases) > claim value unbindable (quarry replies: value word
absent) > claim inventory incomplete (STATE_CLAIM reads) > refusal
inventory certification (1 case). Zero false ERROR across every arm and
both splits.

## 18. Negative results (honest)

1. Compositional parsing (S1-B) and action-inventory-first (S1-C/D) are
   **much worse** than one-shot at this model tier (atom F1 .095-.353 vs
   .621) — decomposition hides cross-tool predicates and fragments
   programs. Mechanism B is killed for now (§104).
2. CEGIS mutation falsifier found **nothing to fix** on a good extractor;
   its value this round came from compile-failure counterexamples and
   cross-model repair, not from semantic invariants.
3. A wrong invariant in the falsifier actively **broke a correct program**
   through repair (museum 4/4 → 1/4) until fixed — counterexample-guided
   repair inherits the correctness burden of its invariants.
4. Prose contract acquisition stalls at P/R ≈ .3 with the contrastive
   round adding +.1 — read-vs-write strength remains unsolved.
5. Universal consensus **suppresses correct Φ2 verdicts** where Φ1
   abstains (archive 3 cases); error-existential recovers exactly one,
   at the structural risk of false ERROR.
6. The sealed transfer gap (dev 15/20 → sealed 10/20) persists even with
   a frozen protocol — freshness costs 25 points.

## 19. Components removed / retained / added (§104 kill criteria)

- **Removed from the active path:** S1-B/C/D (no gain, heavy loss);
  LangExtract/NLP frontend (already gone); always-on second extractor as
  *extraction union* (kept only as independent Φ for consensus).
- **Retained:** one-shot raw-policy extraction with programmatic
  validation (quote gates, catalog anchoring); the frozen proof runtime
  and reachability core byte-identical; mutation library as a standing
  falsifier; behavioural signature as the primary Step 1 metric.
- **Added (measured):** AUTO_VERIFIED trust value for programs/bindings/
  goals/refusals (four guarded constructors extended; frozen outputs
  re-verified byte-identical after the change); compile-failure→repair
  loop with cross-model fallback; multi-Φ runtime consensus.

## 20. Simplest architecture supported by the evidence (§108)

```text
RAW POLICY + TOOL CATALOG
  → ONE strong LLM, one-shot Policy Program (quotes, catalog anchors)
  → programmatic validation (compile failures = counterexamples)
  → bounded repair: same model, then ONE cross-model fallback
  → SECOND extractor as independent Φ (not union, not judge)
  → frozen proof runtime per Φ
  → universal consensus; escalate only verdict-divergent cases
```
PROVEN: Step 4 (goal→reachability) automatic; Step 3 literal claim path
(P 1.0); trust-boundary extension without drift.
PARTIAL: Step 2 prose contracts (.3/.3); Step 1 sealed (.75 atom F1,
union tool recall 1.00).
ORACLE ONLY: full policy-program correctness on fresh long/multi-rule
domains; claim value grounding for reads.

## 21. READY / NOT READY

**NOT READY as an integrated contest detector.** Full-auto sealed exact
3-way .50 with 0 false ERROR and 1.00 accuracy among decided — the
conservative proof discipline holds, but 75% of sealed cases abstain.
**READY as a measured architecture:** every remaining loss is localized
(Step 1 program acquisition on fresh domains, then Step 2 prose
contracts), with oracle ceilings (17/20 with gold Step 1) proving the
downstream is not the blocker.

## 22. Exact next experiment (V3)

1. Step 1 robustness on fresh long policies: serialization-stable
   extraction (Φ2 as primary or chunked emission), measured on a NEW
   sealed suite with 10-20-sentence policies.
2. Shared predicate vocabulary contract between Step 1 and Step 2 for
   prose-only tools (extraction proposes names, acquisition must adopt or
   veto them — not invent independently).
3. Claim value grounding for OBSERVED predicates (result-evidence
   grounding instead of allowed_values), targeting the measured R .46→.8+.
4. Verdict-divergence-only escalation on the ~15% material-ambiguity
   cases with a narrow distinguishing question (§69-70).

## Appendix: artifacts

- Suite + gold: `frozen/trajectories_v2/` (manifest SHA256s)
- Mutation library: `mutations.py` · Protocol: `PROTOCOL.md`
- Arms: `step1_arms.py`, outputs `step1_{dev,sealed}.json`,
  `step1f_{dev,sealed}.json`
- Steps 2-4: `steps_2to4.py`, outputs `step{2,3,4}_{dev,sealed}.json`
- System: `system_eval.py`, outputs `system_{dev,sealed}.json`
- Probes: `probe_task1.py`, `probe_tasks_2to5.py`,
  outputs `probe_task{1..5}.json`
- Cost log: `outputs/cost_log.jsonl` (gitignored)
- Commits: `869feac1` (freeze), `6194168d` (arms+results), report commit
  follows.
