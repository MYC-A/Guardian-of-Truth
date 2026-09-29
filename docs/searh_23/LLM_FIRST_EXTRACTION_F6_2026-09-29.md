# LLM-FIRST EXTRACTION — F6 SEALED ROUND (Level F6)

**Branch:** `codex/llm-first-extraction-f6-20260929` (base:
`codex/event-normalization-f5-20260929` @ 27a21bc5) · **Date:** 2026-09-29
**Directive question:** is an NLP-first frontend needed at all, or should a
strong LLM read the RAW POLICY and extract the semantic structure directly,
with NLP demoted to an independent coverage/audit signal?
**Order of trust:** F6 sealed / rename / counterfactual > F5 > F3/F4 > dev.
F5 results were known before this round (v10 on F5: P .406 / R .361);
nothing in this round was tuned on F6 after inference.

---

## 1. Frozen protocol (anti-leakage, directive §18)

Workflow actually executed, in order:

1. **F6 sealed suite frozen and committed BEFORE any inference** (commit
   375c5e41): 24 policies, 221 mentions, 97 canonical events, 43 gold
   edges, 293 gold pairs (SAME 37 / RELATED 142 / DIFFERENT 114), 6 CF
   twins, 6 renamed cases. Manifest sha256(cases) `3a5a019c32b826d5…`.
   Deterministic full-format conversion committed next (`level_f6_cases.json`
   sha `737a96028413…`, `level_f6r` sha `eb23e68bc6a5…`).
2. **Arms/prompts frozen and committed BEFORE any inference** (commit
   ec928cb8): ARM A/A2 raw-extractor prompts, ARM B strict-grounding
   variant, ARM D narrow resolver, ARM F judge, model registry, the raw
   runner with programmatic quote verification, the local Mistral client
   (byte-compatible request semantics with the frozen pl_common.Mistral).
3. Single inference round: raw arms → audit → stack oracles → identity →
   escalation/agreement/verdict → rename → LangExtract. Post-hoc
   diagnostics are labeled post-hoc where they are (§5 hyb arm) and the
   confirmatory round for any fix is F7.

## 2. F6 composition

Three groups of 8 policies (all new formulations; no F3/F4/F5 sentence
reused; domains all new relative to every previous suite):

- **M — mention-form mechanics:** active→passive→nominalization chains,
  result states + coordinated state gates, subject-nominalization ==
  imperative, check-vs-state readout, same object under three predicates,
  same predicate on two objects, embedded verify over a recording passive
  (triple nesting), irregular morphology (sweep→swept) with modal passives.
- **L — licensing:** forbidden-until negation, only-if + unless over the
  same state, OR alternatives with numeric thresholds, temporal windows
  ("within six hours of collection"), coordinated state gates,
  gerund+pronoun references + a descriptive non-policy sentence,
  same-predicate-different-object roads, may-permission + artifact-subject
  recording passive.
- **S — reference & identity stress:** quoted/reported action (embedded
  clause shares the cid with the direct imperative), "this step" anaphora +
  repetition, cross-sentence passive-facet chains, hypothetical
  conditionals + damage reporting, confirmation with a synonym-voice facet
  ("Broadcast" / "was transmitted"), entity IDs that matter (fish 44/45),
  check-of-state vs the action producing that state, repetition with
  ordinal completion states.

Gold conventions (documented in `f6_manifest.json`; three deliberate
changes vs F5): (i) nested CHECK/RECORD/COMMUNICATION clauses keep BOTH
the outer mention and the embedded clause (embeds field); (ii) recording
clauses are first-class RECORD events with their own cid; (iii)
outcome/failure/cancellation states get their own cid. New sem taxonomy:
ACTION / CHECK / STATE / RECORD / COMMUNICATION / REFERENCE_TO_EVENT /
OTHER. 6 CF twins (crate-51/52, cleanse, logged, grind, gatecheck,
replace — the directive's own examples included verbatim where given).

## 3. Models / endpoints actually used

- **ministral-14b-latest** (api.mistral.ai, temperature 0, json_object,
  sha-keyed disk cache, 429-retry) — primary raw extractor (ARM A/B).
- **codestral-latest** (same API, the documented strong control from the
  operation/check phase) — second independent extractor (A2), escalation
  resolver (ARM D), type-judge (ARM F).
- **bge-reranker-base + bge-base-en-v1.5 + stanza 1.14 (en)** — local CPU
  (the frozen relation stack, identity support, and the NLP audit).
- **Granite:** NOT RUN — documented blocker. Historical configuration
  located (granite-guardian-3.3-8b @ `/mnt/data/guardian/models/
  granite-guardian-3.3-8b-b3421eda` via `experiments/full21/
  run_granite_modes.py`; gateway README also lists granite-guardian-4.1-8b
  @ `agent-workspace/superz_models/`). The remote GPU gateway answered
  `health: ok` but `/jobs` returned **503 for the entire session**
  (probed repeatedly over ~4 hours). No arbitrary other Granite was
  downloaded or substituted (directive §5). Granite-as-raw-extractor is
  the single F6 arm that remains unmeasured → F7.
- **LangExtract 1.7** (pip) with the OpenAI provider pointed at the
  Mistral endpoint (same model as ARM A — isolates the machinery).

## 4. Exact prompts

Frozen in `experiments/searh_23/llm_first_f6/en_f6_prompts.py` (committed
before inference). ARM A: raw policy + tool catalog + strict JSON schema,
one grounding line ("quote = exact substring, copied character by
character"), explicit instruction to return nested content as separate
mentions and NOT to merge mentions. ARM B: the same plus the four hard
grounding rules of directive §6 spelled out. ARM D resolver and ARM F
judge: narrow single-question prompts (YES/NO/UNKNOWN; A/B/BOTH_POSSIBLE/
UNKNOWN + exact evidence). Identity judge: the F5 F4way SYSTEM prompt
byte-identical.

## 5. Arms

| arm | what it is | status |
|---|---|---|
| A / A2 | raw LLM extractor, ministral / codestral | run (24+6+12 policies each) |
| Ag | raw Granite extractor | **blocked** (gateway 503) |
| B | raw + strict source-grounding prompt | run (both models) |
| C | A + NLP coverage audit (stanza anchors) | run |
| D | selective escalation (narrow resolver on 61 spots) | run |
| E | two independent extractors, agreement analysis | run |
| F | narrow judge over 53 type disputes | run |
| G | calibrated uncertainty / selective prediction | run |
| H | multiple interpretations Φ (mistral vs codestral parses) | run |
| I | verdict-aware escalation (edge-set agreement) | run |
| — | v10 NLP-first chain on F6 (LLM_SG frontend + hygiene + bnorm + consolidation + stack) | run |
| — | hyb: raw + frozen connective-strip + compatible_nodes merge (**post-hoc composition**, §5 honesty note) | run, labeled post-hoc |
| — | **rawsan**: raw LLM mentions as the candidate source for the FULL frozen sanitation chain (hygiene → bnorm → build_nodes_v3 → stack); rawsan2 = the codestral variant | run |

## 6. Mention metrics (129 gold event mentions over 24 policies)

| arm | pred | coverage (overlap) | strict IoU≥.5 | exact P / R / F1 | junk | hallucinated |
|---|---|---|---|---|---|---|
| mistral A | 159 | **1.000** | .721 | .421 / .519 / .465 | 2 | **0** |
| mistral B | 189 | 1.000 | .667 | .354 / .519 / .421 | 1 | 0 |
| codestral A | 122 | .992 | .581 | .434 / .411 / .422 | 0 | 0 |
| codestral B | 119 | .992 | .543 | .353 / .326 / .339 | 0 | 0 |
| LLM_SG frontend (v10 chain source) | 246 | .992 | — | .309 / .589 / — | 33 | 0 |
| LangExtract (8 cases, same model as A) | 45 | .976 | — | 33 exact | 5 | 0 |

**Q1 answer:** raw extraction is decisively better than the NLP-first
frontend as a candidate source: full semantic coverage (1.0 vs .768
cluster recall of the F5 A-layer), ~zero junk (2 vs 14), **zero
hallucinated quotes across every arm and every policy** (programmatic
verbatim verification), and it needs no NLP machinery to get there. The
exact-span gap (F1 .47) is a boundary-convention difference (adjuncts
included), not missing content. **Q2:** codestral is comparable
(coverage .992, zero junk) but less complete per-policy.

## 7. Typing metrics (strict-IoU matched pairs, gold sem taxonomy)

mistral A per-class recall: ACTION 31/35, REFERENCE_TO_EVENT 12/13,
STATE 14/26, RECORD 5/7, CHECK 3/8, COMMUNICATION 2/4. Largest
confusions: STATE→CHECK (6), CHECK→ACTION (5), STATE→ACTION (4) —
exactly the directive's predicted hard classes (action vs resulting
state; check-of-state vs the action). codestral similar (ACTION 29/31,
CHECK 3/6, COMMUNICATION 0/3).

## 8. NLP coverage audit (ARM C)

131 structural anchors (stanza: non-aux verbs, lemma-matching deverbal
nouns, derivational nominalizations, attached participulates). For
mistral A there were **0 uncovered anchors and 0 missed gold event
mentions — the watchdog has nothing to catch** (audit P/R undefined /
0.0 by empty positive set). codestral A: 1 missed gold mention, detected
by the audit (detection recall 1.0) at 3 uncovered anchors → anchor
precision .333. **Q3–Q5 answer:** on short policies the NLP audit is
correctly ignored: real-miss detection ≈ 1.0 but the base miss rate is
~0–1%, so the signal almost never fires; when it fires it is ~1:2
precise. Its value should be re-measured on long policies (F7), where
misses actually exist.

## 9. Disagreement analysis (ARM E)

Mention agreement .847 (119 one-to-one matches, mean IoU .912), type
agreement on matched .832. gold missed: mistral 0, codestral 1.
Agreement-as-uncertainty: agreed mentions on-gold-event 96.6% vs
disagreed 81.4% — informative but weak, because both extractors are
individually near ceiling. **Q9 answer:** disagreement is a usable
uncertainty signal but buys little here.

## 10. Selective escalation (ARM D) vs always-two (directive §8)

61 escalation spots (8 keep-or-drop content spots + 53 type disputes).
Resolver (codestral, narrow questions): veto precision 1.0, veto recall
.33 — its vetoes were all correct but conservative. Mention-level:
mistral alone precision-proxy .925 / coverage 1.0; selective .929;
union-of-both .947 but with 281 mentions (77% duplicates). Cost:
selective = 61 narrow calls; always-two = a full second extraction per
policy. **Q7/Q8 answer:** on F6, always-two-LLMs buys almost nothing
that selective doesn't, and selective itself buys almost nothing over
ONE strong extractor. The second model is not needed for coverage.

## 11. Calibration / risk-coverage (ARM G)

Observable signals only (agreement, exact-source support, NLP anchor
coverage, type-disagreement). No logprobs are exposed by this API tier;
no method named "Jeff" exists anywhere in the repository (searched) —
the arm is honestly named calibrated uncertainty / selective prediction.
Base per-mention accuracy .925. Risk-coverage: at 56.6% coverage
accuracy .956; at 93.1% coverage .932 — a nearly flat curve.
Signal separation: agreed .94 vs disagreed .625; anchor-covered .955 vs
uncovered .76. **Q10 answer:** the signals are individually informative
but the extractor is already accurate enough that selective prediction
adds ≤3 points at halved coverage — not a usable gate on F6-class data.

## 12. Φ analysis (ARM H)

Two independent interpretations per policy (mistral / codestral parses):
**10/24 policies have divergent node interpretations** (Φ > 1 in any
meaningful sense); 14/24 produce identical node-span sets. Of the 10
divergent, carrying both through the FULL frozen chain (rawsan vs
rawsan2): 4 collapse to the same licensed graph, 6 remain
verdict-critical (§13). Multiple-Φ storage is cheap and safe; it matters
for ~25% of policies.

## 13. Verdict-sensitive ambiguity (ARM I)

Verdict proxy (honest scope note: F6 has no execution traces, so the
"final Guardian verdict" is proxied by the licensed gold-cid edge set —
the input any verdict is computed from; a trace-level experiment belongs
to F7): **18/24 policies verdict-equivalent, 6/24 verdict-critical**
(m_tram, l_deicing, l_algae, l_snowroute, l_roastery, s_herbarium).
Edge recall: single interpretation .581, union of both .651 — the
escalation upside on the 6 critical cases is +.07 total recall. The
directive's cascade (evaluate both Φ; escalate only when the verdict
differs) would skip 75% of policies entirely. **Q11 answer:** 25% of
policies carry interpretation ambiguity that changes the licensed graph.

## 14. Rename / counterfactual results

**Rename** (6 cases, entity nouns/IDs renamed, structure preserved):
codestral **6/6 structural identity** (100% span alignment through the
rename map); mistral 1/6 (.676 span alignment — drops/adds mentions on
renamed text; worst on the entity-ID case). Raw extraction rename
stability is model-dependent. **Counterfactual twins** (F4way identity
judge on focus pairs): 2/6 both-sides-correct (cf_logged — action vs
recording now CORRECT on both sides, cf_grind — same-predicate-different-
object + irregular passive + substring trap). Persistent failures: the
**check-embedding class** (cf_cleanse_b: "Verify that the vessel was
cleaned" still merged with the cleaned state — the same failure every
F5 system had) and **prescribed-vs-performed** (cf_replace_a: the
standing rule merged with a reported past occurrence). Entity-ID binding
(cf_crate) and gate-action-vs-check (cf_gatecheck) decided correctly on
the b-side, boundary-confused on the a-side.

## 15. Cost / latency

- Raw extraction: 108 fresh API calls ≈ 1.09M tokens total, 934 s
  wall-clock (all four raw arms + CF + renamed; heavy cache reuse).
- Relation stack: 1,094 certificate/judge/fallback responses (shared
  cache across the 7 stack arms); identity 605; escalation 112.
- GPU-free: everything ran on CPU (bge-reranker CPU ≈ 40 s/case for the
  stack arms) + the Mistral API. Full F6 round ≈ 1.9k LLM calls.
- ARM D selective: 61 narrow calls vs 24 full second extractions.

## 16. Oracle decomposition (directive §17; strict W1 graph semantics)

| arm | P | R | F1 | exact | junk | cluster recall | meaning |
|---|---|---|---|---|---|---|---|
| **Oracle 1** gold nodes + frozen stack | **.892** | **.767** | .825 | 13/24 | 0 | .969 | stack ceiling on F6 (transfers; F5 oracleA was .800/.667) |
| **Oracle 2** raw mentions + GOLD identity | .350 | .163 | .222 | 3/24 | 12 | .856 | raw spans (connective prefixes, wide boundaries) damage the stack even with perfect identity |
| **Oracle 3** raw mentions, unmerged | .162 | .140 | .150 | 1/24 | 12 | .856 | naive raw→stack: duplicates flood the pair proposal |
| **Oracle 4** raw + FULL frozen sanitation (**rawsan**) | **.800** | **.558** | .658 | 10/24 | 3 | .866 | the LLM-first hybrid: best real pipeline measured |
| rawsan2 (codestral variant) | .800 | .558 | .658 | 10/24 | 2 | .907 | model-agnostic at this level |
| v10 NLP-first chain on F6 | .697 | .535 | .605 | 9/24 | 3 | .887 | the old architecture, same suite |

**Oracle 4 beats the NLP-first chain by +.10 P / +.02 R / +.05 F1 and
+1 exact graph, with the same frozen downstream.** The gain is entirely
in the candidate source: the raw extractor's coverage (1.0) vs the
frontend's (.992 with 33 junk and 246 candidates needing aggressive
sanitation). The two models (mistral / codestral) produce IDENTICAL
graph scores through the same chain — the architecture is
extractor-agnostic at this quality tier.

## 17. Failure taxonomy (rawsan, the best arm)

node_missing_cid 13 > contaminated_endpoint_edges 3 > node_junk 3 >
unsupported_edge 2 > duplicate 1. The dominant loss is still the node
layer: the frozen bnorm+consolidation drops ~13% of gold cids that the
raw extractor DID cover (bnorm DROP 19 + dedupe 29 of 159 candidates).
The v10 chain shows the same shape (missing 11, junk 3, contaminated 8).
Exactly as in F5, recall is lost before the relation stack fires — but
now the loss is in SANITATION, not extraction.

## 18. Negative results (honest)

1. **Naive LLM-first fails at the graph level.** Feeding raw mentions
   straight into the frozen stack (oracle 3) is the WORST measured
   system (P .162): unmerged duplicates + connective-prefixed spans
   ("if the range is clear") break pair proposal and gating. The
   directive's suspicion was right to demand the test and wrong to
   assume the win.
2. **Even GOLD identity cannot rescue raw spans** (oracle 2, P .350) —
   boundary hygiene, not identity, is what raw mentions lack.
3. **The strict-grounding prompt (ARM B) made extraction WORSE**, not
   better: more mentions (189 vs 159), lower exact precision (.354 vs
   .421), same recall. The constraint list induced verbosity, not
   discipline; programmatic verification already enforces what the
   prompt repeats.
4. **The partial hybrid (hyb: connective-strip + compatible_nodes) did
   not work** (P .346): the frozen LEADING_CONNECTIVES regex does not
   cover coordination prefixes ("and the red flag is hoisted") and
   compatible_nodes alone is not a consolidation. Labeled post-hoc and
   superseded by rawsan.
5. **The NLP watchdog has nothing to watch** on short policies (0
   misses to catch for the primary extractor).
6. **The narrow type-judge does not fix typing disputes** (ARM F:
   correct on only .312 of decisive disputes — it mostly rubber-stamps
   extractor 1's typing).
7. **Selective escalation and uncertainty gating buy ≤3 points** at
   mention level because the base accuracy is already .925.
8. **LangExtract adds no measurable value over the raw prompt on the
   same model** (coverage .976 vs 1.0, junk 5 vs 2, alignment equivalent
   to our programmatic check). It did not recover anything (nothing was
   missed) and its built-in alignment matched our zero-hallucination
   verification.
9. **mistral extraction is rename-unstable** (1/6 structural identity
   vs codestral 6/6).

## 19. The simplest architecture supported by the evidence

```text
RAW POLICY
  → ONE strong LLM, flat recall-oriented extraction prompt,
    verbatim quotes, nested content as separate mentions, NO merging
    (zero hallucinated quotes; coverage 1.0; junk ≈ 0)
  → frozen deterministic hygiene (connective strip)
  → frozen LLM boundary normalization (bnorm)
  → frozen deterministic consolidation (build_nodes_v3)
  → frozen relation stack (certificate → judge → gates)
```

This is exactly the current pipeline with the **candidate generator
swapped for the raw LLM extractor** — measured at P .800 / R .558 /
F1 .658 (best real pipeline this project has produced on a sealed
suite; the previous best was F4's v10 at P .750 / R .750 on 5 policies,
and v10-on-F5 collapsed to .406/.361). Everything beyond this — second
extractor, judge, uncertainty gates, NLP watchdog, LangExtract — adds
complexity without measurable gain on F6-class data, with one
exception: **verdict-aware escalation on the ~25% of policies where
two interpretations produce different licensed graphs** (potential
+.07 edge recall, measurable, cheap).

## 20. What should be removed from the current pipeline

- **The NLP candidate-generation role of the frontend** (LLM_SG's typed
  mention-graph proposal): replace its output with the raw extractor's
  (rawsan swap). Keep the sanitation stages that follow it.
- **Always-on second-model / judge / uncertainty layers:** not supported
  by any measured gain at this data scale.
- Keep (all still load-bearing): deterministic connective hygiene, bnorm
  boundary normalization, deterministic consolidation, the relation
  stack, and a **thin verdict-aware escalation hook** for
  interpretation-divergent policies.
- Fix next (F7 candidates, NOT tuned on F6): bnorm over-dropping (13
  gold cids lost during sanitation of a 1.0-coverage candidate set);
  check-embedding identity (cf_cleanse); prescribed-vs-performed
  distinction (cf_replace); "and/or" prefix stripping; rename stability
  of the primary extractor.

## 21. READY / NOT READY conclusion

**NOT READY as a final architecture; READY as a validated direction.**
The LLM-first hypothesis is **confirmed at the mention level and
confirmed end-to-end only in the hybrid form** (raw LLM + frozen
sanitation), which is now the best measured pipeline and strictly
simpler upstream than the current frontend. The naive strong form
(raw LLM → downstream directly) is **refuted** (P .162). Granite-as-
raw-extractor was never measured (gateway 503 all session — the one
open model question, → F7). Confirmatory items for F7: long-policy
behavior (where the NLP watchdog and uncertainty gates could matter),
trace-level verdict sensitivity, the four fix classes above, and a
second sealed suite to confirm rawsan without any F6-informed choice.

---

## Appendix: file map

- Suite + gold: `experiments/searh_23/llm_first_f6/f6_frozen/` (7 files,
  manifest sha 3a5a019c…)
- Prompts: `en_f6_prompts.py` (frozen pre-inference)
- Raw arms: `outputs/raw/{mistral,codestral}/{A,B}/` (+CF, +renamed)
- Audit: `outputs/audit/`; identity: `outputs/identity/`;
  escalation: `outputs/escalate/`; scores: `outputs/score/`
- Stack arms: `outputs/stack/f6_{oracle1,oracle2_mistralA,
  oracle3_mistralA,v10,hyb_mistralA,rawsan,rawsan2}/`
- rawsan chain intermediates: `event_ie_frontends_v1/outputs/RAWA{,2}`,
  `step1_working_v1/outputs/W1_HYG/RAWA{,2}`,
  `step1_working_v1/outputs/W1_BNORM_383f5df9/RAWA{,2}`
- Research log: `LLM_FIRST_F6_RESEARCH_LOG.md` (this directory)
