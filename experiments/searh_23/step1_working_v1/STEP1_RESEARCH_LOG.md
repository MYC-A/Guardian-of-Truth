# STEP1_RESEARCH_LOG — working-architecture cycle

Branch: `codex/step1-working-architecture-20260929` (from `codex/step1-ready-ie-frontends-20260928` @ 092896d7).
Format per directive §6: HYPOTHESIS / WHY / CHEAP TEST / RESULT / FAILURE MODE / DECISION / NEXT IDEA.

Known starting state (from previous phases, NOT to re-prove):
- E3 endpoint certificate works on clean endpoints (F2 FULL_GOLD R .500 vs E1 .125) but
  collapses on noisy real nodes (F2 LLM_SG+E3: 0 correct, 18 extra).
- LLM_SG is the best candidate generator (mR .699, typeAcc .753) but nodes are noisy.
- Ready IE systems (OneKE/UIE/GLiNER/OmniEvent/OpenNRE) are dead ends as frontends. AMR =
  structural witness only.
- scripts/predict.py frozen. Step 2 frozen.

## D0. Initial diagnosis (2026-09-29) — before any new LLM call

Manual tracing of F2 failures (g_film, g_watertower, g_curling, g_repeater, g_yeast):

**Missing edges (recall) mechanism, g_watertower E1->E2 (CE=0.997, cert run manually):**
- LLM_SG proposes OVERLONG span "Clean the interior only after the tower is drained"
  (event + connective + subordinate state in one mention).
- build_nodes groups {overlong span, 'the cleaning'}; node_view displays SHORTEST span
  first -> primary span = 'the cleaning'.
- E3 extractor quotes relation_text = "Clean the interior only after the tower is
  drained" but sets b_in_relation = "the cleaning" (the display name) -> NOT a substring
  of relation_text -> deterministic verifier: relation_text_not_connecting_both_endpoints
  -> UNSUPPORTED. Both gold edges of the case die on this one node.
=> Two independent defects: (a) overlong spans, (b) display-span-vs-relation-span mismatch.

**Extra edges (precision) mechanisms, g_film:**
- c02 'the inspection is logged' typed EVENT (gold STATE) -> state becomes normative
  endpoint -> extra E1->E4-class edges licensed with real evidence.
- c09 'the inspection', c10 'the mold check' -> PARTIAL sub-spans inside real state spans
  -> junk singleton nodes -> contaminated endpoints.
- c06/c14 UNGROUNDED spans (start=None, paraphrase) still become nodes (build_nodes
  keeps them; start defaults 10**6).
- c05 'the inspection is logged and the mold check is negative' overlong (conjunction
  of two states as one reference).
- Co-precondition pairs ("A and B gate C") still occasionally licensed as A->B.

DECISION D0: no new mechanism yet. First build deterministic loss-budget tooling
(directive §38) to quantify each category on main F + F2 before choosing hypotheses.

## H1. Boundary normalization + anchor-set certificate repair (deterministic + tiny LLM)

HYPOTHESIS: The single biggest recall killer is span-boundary damage (overlong spans
absorbing connectives/subordinate clauses) combined with the verifier demanding the
DISPLAY span inside the relation text. Both are repairable WITHOUT new semantics.

CHEAP TEST: F2 (5 cases) probe: hygiene + bnorm v2 + E3v2 + anchor-set verify.

RESULT (F2, DOWN vs W1_DOWN_LLM_SG): P 0.000->0.273, R 0.000->0.375
(0/8 correct -> 3/8; extra 18->8; nodes 40->23: EXACT 14 / OVERLONG 4 / SUBSPAN 3 /
SPURIOUS 2; gold cid coverage 12/13). PROMOTE with iteration.

FAILURE MODES remaining (D1, traced certificate-by-certificate, no new LLM calls):
- (A) extractor quotes a WRONG-LOCATION form for a_in_relation (e.g. 'the cleaning'
  from the NEXT sentence) -> verifier's rel-Containment check fails although the
  endpoint IS represented inside relation_text. 2 of 5 missing edges (g_watertower,
  g_film E1->E2).
- (B) extractor quotes a FRAGMENT as relation_text ('but only when the scrapes are
  dry') missing endpoint A -> g_curling E1->E2. Deterministic clause repair needed.
- (C) CE band kills cross-sentence state-gated pairs: g_repeater (Measure, Transmit)
  CE=0.057 although the gate state shares the sentence with Transmit. Reranker is a
  relevance model, not a discourse-relation model.
- (D) bnorm DROPS legit state clauses (g_repeater 'swr reading is below two') and
  frontend emits predicate-initial fragments ('is contaminated') -> missing E3 node
  (g_yeast). Subject re-attachment + deterministic keep-override needed.
- (E) node-surface conventions: gold uses full clauses ('the culture is contaminated')
  AND subject-less predicates ('is stored') AND article forms ('the swr reading is
  below two'); pipeline needs boundary VARIANTS as member forms (multi-representation
  node), incl. keeping the ORIGINAL span when bnorm normalizes (g_curling 'after
  scraping' -> 'scraping' lost the exact gold match; g_film 'Inspect reel 7 for mold'
  -> 'Inspect reel 7').
- (F) junk nodes: orphan fragment NPs ('the mold check' inside 'the mold check is
  negative'), artifact-subject sentences ('the cleaning certificate confirms the
  cleaning', 'is a document') -> extra edges.
- (G) judge discipline: co-preconditions still licensed as A->B (g_film 'the
  inspection is logged' x 'the mold check is negative'); relation typing: state-form
  antecedents typed ORDER_BEFORE instead of PRECONDITION/STATE_GATE because the judge
  never sees WHICH surface form the relation text uses. typed=0/3 on F2.
- (H) CE pair construction is order-dependent (i<j only) and sentence-blind.

DECISION: H1 iteration 2 = deterministic-heavy v3 (see D1-v3 below). Tune on main F
(dev) ONLY; F2 becomes the validation checkpoint; final generalization claim requires
a fresh sealed suite (to be built, F3).

## D1-v3. Pipeline v3 changes (implemented 2026-09-29, pre-registered before runs)

Deterministic layer:
  v1. verifier: any-form-inside-relation_text for both endpoints (drop reliance on
      extractor's a_in/b_in choice; anchors become evidence, not gates);
  v2. relation-text clause repair: if a form is missing, expand rel to the minimal
      covering span within its sentence; re-check;
  v3. via_reference channel: form missing + extractor's *_via_reference verbatim
      inside rel -> pass to judge as UNKNOWN-candidate;
  n1. member-form VARIANTS: original span (pre-bnorm) + normalized + leading-article
      variant + predicate-only variant + subject-extended variant (all verbatim);
  n2. orphan-fragment drop: grounded NP-like candidate strictly inside another
      grounded candidate with NO relations -> fragment, drop;
  n3. artifact-subject filter: subject head in {log, certificate, note, record,
      report, master, form, file, reading} + communication verb / 'is a <noun>'
      predication -> NON_EVENT, drop;
  b1. bnorm keep-override: frontend STATE/CHECK-typed span matching a copula/passive
      regex is never dropped (restore as KEEP if the LLM dropped it);
  b2. subject re-attachment: predicate-initial spans extend left to the clause
      subject (deterministic scan);
  p1. pair-proposal channels: CE>=0.35 OR same-sentence-form co-occurrence OR
      content-token (entity) bridge between the nodes' forms/sentences.

LLM layer (prompts):
  v4. node_view passes type + arguments to extractor/judge prompts;
  j1. judge sees the in-relation anchor form for each endpoint (typing context);
  j2. judge co-precondition rule strengthened (coordinated 'and' clauses jointly
      gating a third action -> q3 NO).

Regression gate: w1_cert_units (22 frozen adversarial items) must be >= E3 baseline
(15/22) before any downstream run.

RESULT (gate, 2026-09-29): 17/22 >= 15/22 PASS. All 9 positives SUPPORTED;
3 negatives missed through the judge (cf_neg_09 argument-as-endpoint,
cf_neg_12, cf_neg_14). First v3 verifier version (any-form ONLY) scored
0/22 - root cause: single-form unit endpoints require the v1 positional
extractor-anchor path; fixed by the verification LADDER (a) forms-in-rel
-> (b) positional extractor anchors -> (c) clause repair -> (d)
via_reference->judge.

## D2. Dev run v3 (main F): P .270 / R .739 (correct 17, extra 46)

Recall fixed (was 4/23), precision now the bottleneck. Extra attribution:
contaminated_or_junk_endpoint 25, unsupported_edge 13, duplicate_gold_edge 8.
Node defects: 14 None-label + 5 MIXED nodes; mechanism classes:
- taxonomy-missed junk ('The feeding roster is a document', 'is a document')
  - subject noun ('roster'/'tally') not in artifact list;
- act/state/ref node MULTIPLICITY -> duplicate gold edges + self-loops
  (E1 licensed via act-node AND via state-node);
- fragment nodes ('passes', 'is filed', 'start') without subject;
- modal/deontic restatements ('must be repeated', 'Repair is permitted');
- identity-negation distractors ('X is not Y', 'is a separate event');
- overlong-form lemma poisoning + argument-sharing over-merge
  (Feed/Weigh the red pandas) in early consolidation prototypes.

## D1-v4. Iteration 3 changes (commit 580afbc1, before dev inference)

- consolidate_nodes() deterministic H4 core:
  (1) action-lemma match + >=1 shared NON-NUMERIC argument lemma
      (merges act/gerund/passive-state facets of the SAME action;
      keeps argument-sharing DIFFERENT actions apart);
  (2) substring merge guarded by OP_ON_MENTION ('Log the inspection',
      'verify that X passed' are events ABOUT the contained mention);
  (3) adjacent subject-predicate attachment guarded by RECORDING_PRED
      ('X is logged' = logging event, not facet of X);
  - 'again' repetition veto (distinct event instances never merge);
  - identity lemmas computed from connective-free short forms only
    (overlong originals are anchors, not identity evidence).
- junk filters: taxonomy predication (any subject), deontic adjectives,
  identity-negation, modal-copula fragments, artifact-subject + comm-verb
  with modals/inflections;
- negation-strip variant ('Do not X' -> 'X');
- p1b CE gate: positional extractor-anchor paths require CE band or
  same-sentence co-occurrence; structural and via_reference paths stay open.
- Local deterministic validation (both suites): every case's node set now
  matches the gold cid structure (Feed/Weigh separate, Log-the-inspection
  separate, act+state clusters merged, distractors dropped).

## D3. Iterations 3-8 on dev (main F, 15 cases): summary table

| arm | P | R | correct | extra | missing | exact | change |
|-----|---|---|---------|-------|---------|-------|--------|
| baseline DOWN_LLM_SG_E3 | .167 | .174 | 4 | 20 | 19 | 2/15 | frozen previous phase |
| W1_DOWN3 (v3) | .270 | .739 | 17 | 46 | 6 | 1/15 | ladder verifier + channels + variants |
| W1_DOWN4 (v4) | .423 | .478 | 11 | 15 | 12 | 4/15 | consolidation v1 (over-merge bugs) |
| W1_DOWN5 (v5) | .412 | .913 | 21 | 30 | 2 | 5/15 | action-lemma compat + harvesting + trailing spawn |
| W1_DOWN6 (v6) | .618 | .913 | 21 | 13 | 2 | 6/15 | asymmetric state-of-act, same-action suppression, coordination gate, deontic attach |
| W1_DOWN7 (v7) | .778 | .913 | 21 | 6 | 2 | 11/15 | effective-endpoint dedup, no-connective gate, aux fragments |
| **W1_DOWN8 (v8)** | **.808** | **.913** | **21** | **5** | **2** | **12/15** | tightened no-connective ('only at' is not gating), object-containment gate |

Target reference (directive): strict edge P >= ~0.80, R >= ~0.70 -> REACHED on dev
(P .808, R .913; typed 18/21; exact graphs 12/15).

Residual dev errors (5 extra + 2 missing):
- f_planet E1->E2 licensed with REVERSED direction ('only while' simultaneity
  confuses the judge's q4) -> 1 extra + 1 missing;
- f_planet E3->E1 object-containment judge over-licensing -> killed in v8?
  (f_pool/f_pit class), remaining: f_pool 3 edges with REAL textual evidence
  ('Test the level before reopening') against ultra-sparse gold (gold has
  only 1 edge for the case) - gold-boundary semantics, documented residual;
- f_bottling E1->E2 missing: 'Label each crate and pack each crate after
  capping' - 'after capping' attachment scope ambiguity (gold scopes the
  connective over the whole coordination, the judge reads it as attaching
  to 'pack' only).

## H1 DECISION: PROMOTE. The working architecture is:

  LLM_SG frontend (schema-guided proposer, frozen)
  -> deterministic hygiene (grounding + connective strip)
  -> LLM boundary normalizer (extractive-subspan discipline, KEEP-drops)
  -> deterministic node construction:
       form VARIANTS (original/article/predicate-only/subject-extended/
         negation-strip), subject re-attachment (copula/modal/aux-initial),
         trailing-clause spawning (states + gerunds out of overlong spans),
         bnorm keep-override (indicative copula states),
         junk filters (taxonomy/deontic/identity-negation/modal-copula/
           artifact-subject-comm-verb/participle fragments),
         relation HARVESTING (all frontend candidates by span/root),
         frontend-relation unions VETOED by action compatibility
           (asymmetric state-of-act, recording guard, 'again' veto),
         deterministic consolidation (action-lemma + args, subject-position
           substring, adjacent subject-predicate with recording guard)
  -> pair proposal: CE band OR same-sentence OR entity-bridge,
     with same-action facet suppression
  -> E3v3 certificate: extractor (all surface forms + type + arguments)
     -> deterministic verification LADDER:
        (a) any-form in relation_text -> (b) positional extractor anchors
        (CE-gated for cross-sentence) -> (c) clause repair -> (d)
        via_reference -> judge
     -> judge v3 (anchor context, co-precondition rule, typing rule)
     -> relation-level gates: no-connective, coordination,
        object-containment, NOT_SUPPORTED
  -> direction/CLS fallbacks (frozen pl machinery)
  -> licensed-edge consolidation (effective-endpoint compatibility)

## Validation sequence (2026-09-29): F2 checkpoint + F3 sealed

F3 SEALED suite frozen BEFORE any F3 inference (commit dce04fd0):
5 new domains (greenhouse/bakery/aquarium/printing press/orchard),
9 gold edges, hard features: coordinated state gates, unless-exception +
in-which-case response, check-result state gate + deontic requirement +
modal recording mention-only event, deontic permission with bare-subject
reference, repetition ('again') + gerund ref + conditional gate, implicit-
order traps (NO edge), identity-negation distractors. SHA 91619dc945aa8bb4.

STATUS: F2 + F3 chains running.

## H2. Node certificate (directive §7-§9)

HYPOTHESIS: junk/partial/ungrounded/state-typed-as-event nodes pass into endpoints
because nothing checks node well-formedness. A NodeCertificate (span grounded verbatim,
predicate anchor inside span, claimed arguments grounded, type evidence, contrastive
EVENT-vs-STATE verdict) gated deterministically will remove the extra-edge noise
without killing recall.

WHY: F2 extra=18 decomposes mostly into junk endpoints (partial spans, connective
spans, ungrounded spans) and state-as-endpoint errors.

CHEAP TEST: 30 hard mentions (worst F2/F nodes + hard negatives incl. CHECK/STATE);
measure false-trusted-nodes and real-node-recall before/after gate (directive §5
example metrics).

STATUS: pending.

## D4. Final iterations and sealed validations (2026-09-29)

- v9 (same-sentence anchor rule + connective-side direction override):
  dev P .958 / R 1.000 / exact 14/15 (BOTH missing edges recovered: the
  implicit-order traps died at the same-sentence gate; the flipped
  directions died at the connective-side override).
- v10 (+ recording-state containment): dev unchanged; F2 P .600 / R .750.
- F3 SEALED (v8, frozen dce04fd0): P .636 / R .778, 7/9 gold, exact 3/5.
- F4 SEALED (v10, frozen 4c430563, sha e6b04a0e8a911965): P .750 / R .750,
  6/8 gold, exact 2/5. Residuals: 2 extras (multi-clause bridging pair;
  determiner-subject SVO fragment intercept) + 2 missing (fragment twin
  not merged; gerund-only node lost the imperative form) - all four are
  named mechanism classes with deterministic fixes (see report H).
- Rename invariance on v10: NOT re-run this cycle (pending; the previous
  phase's LLM_SG+E3 was rename-invariant 15/15 on edges and the v10
  prompts contain no tool names, but the claim needs a fresh run).
- Cert-units regression: 17/22 (gate passed at every prompt change).

DECISION: cycle complete. Report:
STEP1_WORKING_ARCHITECTURE_RESEARCH_2026-09-29.md. Next cycle candidates:
clause-mate pair discipline (H.1/H.2), POS-anchored subject/verb split for
determiner-subject SVO states (H.3), artifact-noun + variant fallbacks
(H.4), gold-convention unification for 'unless' suites, rename re-run.
