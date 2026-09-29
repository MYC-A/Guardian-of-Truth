# STEP 1 WORKING ARCHITECTURE RESEARCH — 2026-09-29

Branch: `codex/step1-working-architecture-20260929` (from `codex/step1-ready-ie-frontends-20260928` @ 092896d7).
Goal (directive): push Step 1 (Policy Understanding) to a WORKING state through iterative
research loops - or prove a fundamental limitation that no frontend patch can hide.
Frozen: `scripts/predict.py`, Step 2. Old Level E/F/F2 suites used for diagnosis/dev/
regression only; every generalization claim below comes from suites frozen BEFORE their
inference.

Headline: **the working architecture exists and validates on fresh sealed domains.**
Strict edge quality on the dev suite went P .167 / R .174 / exact 2/15 (frozen
previous-phase pipeline) to **P .958 / R 1.000 / exact 14/15**; on two freshly-frozen
sealed suites (new domains, new authors, never used for tuning) the SAME architecture
scores **P .750 / R .750 (F4, 6/8 gold edges, exact 2/5)** and **P .636 / R .778 (F3,
7/9 gold edges, exact 3/5, v8 variant)** - against the previous phase's sealed collapse
of P .000 / R .000 (0/8 correct, 18 extra). The gap between dev and sealed (~0.2 P) is
fully attributed to identifiable residual mechanism classes (section H), each with a
concrete next fix - none of them fundamental.

---

## A. Architecture evolution (what changed and why)

The starting point was the previous phase's verdict: *good verifier (E3 endpoint
certificate) + bad endpoints = bad graph* - certificates can honestly prove relations
between garbage semantic objects. The whole cycle was therefore about NODE QUALITY
CONTROL and the CERTIFICATE'S DETERMINISTIC DISCIPLINE, in that order.

Iteration record (dev = main F, 15 cases, strict scorer, frozen semantics):

| arm | P | R | correct | extra | missing | exact | what was learned |
|-----|---|---|---------|-------|---------|-------|------------------|
| baseline DOWN_LLM_SG_E3 | .167 | .174 | 4 | 20 | 19 | 2/15 | frozen starting state |
| W1_DOWN3 (v3) | .270 | .739 | 17 | 46 | 6 | 1/15 | recall is solvable (ladder verifier + channels); precision now the problem |
| W1_DOWN4 (v4) | .423 | .478 | 11 | 15 | 12 | 4/15 | consolidation kills junk but naive bag-of-lemmas over-merges (Feed~Weigh) |
| W1_DOWN5 (v5) | .412 | .913 | 21 | 30 | 2 | 5/15 | action-lemma identity fixes over-merge; recall nearly solved |
| W1_DOWN6 (v6) | .618 | .913 | 21 | 13 | 2 | 6/15 | same-action suppression + coordination gate + deontic attach |
| W1_DOWN7 (v7) | .778 | .913 | 21 | 6 | 2 | 11/15 | effective-endpoint dedup, no-connective gate, aux fragments |
| W1_DOWN8 (v8) | .808 | .913 | 21 | 5 | 2 | 12/15 | tightened connective gate, object-containment |
| W1_DOWN9 (v9) | .958 | 1.000 | 23 | 1 | 0 | 14/15 | SAME-SENTENCE anchor rule + connective-side DIRECTION override |
| W1_DOWN10 (v10) | .958 | 1.000 | 23 | 1 | 0 | 14/15 | + recording-state containment; frozen as final |

Every step was pre-registered in `STEP1_RESEARCH_LOG.md` and committed before its
inference run (commit chain 54b83425 → 580afbc1 → 486839d3 → c8c58ba4 → dce04fd0 →
4c430563).

## B. Hypotheses, probes and negative results

- **H1 (PROMOTED)** - "boundary damage + verifier anchor mismatch is the main recall
  killer". CONFIRMED and generalized: the fix was not one repair but a whole
  deterministic layer (form variants, subject re-attachment, trailing-clause spawning,
  ladder verification, relation-level gates). Full mechanism list in E.
- **H2 (PARTIALLY ABSORBED)** - "a NodeCertificate (LLM proposes span+type, deterministic
  gates verify) is needed for node quality". The certified-node vision was implemented
  DETERMINISTICALLY instead: action-lemma identity, asymmetric state-of-act
  compatibility, recording/operation-on-mention guards, junk filters. No LLM typing
  call survived in the final architecture - the deterministic layer proved sufficient
  on dev/sealed for the classes observed. An LLM contrastive EVENT-vs-STATE certificate
  remains attractive for the residual classes (H.3) but was not needed to hit the
  targets.
- **H4 (PROMOTED, deterministic core)** - "mention-level relations before
  canonicalization". Implemented as: never merge across recording verbs or
  operation-on-mention clauses; merge act/gerund/passive-state facets of the SAME
  action only (action-lemma + argument overlap, asymmetric state-of-act exception,
  'again' repetition veto); consolidate licensed edges by effective-endpoint
  compatibility. The naive version (frontend SAME_EVENT/REFERENCE_OF links) was
  measured as actively harmful (f_bottling merged cap+label+pack+filler into one node;
  f_textile merged dye+rinse+fix) - frontend relation links are now PROPOSALS vetted by
  deterministic action compatibility.
- **H5 (multi-candidate parses)** - NOT needed at this suite scale: the single-parse
  certificate + gates reached target; K-parse diversity is the designated next lever
  for the multi-clause bridging class (H.2).
- **Negative results worth keeping:**
  - the FIRST v3 verifier (any-form-only) scored **0/22** on the frozen adversarial
    certificate units - single-form endpoints REQUIRE the v1 positional
    extractor-anchor path; the fix was the verification LADDER (any sufficient path),
    which then scored **17/22 ≥ the E3 baseline 15/22** (all 9 positives SUPPORTED;
    3 negatives missed through the judge);
  - bag-of-lemma consolidation over-merges argument-sharing different actions
    (Feed/Weigh the red pandas share {red, pandas} - not the same event);
  - keeping overlong ORIGINAL spans as node forms poisons identity lemmas AND creates
    MIXED nodes + self-pairs when they embed foreign states - originals are anchors,
    never identity evidence;
  - CE (bge-reranker) is a relevance model, not a discourse-relation model: it scored
    0.057 on a gold state-gated pair and 0.99 on a junk pair; it is only safe as ONE
    proposal channel among deterministic ones, and as a CE-gate for the positional
    verification path.

## C. Cheap probes (Tier 0/1 discipline)

- Deterministic loss-budget replay (w1_diag.py) on saved outputs - zero LLM calls -
  attributed 70% of recall loss and 75% of extra edges to node quality BEFORE any new
  mechanism was built.
- Certificate replay from the LLM cache (w1_replay.py) traced all 5 F2 missing edges
  to 8 concrete failure mechanisms (STEP1_RESEARCH_LOG.md D1) with zero new calls.
- Local build_nodes_v3() runs (no GPU/LLM) validated node structure on all 20 cases of
  both suites before EVERY server inference round; two over-merge regressions were
  caught and fixed locally before ever spending a call.
- 22 frozen adversarial certificate units re-run as a regression gate at every prompt
  change (17/22 final).

## D. Literature / prior systems (position, not re-searched this cycle)

Ready IE systems were ruled out as frontends in the previous phase (OneKE/UIE/GLiNER
span-extractive misses clause-level events; OmniEvent checkpoints unavailable;
OpenNRE zero discrimination; AMR useful only as a structural witness). This cycle's
mechanisms are instead built on classical, verifiable NLP structure: deterministic
morphology (Porter-style normalization + nominalization stripping), clause-level
syntax (subject/predicate positions, connective sides, coordination structure), and
certificates in the spirit of proof-carrying code (extractive quotes + deterministic
grounding + an independent judge). No new external system was adopted; the design
follows the directive's SEMANTIC PROPOSAL → SOURCE-BACKED PROOF OBLIGATION →
DETERMINISTIC/STRUCTURAL CHECK → TRUSTED OBJECT principle throughout.

## E. Final architecture (v10, w1_pipe3.py)

```
LLM_SG schema-guided frontend (frozen, Mistral ministral-14b, temperature 0)
  → deterministic hygiene        (verbatim grounding, leading-connective strip)
  → LLM boundary normalizer      (KEEP/NORMALIZE/SPLIT/DROP, extractive-subspan
                                  discipline; deterministic keep-override restores
                                  indicative-copula state clauses the LLM drops)
  → deterministic node construction
      • form VARIANTS: original / article / predicate-only / subject-extended
        (copula-, modal-, aux-initial) / negation-strip; all case-tolerant-verbatim
      • trailing-clause SPAWNING: overlong originals that embed a foreign
        connective+state spawn that state as its own candidate instead of
        contaminating the act node's identity
      • junk filters: taxonomy predication ('X is a document'), deontic modality
        ('X is permitted' - but its bare subject anchors the act node), identity
        negation ('X is not Y'), modal-copula fragments, artifact-subject
        recording sentences (position-aware: 'the picking log is closed' survives,
        'the log records X' dies), bare participle fragments
      • relation HARVESTING across the normalizer's dedupe
      • frontend SAME_EVENT/REFERENCE_OF unions VETOED by action compatibility:
        same action lemma (+ non-numeric argument overlap), asymmetric state-of-act
        exception (a state/ref form whose subject head IS the other action),
        recording-verb guard, 'again' repetition veto
      • deterministic consolidation: action-lemma merge, subject-position substring
        merge (object-position containment blocked), adjacent subject-predicate
        attachment (recording guarded)
  → pair proposal: CE ≥ 0.35 OR same-sentence OR entity-token bridge;
     same-action facet pairs suppressed; self/shared-form pairs suppressed
  → E3v3 endpoint certificate
      extractor sees ALL surface forms + type + arguments
      → deterministic verification LADDER:
          (a) any-form of both endpoints inside relation_text   [structural]
          (b) positional extractor anchors                       [CE-gated when
                                                                 cross-sentence]
          (c) clause repair to minimal covering span
          (d) via_reference verbatim inside rel → UNKNOWN pending judge
      → judge v3 (anchor context per endpoint; co-precondition rule; state-facet
        typing rule) with q1/q2 verbatim-in-evidence checks
      → relation-level gates: no-trigger-connective (implicit procedure order is
        NOT a relation), coordination (same-side 'and'-separated anchors =
        co-preconditions), same-sentence anchors, object/recording containment
      → connective-side DIRECTION override (subordinate clause after gating
        connective = antecedent; 'before' inverted under negation; 'in which case'
        - antecedent precedes it) - deterministic, overrides the judge's q4
  → frozen direction/CLS fallbacks (pl machinery)
  → licensed-edge consolidation by effective-endpoint compatibility
```

## F. Oracle decomposition

The previous phase's oracle ladder showed FULL_GOLD+E3 = R .565 / exact 6/15 - i.e.
the certificate mechanism was sound and nodes were the bottleneck. This cycle closed
that gap from the other side: on dev, the REAL pipeline now exceeds the previous
phase's FULL_GOLD+E3 oracle (R 1.000 vs .565; exact 14/15 vs 6/15). Remaining
oracle-style attribution on dev: 1 extra edge (f_planet E3->E1 object-position judge
over-licensing) - i.e. the node layer is no longer the limiter on dev; the residual
is judge discipline on object-position containment, which the v10
recording-containment gate already handles for the recording subclass.

## G. Fresh sealed validations (frozen before inference, run once)

| suite | architecture | P | R | correct | extra | missing | exact | frozen at |
|-------|-------------|---|---|---------|-------|---------|-------|-----------|
| F3 (5 new domains, 9 gold edges) | v8 | .636 | .778 | 7 | 4 | 2 | 3/5 | dce04fd0, sha 91619dc9… |
| F4 (5 new domains, 8 gold edges) | v10 FINAL | **.750** | **.750** | 6 | 2 | 2 | 2/5 | 4c430563, sha e6b04a0e… |

Both suites exercise: coordinated state gates, unless-exception + in-which-case
response, check-result state gates, modal-subject existentials ('Drying may start'),
deontic permission statements with bare-subject references ('Printing is permitted'),
negated-before inversion ('Do not open the dome before X'), repetition ('again'),
gerund references, identity-negation distractors, artifact-subject recording
sentences, and implicit-order traps (gold has NO edge). Checkpoint suites: F2
(previous phase's sealed set, now validation-only) P .600 / R .750; cert-units
regression 17/22.

## H. Failure analysis (sealed F3+F4 residuals, diagnosed but NOT tuned on)

1. **DIRECTION on non-canonical connectives** (F3 h_press 'only if', h_bakery
   'in which case'): the judge's q4 flips; the v9 connective-side override fixes the
   single-connective cases (dev went to R 1.000) but the FIRST-connective heuristic
   mis-fires when two connectives separate the anchors (h_bakery E2-E4 bridging
   'unless … in which case'). Next fix: clause-segment the relation_text and require
   the pair's anchors to be clause-mates (H5 K-parse discipline at clause level).
2. **Multi-clause bridging pairs** (i_clinic E4-E2): a judge YES between endpoints
   that live in DIFFERENT clauses of one sentence, connected only through a third
   clause. Same clause-mate fix as (1).
3. **Determiner-subject SVO clauses** (i_dome 'the wind sensor reads calm'):
   action_signature treats determiner-initial clauses as NP-references (head =
   last token 'calm') - wrong for subject-verb-object states; the fragment twin
   ('reads calm') then fails to merge. Next fix: a tiny POS-anchored subject/verb
   split (the stanza tagger already ships with the frontend) instead of the
   determiner heuristic.
4. **Frontend/bnorm recall on unseen domains** (i_robots 'Run the demo' form lost;
   'the run count' not in the artifact-noun list): the node carried only the gerund
   reference, so the state-gate pair lost its structural anchor. Next fix: extend the
   artifact noun list from data ('count', 'tally', 'roster', 'sheet'…) and add a
   determiner-gerund → imperative lemma fallback in variant generation.
5. **Old-suite gold-convention mismatches** (F2 g_yeast 'unless' contributes only
   the response edge there, while F3 h_bakery's gold accepts both the exception and
   the response edge): a gold-ontology calibration difference BETWEEN suites - not
   a pipeline defect; whatever convention is chosen, one suite scores it as an
   extra. Recommend unifying the convention in the next dataset freeze.

## I. Generalization assessment

Same-architecture transfer dev→sealed: P drops by ~0.2 (.958 → .750/.636), R by
~0.15-0.25 (1.000 → .750/.778). Every sealed failure traces to a NAMED mechanism
class (H.1-H.4) with a concrete deterministic fix - none of them the "no frontend
patch can hide this" kind. The architecture's core claim held: proposal →
source-backed certificate → deterministic structural gates → trusted graph survives
unseen domains, whereas the previous phase's same-frontend pipeline scored exactly
zero on its own sealed suite. Step 1 is NOT yet production-ready (rename invariance
and larger-domain stress not yet re-run on v10; the H.1-H.4 fixes need a further
frozen validation), but the question "can a new policy be turned into the rule it
expresses, reliably?" now has a working, inspectable, mostly-deterministic answer
with a measured error budget.

## J. Cost

- LLM (Mistral ministral-14b, temperature 0): **994 unique prompts** across the whole
  cycle (cached; ~4 MB of responses), of which ~230 frontend/normalizer and the rest
  certificates/judges/fallbacks. Deterministic layers run in <1 s/case on CPU; the CE
  reranker (bge-reranker-base) is the only GPU component (RTX 3090, batch 32,
  <2 s/case).
- Human/agent cost: 10 research iterations in one session, each locally validated
  before spending inference; two sealed suites authored and frozen
  (`w1_f3_build.py`, `w1_f4_build.py` with span-uniqueness and edge-endpoint
  validation).
- Reproducibility: dataset/code commits precede every inference; all outputs, pair
  logs (every CE-passing pair with stage/verdict/reason), scorer and loss-budget
  tools are in-repo.
