# EVENT NORMALIZATION / CANONICALIZATION — GENERALIZATION PHASE RESEARCH LOG

Branch: `codex/event-normalization-f5-20260929` (from `codex/step1-working-architecture-20260929` @ df4f9508).
Directive: decide whether v10 is a genuinely generalizable Event Normalization architecture
or substantially tuned deterministic guards. NOT restarting the research; v10 is the
starting point and is frozen as V10_FROZEN.

Core question (§0): dev main F P .958 / R 1.000 vs F3 P .636 / R .778 and F4 P .750 /
R .750 — how much of the v10 gain reproduces on fresh unseen data?

Order of trust (§20): F5 sealed / rename / counterfactual > F3/F4 checkpoint > dev F.
Dev main F is NO LONGER the primary criterion.

## Known starting state (from W1 phase; not re-proven)

- v10 = w1_pipe3.py build: hygiene → bnorm → form variants → junk filters →
  unions/consolidation → pair proposal → E3v3 certificate → judge v3 → relation
  gates → DIR/CLS fallbacks → edge consolidation.
- The claim "no fundamental limitation" (W1 report §I) is a HYPOTHESIS to test here,
  not a fact.
- scripts/predict.py frozen; Step 2 frozen; relation stack (E3v3 extractor/judge
  prompts, CE band 0.35, DIR/CLS fallbacks, pl machinery) frozen for this phase.

## H.1–H.4 (carried over from W1 final report §H; written out BEFORE implementation)

### H.1 — Clause-mate pair discipline (DIRECTION on non-canonical connectives)

- Systematic error fixed: judge's q4 direction flips when two connectives separate
  the anchors ('only if … in which case', h_bakery E2-E4; h_press 'only if'); the
  v9 connective-side override uses the FIRST connective between anchors, which
  mis-fires in multi-clause relation texts.
- Why a general mechanism: a relation's evidence clause is syntactically ONE
  clause-pair; requiring both endpoint anchors to be clause-mates (same minimal
  clause segment of the relation_text) is a structural constraint on ANY policy
  language, not a domain word list.
- Expected effect: kills multi-clause bridging extras (F4 i_clinic E4-E2 class),
  fixes direction on nested connectives.
- Regression risk: clause segmentation errors on commas/coordination could split
  true single-clause relations → recall loss on dev.

### H.2 — Multi-clause bridging gate (judge YES across clauses of one sentence)

- Systematic error fixed: endpoints living in DIFFERENT clauses of one sentence,
  connected only through a third clause, get licensed (i_clinic E4-E2; F3
  h_bakery). Same clause-mate mechanism as H.1 applied to licensing (not just
  direction).
- Why general: normative relations are stated within one clause-pair structure;
  cross-clause 'bridging' evidence is exactly the world-plausibility channel the
  certificate is supposed to block.
- Expected effect: removes remaining sealed-suite extras without touching dev
  true edges (their anchors are clause-mates by construction).
- Regression risk: gold edges whose relation_text legitimately spans a
  subordinate + main clause (e.g. 'Do not X before Y') — must segment at
  connective boundaries, not at every comma, or recall dies.

### H.3 — POS-anchored subject/verb split for determiner-subject SVO states

- Systematic error fixed: action_signature treats determiner-initial clauses
  ('the wind sensor reads calm') as NP references (head = last token 'calm');
  the fragment twin ('reads calm') then fails to merge; node structure degrades.
- Why general: uses the stanza POS tagger already shipping with the frontend —
  no new model, no lexicon; a verb-position rule is language structure, not a
  domain word list.
- Expected effect: correct action lemma + subject args for SVO state clauses →
  fragment twins merge; state-gate anchors become structurally findable.
- Regression risk: stanza POS errors on rare words; must keep the old heuristic
  as fallback when no verb is found.

### H.4 — Artifact-noun coverage + determiner-gerund→imperative variant fallback

- Systematic error fixed: frontend/bnorm loses imperative forms on unseen
  domains ('Run the demo' lost; 'the run count' not recognized as artifact
  NP → junk node survives) → node missing its structural anchor.
- Why general: (a) extending the artifact head-noun list from a DEFINED
  derivational class (deverbal nominalization suffixes -tion/-ment/-ing +
  instrument nouns) instead of a fixed 9-word list; (b) a 'the Xing' gerund
  reference generating an 'X' lemma variant is morphology, not a case patch.
- Expected effect: recovers lost mention forms on new domains; kills
  artifact-junk nodes.
- Regression risk: over-broad artifact filter could kill genuine event mentions
  that happen to end in -tion ('the inspection is logged' — must stay: it is
  already guarded by the recording-verb exception).

### Central hypothesis of THIS phase (§25)

v10 conflates two different tasks under "canonicalization":
  A. candidate sanitation / mention normalization (frontend extraction repair);
  B. true event identity / event coreference (SAME concrete occurrence);
  C. relation-level constraints (relation-graph guards).
Optimal architecture may be MODULAR (normalizer → identity classifier → safe
clustering) rather than one build_nodes_v10(). Test by measuring A, B, C
separately (audit) and by building the modular alternative as an arm.

## Phase plan (pre-registered)

1. V10_FROZEN baseline manifest (commit hash, env, prompts, thresholds, caches,
   frontend outputs, scorer, dev/F2/F3/F4 exact results). v10 never changes after.
2. v10 audit: mechanism inventory classified GENERAL STRUCTURAL / LIKELY
   GENERAL / HEURISTIC / LEXICALLY SENSITIVE / POSSIBLY DEV-SPECIFIC; per-guard
   TP-saved / FP-removed / FN-created / false-merge effects via deterministic
   replay of saved outputs (zero LLM) + node-level toggles (zero LLM).
3. A/B/C decomposition: node quality with vs without unions/consolidation;
   edge quality with vs without relation gates (replay).
4. EventMention IR + pairwise identity classifier (SAME_EVENT /
   RELATED_BUT_DIFFERENT / DIFFERENT_EVENT / AMBIGUOUS) with arms A–I and
   feature ablation; candidate generation analysis; clustering comparison.
5. External ECR baselines actually run (SECURE / other) or documented blockers.
6. H.1–H.4 as separate arms on old suites only (dev + F2/F3/F4 as checkpoints);
   compose v11 candidate by causal-effect evidence, NOT by F5.
7. F5 sealed suite: 15–20 policies, ~1/3 known hard mechanisms, ~1/3
   recombinations/counterfactuals, ~1/3 genuinely new constructions; gold
   mentions/clusters/pairs/graph; manifest SHA; committed BEFORE any inference.
8. Single F5 inference round: v10, v11, identity arms, modular arm, external
   baselines; oracle decomposition; rename invariance; failure taxonomy.
9. Final report EVENT_NORMALIZATION_GENERALIZATION_2026-09-29.md.

## D1. V10_FROZEN (2026-09-29)

- commit df4f9508 (branch codex/step1-working-architecture-20260929), env:
  Vast RTX 3090, /workspace/guardian/venv, ministral-14b-latest t=0,
  bge-reranker-base (cuda, batch 32, max_len 512), CE_BAND=0.35.
- Frontend arm LLM_SG (schema-guided, frozen prompts in event_ie_frontends_v1),
  W1_HYG hygiene outputs, W1_BNORM_383f5df9 boundary-normalizer outputs (all
  cached; the normalizer cache dir is picked by mtime, latest = 383f5df9).
- Results (frozen, from w1_score*.json):
  main F:  P .958 R 1.000 correct 23 extra 1 missing 0 exact 14/15
  F2:      P .600 R .750 (checkpoint, validation-only)
  F3 (v8): P .636 R .778 correct 7 extra 4 missing 2 exact 3/5
  F4:      P .750 R .750 correct 6 extra 2 missing 2 exact 2/5
  cert-units regression: 17/22.
- v10 mechanisms are enumerated in the audit (en_audit.py) and classified in
  the report. After this manifest, v10 code/params are IMMUTABLE; every variant
  is an experimental arm.

## D2. v10 audit results (2026-09-29, deterministic replay, zero LLM)

**Faithfulness**: build_nodes_toggle(all-on) reproduces saved W1_DOWN10 nodes
byte-identically on main F, F2, F3. F4=False — expected: the original F4
bnorm intermediates were lost; reconstruction used fresh (temperature-0) calls.
F4 numbers below are a re-instantiated v10, not the sealed bytes (the sealed
EDGE numbers in part2 use the original saved outputs; node metrics use the
re-instantiated chain). Reproducibility caveat logged.

### A/B decomposition (node level; A = sanitation only, B = + identity)

| suite | nodes A / A+B | junk A / A+B | conll_f A / A+B | false merges (A+B) |
|-------|--------------|--------------|-----------------|--------------------|
| main F | 86 / 59 | 12 / 2 | .295 / .776 | 0 |
| F2 | 27 / 18 | 4 / 1 | .401 / .747 | 0 |
| F3 | 28 / 20 | 5 / 1 | .138 / .675 | 0 |
| F4 | 29 / 20 | 6 / 3 | .612 / .923 | 0 |

- cluster_recall is IDENTICAL with and without B (.939 main / 1.0 F2 /
  .933 F3/F4): **sanitation alone finds the mentions; identity does not add
  coverage — it consolidates.**
- B's contribution = CoNLL +.31..+.54, junk nodes -60..-83%, node precision
  +.06..+.14, with ZERO false merges on all four suites.
- Residual identity misses: false_split_cids 7 (main), 2 (F2), 3 (F3), 0 (F4).

### C decomposition (edge level; guard replay on saved pair logs)

| suite | base P / R | all-gates-off P / R | coordination | no-connective | cross-sentence |
|-------|-----------|--------------------|--------------|---------------|----------------|
| main | .958 / 1.000 | .605 / 1.000 | 7 non-gold killed, 0 gold | 4 / 0 | 3 / **2 gold killed** |
| F2 | .700 / .875 | .500 / .875 | 2 / 0 | 0 / 0 | 1 / 0 |
| F3 | .778 / .778 | .636 / .778 | 2 / 0 | 0 / 0 | 0 / 0 |
| F4 | .778 / .875 | .636 / .875 | 1 / 0 | 1 / 0 | 1 / 0 |

- Relation guards deliver ~.35 P on dev but only ~.14 P on sealed suites —
  the guards mostly fire on dev-class errors; sealed extra edges pass them.
- cross_sentence_gate kills 2 gold edges on main (recovered via other pairs
  in base scoring) — it is the riskiest guard.
- Same-action pair suppression (part 3): 13 suppressed pairs total across 4
  suites, exactly 1 gold edge lost (g_film E2-E3 'Digitize the reel' vs
  'Storage of the master'). Suppression is nearly free.

### Mechanism classification (manual inventory of w1_pipe3.py)

GENERAL STRUCTURAL (language-level, domain-free):
- verbatim grounding + case-tolerant span location
- verification ladder (a/b/c/d) for certificates
- subject re-attachment (extend left to clause subject, stop at connective)
- trailing-clause spawning (connective+state inside overlong span)
- clause repair to minimal covering span
- connective-side direction override (subordinate-clause antecedent rule)
- object-position vs subject-position containment distinction
- coordination gate (and/or between anchors without gating connective)
- same-sentence anchor rule (relation clause is single-sentence)
- adjacent subject-predicate attachment
- CE-gating of positional verification paths
- action_signature modal-subject existential rule
- 'again' repetition veto (occurrence-distinctness marker)

LIKELY GENERAL (morphology/POS-level, minor lexical lists):
- _lemma_match / _norm_lemma derivational morphology (inspect~inspection)
- form VARIANTS (article / predicate-only / negation-strip)
- action-lemma + non-numeric argument overlap merge criterion
- copula/state/ref form-kind triage
- determiner-initial NP vs verb-initial clause distinction

HEURISTIC (fixed word lists, coverage-limited):
- ARTIFACT_HEAD noun list (9 nouns) — H.4 extends derivationally
- RECORDING_PRED participle list (logged/filed/recorded/…)
- OP_ON_MENTION verb set (20 verbs)
- junk-filter regexes: TAXONOMY_PRED, DEONTIC_ADJ, IDENTITY_NEG,
  COMM_VERB, MODAL_COPULA
- STOP list / CONNECTIVE_FORM enumeration

POSSIBLY DEV-SPECIFIC (tuned on seen failures):
- same-sentence gate threshold behavior (killed 2 gold edges on main)
- no-connective gate connective list ('only at' exclusion was dev-driven)
- connective-side override 'before'-negation inversion rule
- substring merge subject-position guard details
- 6-word subject-extension cap

v10 verdict from the audit: the win decomposes into
  A sanitation (recall .93-1.0, generalizes — F3/F4 same level as dev),
  B consolidation (precision at nodes, zero false merges, generalizes),
  C relation guards (dev-heavy precision, weakest transfer of the three).
