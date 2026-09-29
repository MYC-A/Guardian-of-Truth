# EVENT NORMALIZATION / CANONICALIZATION — GENERALIZATION PHASE (Level F5)

**Branch:** `codex/event-normalization-f5-20260929` · **Date:** 2026-09-29
**Directive:** decide whether v10 is a genuinely generalizable Event
Normalization architecture or substantially tuned deterministic guards.
**Order of trust (§20):** F5 sealed / rename / counterfactual > F3/F4
checkpoint > dev. Dev main F (P .958 / R 1.000) is explicitly NOT the
success criterion of this phase.

---

## 1. Question, pre-registration, and freeze discipline

Starting state (W1, frozen as V10_FROZEN at df4f9508): dev main F
P .958 / R 1.000 / exact 14/15, but sealed F3 P .636 / R .778 and F4
P .750 / R .750 — a ≥0.2 precision drop on unseen data. The phase
question: how much of the v10 gain reproduces on fresh unseen policies,
and WHERE does the loss sit (sanitation / identity / relation)?

Pre-registered before any F5 inference (research log D1–D5, commits
798683cd, 32bbad4e):

- **H.1–H.4** written out before implementation (error class / general
  mechanism / expected effect / regression risk).
- **F5 sealed suite** (sha 4546acef…): 20 policies (6 known-mechanism K /
  6 recombination R / 8 genuinely-new N), 182 mentions, 82 canonical
  events, 36 gold edges, 219 gold pairs (SAME 21 / RELATED 93 /
  DIFFERENT 105), 5 CF minimal-pair twins, 6 renamed cases.
- **Arms:** v10; v11 = v10+H.3; identity arms A/B/C/D/H/F4way; modular
  architecture (A-layer + H∧F identity + veto clustering) on the frozen
  relation stack; external ECR baselines; oracle decomposition; rename;
  CF twins.
- **Predictions (D5):** (i) F5 edge P/R within ~0.15 of the F3/F4 range
  (P .64–.75, R .75–.78) ⇒ generalizable; collapse below .5 ⇒ overfit.
  (ii) H_v10 identity F1 ≈ .5–.6 with low dangerous merges.
  (iii) F4way beats deterministic arms by ~.1 F1.
- Deterministic full-format conversion of the frozen compact F5 files
  (`en_f5_convert.py`; level_f5_cases.json sha 00a97f9f…, level_f5r
  a600cbd2…) committed BEFORE inference (6f022b90).

The relation stack (E3v3 extractor/judge prompts, CE band 0.35, DIR/CLS
fallbacks, relation gates) and V10_FROZEN were untouched for the whole
round; every arm is a node-builder swap executed through the byte-verbatim
frozen loop.

## 2. Execution integrity

- **Replay faithfulness:** the F5 relation-stack runs execute the EXACT
  source text of the frozen `w1_pipe3.py` main() per-case loop (extracted
  and `exec`-replayed with a swapped `build_nodes_v3`). Smoke test:
  re-running dev case f_bottling through the replay reproduces the saved
  W1_DOWN10 output (nodes, edges, pair-log length all equal).
- **Incidents during the round (documented; none retro-tuned):**
  1. Builder-signature crash: 4 arms wrote nothing before the fix (the
     driver silently moved on). Re-run from per-case resumability; since
     no inference output existed for those arms before the fix, no F5
     information could leak into any decision.
  2. `en_common._ceaf_entity` used exhaustive `itertools.permutations`
     (hangs beyond ~10 clusters); fixed to the greedy one-to-one
     alignment its docstring already claimed. Cluster metrics are
     computed PER-CASE and macro-averaged (B³/MUC/CEAF are per-document
     metrics); the first external-baseline attempt merged all cases into
     one cluster list (semantically wrong and infeasible) and was killed
     and re-run correctly.
- The Mistral cache is shared across arms (temperature 0): v11's
  judge/certificate calls that coincide with v10's are cache hits; no
  answer was ever sampled twice; oracle arms reuse frontend/bnorm caches
  where node views coincide.

## 3. External ECR baselines (directive §6)

Actually run — identical zero-shot protocol (predict coreference clusters
on the policy text, map gold event mentions by normalized exact span,
pair decision = same cluster, no abstention):

| baseline | pair P | R | F1 | dangerous | gold-event-span coverage | CoNLL |
|---|---|---|---|---|---|---|
| LingMess (longformer-large; OntoNotes entity coref) | .000 | .000 | .000 | 0 | 3/101 | .621 |
| coreferee 1.5.0 en (OntoNotes+GAP+wiki) | .000 | .000 | .000 | 0 | 0/101 | .621 |

Both trained entity-coreference systems fail at the **mention layer
itself**: over the 20 policies LingMess proposed 27 clusters / 59 spans,
almost exclusively entity NPs ('the lens housing'), covering 3 of 101
gold event mention spans; coreferee produced 15 chains linking none of
them. The coreference-scoring layer is never reached. Clean negative
result: existing trained entity-coref does not transfer to event
identity in policy text — the barrier is mention proposal, not linking.

Documented blockers (checked this session, specifics in §2 of the
research log D6): fast-coref/CRAC (Google Drive 404 page stored as
model.pth; gdown lists top-level folders, nested model dirs download 0
files); biu-nlp/fcoref (HF 401 gated org — same for the lingmess-large
API; our local LingMess weights predate this and verified working);
SECURE (no runnable public checkpoint reachable); MAVEN-ERE trigger
tagger (no standalone downloadable model).

## 4. Identity layer on F5 (Level 1; 219 gold pairs)

| arm | F1 | P | R | dangerous |
|---|---|---|---|---|
| A_lex (floor) | .300 | .231 | .429 | 13 |
| B_emb (bge-base, dev-locked τ=0.75) | .473 | .382 | .619 | 8 |
| C_ce (bge-reranker, dev-locked τ=0.2) | .175 | .096 | 1.000 | 105 |
| H_v10 (compatible_nodes) | .612 | .536 | .714 | 1 |
| **D_pred** | **.667** | .667 | .667 | 0 |
| D_pred+ent / +args / +ent+args | .632 | .706 | .571 | 0 |
| D_all / D_no_mode / D_mode_only | .632 | .706 | .571 | 0 |
| F4way (LLM 4-way judge) | .651 | .636 | .667 | **0** |

Dev→F5 transfer: D_all .519/.509 (dev ec/fa) → **.632**; H_v10
.555/.569 → **.612**; C_ce .184 → .175 (template saturation reproduces
exactly); A_lex .409 → .300. **The deterministic identity layer
transfers at or above its dev level.** The dev-derived feature-ablation
ordering (predicate = recall driver; entities/args = precision) also
reproduces: D_pred alone has the best F1 on F5, entity/argument features
trade recall for precision, dangerous merges stay ≤1 where the dev
ablation predicted.

F4way's confusion is informative: 79/93 RELATED gold labeled RELATED,
49/105 DIFFERENT → DIFFERENT, 56 DIFFERENT→RELATED drift, only 8
RELATED→SAME and 0 DIFFERENT→SAME. The narrow LLM judge has real 4-way
discrimination and never dangerously merges — its value is the RELATED
channel and its abstention discipline, not raw SAME F1.

Candidate generation (§8) on F5: locality/union recall 1.0 with
reduction 0.0 (policies are 2–4 sentences; every event pair is local);
lemma-family recall .619 / reduction .813; emb-top3 recall 1.0 /
reduction .187. On short policies, blocking is unnecessary —
pair-reduction is a long-policy problem, not an F5 one.

## 5. Clustering (Level 2)

F4way veto clustering over gold event mentions vs gold clusters:
CoNLL **.7503** (B³ F .924, MUC F .443, CEAF-E .883). Transitive closure
is identical (SAME-edge closure already transitive); merging RELATED as
well collapses (B³ P .356).

Modular identity (H∧F) over A-layer frontend mentions: 68 clusters,
**17 false merges**, coverage 69/82, purity .8619. On the A-layer bench
(260 pairs; 131 carry AMBIGUOUS labels because an endpoint is
junk/unlabeled): F4way P .29 / R .9 / F1 .439; hybrid I_HF P .196 /
R 1.0 / F1 .328 with 7 dangerous. **The same judges that score .651 on
clean gold spans score .439 on predicted mentions** — frontend noise,
not the classifier, dominates the composed system.

## 6. Graph level (Level 3) — the sealed F5 verdict

| arm | P | R | F1 | correct/extra/missing | exact | CoNLL | FM | junk | recall |
|---|---|---|---|---|---|---|---|---|---|
| dev main F (reference, W1) | .958 | 1.000 | — | 23/1/0 | 14/15 | .776 | 0 | 2 | .939 |
| F3 (v8, reference) | .636 | .778 | — | 7/4/2 | 3/5 | — | — | — | — |
| F4 (v10, reference) | .750 | .750 | — | 6/2/2 | 2/5 | — | — | — | — |
| **v10 on F5** | **.406** | **.361** | .382 | 13/19/23 | 6/20 | .803 | 6 | 14 | .768 |
| **v11 (v10+H.3) on F5** | **.452** | **.389** | .418 | 14/17/22 | 6/20 | .801 | 5 | 12 | .784 |
| oracleA: gold nodes + frozen stack | .800 | .667 | .727 | 24/6/12 | 9/20 | 1.000 | 0 | 0 | 1.0 |
| oracleB: A-layer + gold identity | .483 | .389 | .431 | 14/15/22 | 5/20 | .891 | 0 | 30 | .864 |
| modular: A-layer + H∧F identity | .429 | .250 | .316 | 9/12/27 | 3/20 | .724 | 11 | 8 | .614 |

**The pre-registered overfit threshold is crossed:** v10 F5
P .406 / R .361 — precision is .23 below the F3 level and .34 below F4;
recall .39 below. The W1 dev score (.958/1.000) does not survive fresh
data; the graph-level pipeline as a whole is confirmed overfitted.

But the oracle arms decompose the failure, and it is NOT uniform (next
section). v11 is consistently and modestly better than v10 on F5
(P +.046, R +.028, junk −2, false merges −1, recall +.016) — the D4
promotion of H.3 on old-suite evidence was the right call and holds on
sealed data.

## 7. Oracle decomposition (§18)

Deterministic ceilings from saved outputs (v10):

| quantity | value |
|---|---|
| gold edges | 36 |
| node ceiling (both endpoints cleanly labeled) | 23 (.639) |
| proposal ceiling (endpoint pair reached the stack) | 21 (.583) |
| licensed correct | 13 (.361 actual R) |
| licensing efficiency (correct/proposed) | .619 |

Recall loss attribution (36 → 13): **13 edges lost to missing/mixed
nodes**, 2 more never proposed, 8 lost at certificate/judge/gates.
v11: ceiling 24 (.667), proposed 22, correct 14, efficiency .636.

The three oracle arms triangulate the same story:
- **oracleA (gold nodes + frozen stack) = P .800 / R .667** — the
  relation stack itself generalizes: with clean nodes it is already
  above every real F-suite pipeline result this project has produced
  (F3 .636, F4 .750) and far above v10-on-F5.
- **oracleB (A-layer mentions + GOLD identity) = P .483 / R .389** —
  even with perfect identity, predicted-mention noise (30 junk nodes,
  wrong boundaries, missing mentions; cluster recall .864) caps the
  graph barely above v11 itself. The sanitation layer alone explains
  most of the v10 collapse: perfect identity buys only +.03 P and
  +.000 R over v11's own consolidation.
- **modular (A-layer + predicted H∧F identity) = P .429 / R .250** —
  the pre-registered modular architecture UNDERPERFORMS the v10/v11
  monolith (R .250 vs .361/.389): the H∧F clustering on noisy predicted
  spans both under-merges (cluster recall .614 vs v10's .768) and
  mis-merges (11 false-merge nodes vs 6). The strong form of the
  modularity hypothesis is refuted: with current components, the v10
  monolithic consolidation is the better identity engine on real
  frontend output.

## 8. Rename invariance (§14)

Structural identity (same node count, same induced cluster partition
over gold labels, same gold-labeled edge set) across the 6 renamed
cases: **v10 4/6, v11 5/6**. Graph scores on the renamed suite: v10
P .364 / R .286, v11 P .500 / R .357 (vs the same cases' original-side
results — per-case detail in f5_rename_agreement.json). Identity
decisions are rename-stable where the mentions themselves are extracted
consistently; the two v10 disagreements trace to different frontend
candidate sets on renamed text (a mention-extraction effect, not an
identity effect).

## 9. Counterfactual minimal pairs (§13)

| system | both sides correct | binary flip pattern correct |
|---|---|---|
| H_v10 | 0/5 | 2/5 |
| D_all | 0/5 | 2/5 |
| F4way | 1/5 | 4/5 |
| v10 node build | 1/5 | 4/5 |
| v11 node build | 1/5 | 3/5 |

Named failure classes (the twins did their job):
- **Check-embedding** (cf_filter_b: 'an operator verifies that the
  filter was inspected'): EVERY system merges the check with the checked
  action. The action-vs-check distinction fails exactly when the checked
  event appears as an embedded passive inside the check verb.
- **Irregular passive morphology** (cf_otters_a: 'the otters are fed'):
  H and D miss feed→fed (crude suffix stripping); F4way and both node
  builds get it right.
- **Same-predicate-different-object** (cf_otters_b: 'Feed the otters' /
  'Feed the red pandas'): v10 AND v11 node builds FALSE-MERGE them —
  the most dangerous observed failure of the deterministic
  consolidation, and it reproduces in the F5 graph numbers (6 false
  merges).
- **Substring lemma traps** (cf_batch_b: 'the weight' vs 'Weigh each
  linen batch'): raw H merges weigh⊂weight; the full v10 pipeline
  separates them correctly (artifact filter) — pipeline-level guard
  value over the raw pairwise criterion.
- **H.3 regression** (cf_vessel_b: 'The cleaning is logged'): v11 merges
  the recording with the action where v10 correctly separates — H.3 is
  not free; its determiner-subject signature treats 'The cleaning is
  logged' as an SVO about cleaning.
- F4way is the only system that answers RELATED (not just non-SAME) on
  3/5 side-b pairs — again the RELATED channel is the LLM's edge.

## 10. Guard replay / C-decomposition transfer (§3, §19)

Post-hoc replay of the saved F5 v10 pair logs (zero LLM):

| stage/gate | extra killed | gold killed |
|---|---|---|
| ce_band | 43 | 2 |
| certificate (unsupported) | 26 | 5 |
| no_trigger_connective | 6 | 4 |
| cross_sentence_gate | 5 | 0 |
| verifier q3 = no | 3 | 1 |
| semantic_link routing | 2 | 0 |
| coordination gate | 4 | 0 |

The guards still kill mostly extras on F5 (85 extra vs 12 gold) — they
transfer as precision filters. The riskiest on F5 is
**no_trigger_connective** (4 gold edges killed: fresh constructions
license relations without the enumerated trigger words), replacing
cross_sentence (0 gold on F5) as the dev-tuned gate to reconsider. The
guards cannot recover recall lost upstream: the dominant losses are at
the node layer, before any gate fires.

## 11. Failure taxonomy (§22)

v10 on F5 (deterministic attribution, per class):

| class | count |
|---|---|
| node_missing_mention (gold cid not covered) | **21** |
| edge_extra_judge_overlicensing | 18 |
| node_junk_survivor | 14 |
| node_false_merge | 6 |
| edge_missing_certificate/judge/gate | 8 |
| node_false_split | 2 |
| edge_missing_not_proposed | 2 |
| edge_wrong_direction | 1 |

(v11: junk 12, false merge 5, missing mention 20, extras 16 — every
class mildly improved.) The taxonomy is dominated by the MENTION layer:
39 of the error mass (21 missing + 14 junk + 6 false merge... counting
nodes and their downstream edge consequences) originates before any
identity or relation decision.

## 12. Pre-registered prediction verdicts (§20)

| prediction | verdict |
|---|---|
| (i) F5 edge P/R within ~0.15 of F3/F4 | **FALSIFIED** — P .406 (vs .64–.75), R .361 (vs .75–.78) |
| (ii) H_v10 identity F1 ≈ .5–.6, low dangerous | **CONFIRMED** — .612, 1 dangerous |
| (iii) F4way beats deterministic by ~.1 F1 | **FALSIFIED** — parity (.651 vs D_pred .667) |
| F5 collapse below .5 ⇒ overfit | **CONFIRMED** — at the graph level (P .406 / R .361) |

## 13. The central hypothesis (§25): monolith or modules?

The A/B/C decomposition, now measured on sealed data, separates cleanly
by transfer behavior:

| layer | dev level | F5 transfer | verdict |
|---|---|---|---|
| A — candidate sanitation (frontend+bnorm+hygiene) | recall .939, junk 2 | recall .768, junk 14, 21 cids uncovered; caps oracleB at ~.47 | **DOES NOT TRANSFER** |
| B — event identity (consolidation / pairwise) | pair F1 .52–.56, CoNLL .78 | pair F1 .61–.67, CoNLL .80, dangerous ≤1 | **TRANSFERS** |
| C — relation stack (certificate/judge/gates) | dev R 1.000 on v10 nodes | oracleA P .80 / R .667 on gold nodes; guards kill 85 extra / 12 gold | **TRANSFERS** (with a licensing-recall gap) |

The pre-registered modular arm (A-layer + H∧F identity + veto clustering
+ frozen stack) is the architectural embodiment of the hypothesis — and
it is REFUTED in its strong form: the modular arm scores P .429 /
R .250, WORSE than the v10/v11 monolith (.406/.361 and .452/.389),
because the same identity judges that score .651 on gold spans score
.439 on predicted spans (17 false merges at clustering, cluster recall
.614). Modularity does not rescue the pipeline: the A-layer noise
dominates everything downstream, and v10's monolithic consolidation
actually handles noisy mentions better than the composed alternative.

**Answer to the directive's core question:** v10 is neither a uniformly
generalizable architecture nor uniformly tuned guards. It is a sound,
transferable normalization CORE (identity + relation licensing —
oracleA .80/.67 on perfectly clean nodes exceeds every previous real
pipeline) wrapped in a sanitation layer whose recall and junk behavior
were implicitly fitted to dev-family extraction failures. The W1 claim
"no fundamental limitation" is refuted in its strong form: there IS a
limiting layer, and it is the frontend/normalizer, not the normalization
logic. The honest reformulation: *identity and relation-licensing
mechanisms generalize; mention extraction does not.*

The residual licensing gap (oracleA R .667 vs dev R 1.000) additionally
shows judge/gate calibration is partly dev-tuned: on fresh constructions
the judge under-licenses (8 lost of 21 proposed) while still
over-licensing 6 extras — both directions present.

## 14. Costs

- LLM (Mistral ministral-14b, temperature 0, cached): frontend 26 cases +
  10 CF policies ≈ 36 calls; bnorm ≈ 310 candidates; relation stack
  (v10/v11/oracleA/oracleB/modular + f5r) ≈ 1,900 certificate/judge/
  fallback calls (heavy cache reuse across arms); identity F4way
  219 + 217 + CF 10. ≈ 2,800 prompts total, ~0.9 M tokens.
- GPU: bge-reranker-base (stack), bge-base + stanza (identity), LingMess
  2.4 GB (external baseline) — all sequential/parallel on one RTX 3090.
- Deterministic replays (scorer, oracle decomposition, guard replay,
  taxonomy): seconds per suite.

## 15. Conclusion and next steps

The sealed F5 round gives the generalization question a precise,
attributed answer:

1. **The v10 graph pipeline is overfitted** (P .406 / R .361 on F5; the
   pre-registered <.5 threshold crossed) — the W1 dev result does not
   transfer as an end-to-end system.
2. **The overfit is localized, not global**: the identity layer and the
   relation stack transfer (oracleA .80/.67; identity F1 at/above dev;
   guards still precision-positive); the mention-extraction layer does
   not (recall .768 vs .939; 21/82 gold events never covered; junk
   ×7; oracleB capped at ~.47 even with gold identity).
3. **H.3→v11 was the right promotion** (better on every F5 metric) and
   H.1/H.2/H.4 were rightly rejected — the D4 discipline (choose by
   old-suite causal evidence, never by F5) held.
4. **The narrow LLM identity judge is at parity with deterministic
   features on SAME/NOT-SAME but is the only system with a real RELATED
   channel and zero dangerous merges** — its role should be
   abstention/discipline, not recall.
5. External trained entity-coref systems are not competitors here: they
   fail at proposing event mentions at all (≤3/101 coverage).

Next steps (F6 candidates, not tuned on F5):
- Frontend recall: the mention layer needs a recall-oriented rewrite
  (form-variant coverage, passive/nominalization generators) measured by
  cluster_recall on NEW sealed suites — oracleA shows the stack will
  convert improvements ~1:1 into graph recall.
- Judge licensing gap: direction/classification discipline on fresh
  constructions (8/21 lost) without reopening the dev-tuned gates.
- The check-embedding class (cf_filter_b) and same-predicate-different-
  object false merges are the two named identity mechanisms to fix next.
- A long-policy suite would make the candidate-blocking analysis
  meaningful (short policies make blocking vacuous).
