# SEARCH_23 — Results (final matrix)

**Обновление 2026-09-28 (Level E, frontend/Step 1):** на 10 новых авторских
policy завершены 14 основных downstream рукавов и exploratory clustering
replay. Строгая оценка считает уникальные направленные gold edges и не
зачитывает смешанные узлы. RAW: 9 правильных/43 лишних/1 пропуск;
EVENTNESS_ONLY: 9/14/1, P .173→.391 при R .900. Gate+canonicalization
имеет P .750 ценой R .600. FULL GOLD nodes: 9/3/1 — даже правильные узлы
не устраняют привязку настоящей цитаты к другому действию. CE fine-tune
имеет 0TP на новых E2; opaque resolver дал 0/63 role changes при rename.
В тесте выявлен конфликт ontology ACTION↔completion-state; sealed gold
сохранён. Это графовые метрики исследовательского набора, не TP/FP public46.
`scripts/predict.py` не менялся. Полные raw, ошибки и ограничения:
[EVENT_FRONTEND_LEVEL_E_RESEARCH_2026-09-28.md](EVENT_FRONTEND_LEVEL_E_RESEARCH_2026-09-28.md).

**Обновление 2026-09-27 (другая задача, policy parser):** замороженное
сравнение A/B/E на 10 новых policy показало `exact IR = 0/10` у всех трёх.
Новый source-first E обеспечил точные source offsets по конструкции, но нашёл
только 2/22 верных action+kind и 0/15 связей condition→action; one-shot A
нашёл 11/22 и 4/15. Даже при подаче золотого action в E_detail найдено
9/15 связей при 13 лишних. Это не метрики конкурсных траекторий. Полный
разбор, методика и raw: [SOURCE_FIRST_ANCHOR_COMPARE_2026-09-27.md](SOURCE_FIRST_ANCHOR_COMPARE_2026-09-27.md).

Branch searh_23/investigator-v2. All numbers on public46 (46 cases, development
set, §7.1) unless stated otherwise. Gold joined post-hoc; no thresholds were
tuned after seeing results. Inputs and per-case records are in git.

## 1. Controls (audited, §1; commits 33cceca..685e4a8)

| Configuration | TP | FP | FN | TN | F1 |
|---|---|---|---|---|---|
| baseline structural Guardian | 12 | 0 | 11 | 23 | .6857 |
| granite 3.3 groundedness (doc 12k) | 16 | 2 | 7 | 21 | .7805 |
| **OR control (Guardian OR granite)** | **20** | **2** | **3** | **21** | **.8889** |
| granite 4.1 standalone (re-run verified) | 17 | 2 | 6 | 21 | .8095 |
| OR with 4.1 instead of 3.3 | 20 | 2 | 3 | 21 | .8889 (no gain) |

Gate conclusion: 4.1's standalone +1 TP brings nothing into the OR hybrid — both
4.1-only wins are already covered by the structural Guardian channel.

## 2. §4.5 decisive comparison — Investigator v2 arms (46 cases each)

| Arm | Base | Arm F1 | Base F1 | flips | tool/orch/NL calls | unknown disp. | latency mean |
|---|---|---|---|---|---|---|---|
| A: P+Graph → Investigator (4 steps, compact) | pgjudge | .7419 | .7419 | 0 | 134/182/38 | 128 | 9.8s |
| B: Guardian+Granite + P+Graph → Investigator | OR | .8889 | .8889 | 0 | 138/184/38 | 115 | 10.1s |
| C: fixed deterministic routing (same tools) | OR | .8889 | .8889 | 0 | 172/0/3 | 98 | 1.0s |
| M: single Mistral judge (whole case) | — | .6984 | — | — | 0/0/0 | 0 | — |

M metrics: TP22/FP18/FN1/TN5 (P .55, R .9565).

**Honest conclusions.**
1. Agent routing choice adds NO measurable benefit over fixed routing at the
   same budget (.8889 both; C is 10x faster and needs no LLM routing).
2. The fixed aggregation discipline (0→1 only mechanical/formal SUPPORTED;
   1→0 only ALL refuted + counter scanned) yields ZERO flips at steps 2/4 —
   evidence stays UNKNOWN in ~2.5 dispositions per case.
3. The two-stage hypothesis (A removing pgjudge FPs) fails: 16 FPs survive
   every step budget.
4. A single LLM judge (M) is far below the granite control.

## 3. §4.2 step-budget ablation (2/4/6, same data, arms A and B)

| Run | F1 | flips | calls (tool/orch/NL) | latency |
|---|---|---|---|---|
| A @2 | .7419 | 0 | 45/90/14 | ~5s |
| A @4 | .7419 | 0 | 134/182/38 | 9.8s |
| A @6 | .7419 | 0 | 224/276/64 | 16.0s |
| B @2 | .8889 | 0 | 46/92/20 | 5.3s |
| B @4 | .8889 | 0 | 138/184/38 | 10.1s |
| B @6 | **.8636** | **1 (1→0, TP lost)** | 225/275/80 | 16.2s |

The ONLY non-zero flip in the entire study is B@6: telecom mms data_usage t7
(gold=1, base=1) flipped 1→0 because `premise_check` returned PREMISES_VERIFIED
for suspicion G0 and the evidence controller refuted the primary channel's flag.
The case is a bare-TOOL_CALL non-engagement violation which the formal layer
cannot represent. More steps ⇒ more opportunities for unjustified refutation:
steps are a cost, not a gain. tp_rescued=0, fp_removed=0 everywhere.

## 4. §5.1 verifier-context ablation (arm B, 4 steps)

| Context | F1 | unknown disp. | note |
|---|---|---|---|
| compact (length-matched) | .8889 | 115 | default |
| full history | .8889 | 115 | no material change |
| graph+exact source | .8889 (B), .7419 (A) | 127 (A) | no material change |

Full-history context does not change a single disposition count versus the
length-matched compact context: the verifier's bottleneck is the evidence
status discipline, not the context window.

## 5. §5.3 P factor analysis (outputs/searh_23/p_factor.json)

- pjudge fresh F1 .7018 (TP20/FP14/FN3) → pgjudge F1 .7419 (TP23/FP16/FN0):
  the graph flip adds +3 TP and +2 FP via 5 label changes
  (TP gained: airline__7::t6, retail__106::t3, telecom mms data_usage t7;
   FP gained: airline__3::t4, retail__78::t1).
- s8 fresh: 88 cards, 44 bound, 0 violated, 28 safe, 60 unknown
  (44 no deterministic binding, 16 bound-but-unobservable;
  blocking stages: applicability_condition_unknown 49, exception_status_unknown 11).
  Clingo remains an honest-negative filter on this benchmark.

## 6. §5.5 Q v2 (outputs/searh_23/q_v2/)

3434 divergences (NuExtract3 vs Mistral-langextract, independent channels),
12 deep questions, 5 verified (span_anchored AND formal_conclusive), 7
unverified, 0 errors. Downstream vs the OLD labels of the SAME configuration:
**0 wrong_to_right, 0 right_to_wrong, 5 no_change** — the v1 "1 flip" does not
survive correct measurement. 1 case (banking__063::t8) where both channels are
empty: Q cannot fire. Q is a diagnostic surface, not a label changer.

## 7. §5.6 Granite modes

- **Evasiveness (conv, 12k; labels audited from surviving per-case):**
  flags 4/46, all gold=1 (P=1.0), all four are BARE TOOL_CALL responses
  (a tool call with zero NL engagement) — NOT refusals: 0/12 refusal/handoff
  cases flagged. Within the bare-TOOL_CALL class (17 cases, 15 gold=1):
  recall 4/15. The class itself is a structural property of public46
  (error injection often manifests as a premature/bare tool call) — reported
  as characterization, NOT as a proposed detector (overfitting risk).
  Mechanical refusal-justification via policy keyword spans discriminates
  nothing (12/12 candidate spans, 5/12 actually gold=1) — caveat recorded.
- **function_call criterion:** applicable in principle — tool definitions with
  preconditions are documented inside <policy> (English) — but no extractor
  was built; recorded as a gap, not a result.
- Historical modes (answer_relevance .7442, context_relevance useless, think
  honest-negative) remain as audited in §1.

## 8. §7.2 frozen candidates — docs/searh_23/FREEZE.md

C1 primary = OR(structural Guardian, granite 3.3 groundedness) F1 .8889;
C2 recall channel = pgjudge R=1.0 F1 .7419 (FP 16 — the open problem);
Investigator v2 kept as experimental mode (no reproducible gain).
Structural channel integration re-validated 12/12 vs the frozen baseline.

## 9. §7.3 contrast evaluation (NEW hotel domain, 20 cases, 10 minimal pairs)

Synthetic suite with expected labels fixed by construction (single author,
recorded as a probe, not a benchmark). Frozen C1 granite channel on it:

| Channel | TP | FP | FN | TN | F1 | pairs with full label flip |
|---|---|---|---|---|---|---|
| granite groundedness | 10 | 8 | 0 | 2 | .7143 | 2/10 |
| C1 (OR with structural) | 10 | 8 | 0 | 2 | .7143 | 2/10 |

- Recall transfers: ALL 10 constructed violations flagged.
- Precision does NOT transfer: 8/10 compliant twins also flagged; only the
  approval-before (p1) and retry-vs-escalation (p7) contrasts produce clean
  label flips.
- The structural channel abstains on the whole hotel suite (0/20, status
  unknown): its checks are calibrated to public46-style event streams —
  C1 degenerates to granite-only on a truly new domain. Domain fragility of
  the structural half is the key honest transfer finding.
- Open external benchmarks: NOT integrated (recorded honestly per §7.2).

## 10. §8 demo (works on new inputs)

`venv/bin/python experiments/searh_23/demo_frozen.py --input <cases.csv>`
runs both frozen channels on any new case (id,prompt,response): structural
Guardian (instant) + granite groundedness (GPU) + fixed OR + per-channel trace.
Demonstrated on fresh hotel cases: pair01::viol → label 1 (granite 1,
structural 0), pair01::ok → label 0. No recorded public46 answers are needed.
Contest-environment constraints: C1 is fully local (16G VRAM granite + CPU
structural); C2/investigator need the Mistral API channel — its availability
in the final contest environment is unverified.

## 11. FP diagnostic set + mechanical FP-refutation layer (post-freeze development)

pgjudge fresh (TP23/FP16/FN0, R=1.0) is the only recall-complete channel; the
16 FP were deep-dived (see docs/searh_23/FP_DIAGNOSTIC.md and
outputs/searh_23/fp_diagnostic/): 15/16 refutable by 8 general evidence-cited
operations, 1 honest residual (banking_080, no clean latest observation).
Dominant cause (~9/16): preconditions demanded where no action is executed or
the demanded confirmation is already present — an action/communication
discriminator problem, not reasoning budget (consistent with Investigator v2).

Mechanical refutation layer over pgjudge candidates (1 -> 0 only when ALL
flagged cards refuted; any UNKNOWN keeps):

| Layer | TP | FP | FN | P | R | F1 | note |
|---|---|---|---|---|---|---|---|
| pgjudge (base) | 23 | 16 | 0 | .590 | 1.0 | .7419 | recall channel |
| + refute v1 | 22 | 6 | 1 | .786 | .957 | .8627 | killed TP banking_003::t7; unsound 080 removal |
| + refute v3.0 | 23 | 5 | 0 | .821 | 1.0 | .9020 | INDEXING BUG: violated_cards looked up in the full card list while the judge sees only grounded cards (19/46 records affected) |
| + refute v3.1 | 23 | 6 | 0 | .793 | 1.0 | **.8846** | corrected (grounded-card indexing); 0 TP lost; 080 UNKNOWN-kept |
| + refute v4 | 23 | 6 | 0 | .793 | 1.0 | .8846 | v3.1 + structural guard + history-satisfaction + scope entailment + temporal threshold; public46 unchanged |

CORRECTED CLAIM: v3.1 does NOT beat the frozen OR baseline F1 (.8889). It is a
different tradeoff point: recall-complete (R=1.0, FN=0 vs baseline FN=3) with 6
FP vs baseline 2. The earlier .9020 was inflated by the indexing bug (one FP
refuted via a wrong-card lookup, telecom t15). In-sample caveat still applies.

Out-of-sample hotel port (checkpoint 10, outputs/searh_23/hotel_p/):
pgjudge pipeline unchanged, paths repointed (experiments/searh_23/p_hotel_port.py).

| Channel | set | TP | FP | FN | TN | P | R | F1 |
|---|---|---|---|---|---|---|---|---|
| granite groundedness | semantic20 | 10 | 8 | 0 | 2 | .556 | 1.0 | .7143 |
| pgjudge (cards+graph) | semantic20 | 10 | 9 | 0 | 1 | .526 | 1.0 | .6897 |
| pgjudge (cards+graph) | all28 | 14 | 12 | 0 | 2 | .538 | 1.0 | .7000 |
| pgjudge + refute v3.1 | all28 | 14 | 12 | 0 | 2 | .538 | 1.0 | .7000 |
| pgjudge + refute v4 | all28 | 14 | 3 | 0 | 11 | .824 | 1.0 | **.9032** |

- pgjudge RECALL transfers to the new domain (R=1.0); precision does not (12 FP).
- v3.1 does NOT transfer: 0/12 hotel FP refuted — but 0 TP lost: the layer
  abstains rather than wrongly refutes (safety property holds out-of-sample).
- Hotel FP causes are a NEW class vs public46: ~9/12 "precondition already
  satisfied in trajectory history (verify_identity match:true /
  check_supervisor_approval granted / cancelled_at present / incident report
  found), judge demands restatement in the final response". Absent from the
  public46 diagnostic set the v3 families were built on.
- v4 BUILT AND RUN (checkpoint 11): structural guard (ported catalog checks —
  undeclared tool / missing required args; saved pair13/12::viol TPs),
  history-satisfaction (entity-anchored SAT/FAIL observations), scope
  entailment, temporal threshold. hotel 9/12 FP removed, 0 TP lost ->
  F1 .9032 R 1.0; public46 unchanged (.8846, families inert there).
  Honest residuals: pair05/08 (suite-lenient labels, judge right under
  strict policy reading), pair11 (control artifact).
- IN-SAMPLE CHAIN: public46 in-sample for v3, hotel in-sample for v4;
  mechanisms domain-general, JSON-key lexicon portable; a THIRD unseen
  domain / new trajectories = the honest validation frontier (next step).

## Bottom line

- The best frozen configuration remains the audited control
  **OR(structural Guardian, granite 3.3 groundedness) = F1 .8889** on public46.
- Investigator v2 (agent routing, more steps, richer verifier context, Q,
  single-judge) adds no reproducible label-level value; its only observed
  flip is harmful. The negative results are themselves the deliverable of
  §3/§4/§5: the useful mechanisms are (a) the OR of two independent channels,
  (b) graph flips inside pgjudge (+3 TP), (c) granite evasiveness as a
  high-precision narrow detector of bare-TOOL_CALL non-engagement.
- Transfer risk is real: on a new synthetic domain the structural half
  abstains and granite precision collapses; the frozen candidate should not
  be represented as domain-general.
- Recommended next iteration: pgjudge as candidate generator with a
  mechanical FP-verification layer (the reverse of the failed A arm), and
  porting the structural checks to new-domain event formats.
- UPDATE (post-freeze, corrected): the layer exists — refute v3.1 reaches
  F1 .8846 / R 1.0 in-sample on public46 (indexing-bug-corrected; v3.0's
  .9020 was inflated). Out-of-sample hotel port: recall transfers (R=1.0),
  the v3.1 families do not (0/12 FP removed, 0 TP lost — safe abstention).
  v4 history-satisfaction family is the recorded next step (§11).

## 12. Typed-question layer (Jev-form) and LettuceDetect v2 locator (2026-09-24)

Protocol per directive: replay the mechanical base, compare base vs base+typed-questions
vs base+LD-locator on identical inputs, freeze rules, one run on unseen scenarios;
report additional TP / removed FP / lost TP separately. Full report:
`docs/searh_23/TQ_LD_LAYER.md`; artifacts `outputs/searh_23/tq_layer/`, `outputs/searh_23/ld_layer/`.

| Arm | Suite | TP | FP | FN | F1 | Changes vs base |
|---|---|---:|---:|---:|---:|---|
| v3.1 (replayed from committed code; 0 per-case mismatches) | public46 | 23 | 6 | 0 | .8846 | baseline |
| v3.1 + typed questions (Mistral, frozen iter-3 rules) | public46 | 23 | 4 | 0 | .9200 | -2 FP (airline__10 tense; banking_033 not-due), 0 TP lost |
| v3.1 + LD encoder locator | public46 | 23 | 5 | 0 | .9020 | +1 new FP ("185"), 0 missed errors, 0/7 fragment supply |
| v4 (replayed; in-sample families) | hotel28 | 14 | 3 | 0 | .9032 | baseline |
| v4 + typed questions (same frozen rules) | hotel28 | 14 | 3 | 0 | .9032 | 0 changes (0 removed, 0 TP lost) |
| v4 + LD encoder locator | hotel28 | 14 | 4 | 0 | .8750 | +1 new FP (unsourced "5000 bonus points" vs lazy label), 0/5 supply |

Development-loop honesty: TQ iteration 1 lost 7 TP (F1 .9143) via three unsound paths
(trigger scope, entailment invention, loose handoff conjunction); all were fixed at
logic level and documented before freezing. LettuceDetect v2-qwen-2b emits invalid
span offsets on this corpus (negative indices into context) and is unusable via
lettucedetect 0.2.3; the encoder emits token-level spans (median 5 chars) that do not
supply operation-grade claim fragments (0/12 supply overall). The typed-question layer
is experimental, not promoted into frozen candidates; its measured property is zero
TP losses anywhere with code-verified, evidence-cited refutation traces.

## 13. Fast follow-up prepared for the next server run (2026-09-24)

Branch `codex/fast-followup-20260924` contains a frozen, 32-case service-desk
mechanism suite and one label-free runner. The suite is balanced across gold
class and response tool-call shape; its labels are read only after prediction
files are sealed. Existing C1, Granite context-budget, `function_call`,
pgjudge, v3.1/v4/v4-safe, and TQ arms are run on the same case IDs.

Additional prepared arms are: (1) exact source and entity joins for argument
provenance and failed-call replay (diagnostic only); (2) extractive
action-feasibility proposals for refusal/handoff; (3) atomic completed-action
claim proposals checked against matching successful tool results; and (4) R1/R2
from the exact historical E2E commit `300dc2e` on the same CSV. The two Mistral
proposal arms have code checks for citations, tool membership, entity and
amount but still depend on model semantics; `UNKNOWN` is retained in their raw
traces. C1 OR proposal, C1 OR E2E, and C1 AND refutation arms are reported
separately with per-case TP/FP changes.

Before reading the first server results, a paired lexical robustness suite was
also frozen: `service_desk_v1_renamed` changes every case/device ID and tool
name, with all 32 labels and response-call shapes held fixed. Any improvement
that disappears under these benign renames is not a mature candidate.

At the initial branch freeze, Granite and Mistral had not run on the new suite.
The first server execution below has not been scored, so there is still no new
quality result. The server commands and stop conditions are in
`docs/searh_23/FAST_FOLLOWUP_RUNBOOK_2026-09-24.md`. A gain on the authored suite
tests a mechanism; it does not establish performance on untouched contest data.

### First server execution: technical repair before scoring

The first `pgjudge` extraction attempt on `service_desk_v1` produced 30/32
parseable records and 0 grounded cards. The model folded source line wraps in
policy quotes; the original exact-substring anchor therefore rejected them.
The two failures returned an empty JSON array (`[]`) instead of the required
object, so they now normalize to zero cards for extraction only. Before scoring,
the runner was amended to accept a **unique whitespace-only** quote match,
replace it with the exact source span, retain the model quote in the trace,
and retry other no-JSON completions once with a larger output budget. The initial
append-only records remain available. These are input/serialization repairs;
their effect on predictions and quality is still unmeasured.

### Label-free diagnostic after the first completed proposal run

The original service-desk run completed local C1, pgjudge, refutation, TQ,
and both v1 proposal stages. TQ made 67 Mistral calls on 25 surviving alarms
and changed zero raw decisions. This is not a quality score: labels have not
been opened. The v1 feasibility extractor proposed one candidate, on a
stock-out refusal whose cited policy merely *permits* a delay or transfer.
Its two other possible cases failed quote validation because the model folded
line wraps. The v1 completion extractor proposed no candidates on six
eligible responses; its raw explanation for a false completed-action claim
said no matching result existed, showing that it interpreted `candidate` as
"supported" rather than "asserted". Neither v1 proposal is ready to promote.

Two explicitly post-inspection diagnostic variants now have separate files:
`feasibility_v2.jsonl` demands a unique source quote from a single mandatory
policy clause that names the target tool; `completion_v2.jsonl` asks for a past
claim independently of whether the history supports it. Both retain v1
artifacts. They are developed after reading label-free v1 outputs, so a gain
on these same authored cases is development evidence, not independent transfer.

The additional `service_desk_precondition_ablation/cases.csv` removes one of
four stated prerequisites (stock, identity, authorization, confirmation) from
each v2 refusal/handoff candidate in both lexical variants. It has no gold
file; the narrow expected property is that a conditional **must act now**
proposal stops when any antecedent is absent. This was constructed after v2
inspection and is a falsification stress test, not another held-out score.

## 14. Completed server follow-up and modal-rule audit (2026-09-24)

Full sealed per-case results, paired-renaming flips, post-inspection
prerequisite ablations, and the modal-word counterexample are in
`docs/searh_23/FAST_FOLLOWUP_SERVER_RESULTS_2026-09-24.md`.
The 32-case authored suite and its renamed pair show C1 TP16/FP12/FN0 in
both. C1 AND frozen v4-safe appears to reduce FP to 8 and 7 without lost TP,
but its additional removals depend on the invalid inference that a policy
quote without `must` is not an obligation. A separate modal-safe replay
returns C1 AND layer to TP16/FP11/FN0 on both. This replay was written after
the scores were opened; it is a logic correction, not independent validation.
Six valid-call FP per suite remain. No new whole-case classifier is promoted.

## 15. Vast action-state and completion mapping probe (2026-09-26)

This was a component test, **not** a full benchmark or a new whole-case score.
On 16 service-desk text responses, 16 lexical renames and 16 new authored
responses, a narrow Mistral API frame extractor got the action kind right
16/16, 16/16 and 15/16. Actor was right only 13/16, 12/16 and 14/16: it
repeatedly assigned `ASSISTANT` to requests that the **user** act.

Source-bound completion proposals exposed a deeper gap. The first
claim-to-tool mapper chose the correct tool for 2/4 original and 3/4 renamed
completed claims; adding exact catalog descriptions raised this only to 3/4
and 3/4. It still mapped a completed **replacement** claim to the **audit**
tool, while quote anchoring and absence of a tool result produced a positive
candidate. On four fresh paired claim families the mapping was correct, but
two families returned abbreviated policy quotes; exact validation yielded
only 4/8 expected component verdicts. Replacing those quotes with the suite's
single policy clause after scoring yielded 8/8, a serialization control rather
than an end-to-end improvement.

No arm is added to C1. The evidence-backed next target is checking whether a
*specific tool result entails the specific completed-action claim*, with
negative pairs such as replacement versus audit. Full setup, hashes, paired
errors and the formalization-paper triage are in
`docs/searh_23/VAST_SEMANTIC_PROBE_RESULTS_2026-09-26.md`; archived artifacts
are in `outputs/searh_23/action_state_probe_2026-09-26/`.

## 16. Tool-effect and external-runtime audit (2026-09-26)

A source-bound counterfactual question did **not** resolve the claim-to-tool
gap: on three development families it selected the intended action tool on
0/18 history variants. Terse tool descriptions did not establish every stage
of a completed-action claim. A second probe with the actual result and strict
call/ID/outcome gates still produced **3 false supports on 18 development
rows** and **1 on 36 new-domain rows**; it also missed 4 of 6 genuinely
supporting fresh results. A generic `status: completed` from an audit or scan
tool can still be mistaken for completion of the business action. Neither
probe is promoted to C1. Detailed sealed results are in
`docs/searh_23/VAST_TOOL_EFFECT_RESULTS_2026-09-26.md`.

Ten adjacent systems were audited in
`docs/searh_23/EXTERNAL_TOOL_TRACE_SYSTEMS_AUDIT_2026-09-26.md`. ToolSandbox
and AgentDojo are most useful as state-backed evaluation environments;
Invariant and MFOTL provide event-order/provenance mechanics once tool effects
are known. None infers a reliable business postcondition from an ambiguous
trace. The next bounded candidate is an explicit source-bound postcondition
contract with `UNKNOWN` when the trace has no such evidence.

## 17. Typed tool-trace transfer (2026-09-26)

Implemented a narrow transfer from Invariant/formal runtime verification and
ToolSandbox-style paired testing in `vnext`. Existing source envelopes already
pair calls and results by actor, full tool identity and transport ID. A new
strict layer (`bound_tool_effects_v2`) requires an application-authored equality
join between a call field and a result field; it rejects reversed, disputed or
non-tool results while leaving frozen T1 unchanged. `ordered_effects_v1` checks
whether a confirmed effect on one exact entity has an independently confirmed
prerequisite for that entity **before**
the action. A missing witness returns `UNKNOWN`; it does not assert absence
of external actions.

The local 10-variant control covers wrong entity, wrong call ID, duplicate IDs,
late or wrong-entity approval, generic completed status from an audit, failure
and missing result. It also compares a simulated replacement and a simulated
audit against their distinct post-states. These are deterministic component
tests, not an independent Guardian score. The result depends on an
application-reviewed, exact tool-version contract and explicit postcondition;
most competition tools do not supply that authority. No new C1 arm or veto is
enabled, and no full benchmark was run. See
`tests/test_vnext_ordered_effects_v1.py`,
`src/guardian_truth/vnext/bound_tool_effects_v2.py` and
`src/guardian_truth/vnext/ordered_effects_v1.py`.

## 18. Real tool trace and independent generality audit (2026-09-26)

On the inspected public46, exact source-bound contracts confirmed three
action results: one reservation cancellation, one exchange **request**, and
one line resumption. These are component facts, not three newly detected
violations. Exact entity echoes recovered 41 previously ambiguous read-result
pairings for two reviewed tools; one concrete case would pair incorrectly by
FIFO. No binary Guardian prediction changed.

The separate `codex/generality-research-20260926` branch contains a promising
post-hoc replay, but six counterexamples show that its proof layer can accept
wrong actions, wrong entities, or missing amounts. Its TP16/FP7/FN0 renamed
suite result is not a fresh validation and cannot yet be promoted. Detailed
commands, source hashes, per-case evidence, and limitations are in
`docs/searh_23/REAL_TOOL_AND_GENERALITY_AUDIT_2026-09-26.md`.

## 19. Target-call precondition probe (2026-09-26)

A narrow Mistral API question about one proposed tool call improved on C1's
six service desk false alarms in an authored 16-call suite, but tool renaming
introduced three model false alarms and eight state/provenance controls added
two more. On eight previously viewed hotel calls, the model marked all four
nominally valid calls as violations. The common failure is wrong clause scope
or wrong interpretation of a cited prior fact. A conservative exact-scope
replay retracts unsupported accusations to UNKNOWN and checks call shape
independently; it does not establish a binary score gain. One hotel `ok` label
also conflicts with its own identity prerequisite. See
`docs/searh_23/CALL_CONDITION_PROBE_2026-09-26.md` for counts, seals and
case-level counterexamples. No new arm is promoted to the entry point.

## 20. Action-trigger and ordered-evidence transfer (2026-09-26)

The action-stage trigger was frozen before a balanced 12-case parcel suite
and a 12-case tool-renamed copy were sent to Mistral API. Raw model counts on
each suite were TP6/FP2/FN0; the trigger withdrew one FP to UNKNOWN while
retaining all six TP. A post-hoc source-paired latest-observation check then
withdrew the other FP to UNKNOWN. The same check withdraws one service-desk
state-control FP, and an exact earlier action/result pair withdraws the
renamed audit FP. No binary entry-point decision changed; an UNKNOWN fallback
remains unselected and the temporal layer was written after seeing the parcel
answers. Full per-case results, proof boundaries and external-repository
transfer are in `docs/searh_23/ACTION_TRIGGER_TRANSFER_2026-09-26.md`.

## 21. Small action graph and sourced fact chain (2026-09-26)

A bounded compiler now enumerates every supported policy bullet for one call,
then checks same-entity prior results and action order in a small evidence
graph. Repair controls and gold were frozen at `3c68de7` before the verifier.
It scored TP6/FP0/FN0/TN6 on each of four authored 12-case suites: repair,
renamed repair, parcel, and renamed parcel. The repair rules deliberately
mirror parcel's grammar, so this is a mechanism check rather than independent
policy transfer. On the more complex existing service-desk policy, 14/16
cases remained UNKNOWN; the two other calls had structural errors. The
compiler's binary output is valid only under its narrow complete grammar;
the contest entry point is unchanged. Details, seals, adversarial controls,
and the next policy-language test are in
`docs/searh_23/MICROGRAPH_CERTIFICATE_2026-09-26.md`.

## 22. Policy-language transfer and role extraction (2026-09-26)

Three 12-case policy-wording suites were frozen before Mistral API inference.
The canonical-language compiler returned UNKNOWN on all 36; no binary gain.
Keeping original bullets and asking for tool roles yielded 5/7 exact clause
roles. A narrower, post-hoc pairwise question yielded 22/28 correct
governed-action roles and 20/28 correct evidence roles. One policy omitted the
replacement action entirely; pairwise questions also missed it. Exact source
quotes and valid JSON did not protect against this semantic omission. An
independent audit found three constructed false-SAFE holes in the earlier
certificate; entity binding, action-effect recognition, and paraphrase gating
were tightened. The authored 48-case replay remains intact; 16 targeted
tests pass. None of these probes changes `scripts/predict.py` or a contest
prediction. See `docs/searh_23/POLICY_LANGUAGE_PROBE_2026-09-26.md`.

## 23. Typed policy atoms across new domains (2026-09-26)

Seven one-call Mistral API extractions were checked against policy atoms and
contrast traces frozen before each call. On five conjunction policies, all 11
conditions were named, but two prior-evidence conditions were incorrectly
made latest-result conditions. Three of five policy IRs were fully exact. The
model failed to mark both an emergency exception and a numeric limit as
unsupported by the conjunctive Boolean schema. A post-hoc source guard sends
those two examples to UNKNOWN. No false SAFE appeared on the 62 authored
conjunction cases, but removing any one required atom creates 3–4 false SAFE
decisions. This quantifies the still-unsolved completeness risk. No full
benchmark or entry-point change occurred. See
`docs/searh_23/POLICY_ATOMS_PROBE_2026-09-26.md` for the frozen protocol,
raw outputs, limitations, and next gate.

Independent Astra High audit found and prompted fixes for duplicate-atom
counting, vacuous SAFE when no atom governs the target, and numeric `1`
passing as Boolean evidence. A remaining constructed case still gets false
SAFE when one of two otherwise valid atoms governs the wrong tool. This is a
source-completeness/action-binding failure, not an event-join bug; the typed
atom layer remains diagnostic only.

## 24. Original-clause scope and completeness audit (2026-09-26)

Using the model and key supplied by the server environment through Mistral API,
an action-first question mapped the constrained tool scope on 4/5 previously
viewed service-desk/hotel clauses and 5/5 other clauses from those same
policies. On seven clauses from original public46 retail, airline and telecom
policies, tool scope was correct on 7/7, but only 5/7 outputs carried an exact
continuous source quote. A separate post-hoc quote-only repair fixed both
format failures without changing tool selection. One service/hotel order rule
still included a prerequisite action in the constrained scope.

A second-model completeness question was tested on five authored conjunction
rules, each intact, with one prerequisite removed, and with one condition bound
to a request instead of the action. After fixing an underdescribed tool catalog,
it strictly accepted only 2/5 intact rules while rejecting all five wrong
action bindings and four of five missing-prerequisite controls with valid
source quotes. It cannot certify a complete policy interpretation and would
abstain on too many valid rules. No binary competition replay or entry-point
change occurred. Frozen protocols, raw responses, per-case errors and limits
are in `docs/searh_23/SOURCE_POLICY_COMPILATION_2026-09-26.md`.
The full research handoff is in
`docs/searh_23/CURRENT_RESEARCH_PROBLEM_2026-09-26.md`.

## 25. Staged policy tree and as-of effect claims (2026-09-27)

The user's staged-parser proposal was implemented as two frozen diagnostic
protocols on the new Vast server through the configured Mistral API. V1
misclassified four of five conjunction clauses as an ordering between actions:
its 2/8 exact score consisted solely of pre-model exception/numeric abstains.
After viewing V1, the V2 prompt explicitly separated checks/approvals from
business operations. On the original clauses plus two new authored transfer
clauses it got 10/10 typed-field IR scores. A manual source-span audit found
two action quotes that actually named prerequisites. A post-hoc conservative
span-overlap gate withdrew both to UNKNOWN, leaving 8/10 accepted, including
the two code-only abstains. This is a promising narrow repair, not a complete
policy compiler.

The unchanged V2 scope prompt selected a valid exact action quote and full
tool set on 5/7 previously viewed original public46 clauses. It cannot encode
a policy that governs three modification tools, and it labels several
prohibitions as `PRECONDITION`. No full benchmark or entry-point promotion was
run. A separate typed-effect proof helper now cuts the event ledger at the
answer time; audit success, a generic `completed` status, or a later result
cannot establish an earlier replacement claim. It depends on an application
authored effect contract and a correctly typed claim. Protocols, raw outputs,
cost, case-level failures and limits are in
`docs/searh_23/STAGED_POLICY_TREE_AND_EFFECT_CLAIMS_2026-09-27.md`.

## 26. Policy inventory versus local relation typing (2026-09-27)

A frozen 12-clause Mistral probe attempted to inventory every policy head,
tool set and rule kind at once. It produced 0/12 structurally complete
answers; five calls returned non-object JSON, while the other answers omitted
required fields, duplicated derived prohibitions, or moved conditions to
new parent rules. Some partial meanings, such as three relevant retail tools
and both baggage facets, were found. When the exact source fragment and
action were manually supplied, a separate 16-case relation-only question
matched 15/16 frozen labels; the lone disagreement (`never ... without`
approval) has a logically compatible conditional-prohibition reading.

Direct model-generated source segmentation passed all literal, coverage and
count gates on 1/12 full clauses. Selecting only code-enumerated cut IDs
preserved source text but matched expected cuts on 2/12. A narrow deterministic
splitter for explicit sentence and contrast markers then matched 14/14
post-hoc selected source clauses and 12/13 further original-policy clauses
whose annotations were frozen before replay. It over-split an illustrative
`For example` sentence. None of these results establishes coverage of nested
conditions or a binary competition gain. The full case-level record is in
`docs/searh_23/POLICY_STRUCTURE_FOLLOWUP_2026-09-27.md`.

## 27. Paired Req2LTL/OnionL and NL2Logic architecture comparison (2026-09-27)

Twelve identical policy clauses, one server-configured Ministral model and a
frozen hand-annotated IR were used to compare an adapted one-shot arm, an
adapted staged arm, a Req2LTL/OnionL-like recursive tree, and an
NL2Logic-like parser-selector tree. The first JSON-mode pilot exposed a
response-shape mismatch and was retained only as a format diagnostic. The
schema-controlled protocol was committed before its first successful response;
no prompt, gold, or algorithm changes followed the 48-arm run.

Strict full-IR matches were 0/12 for every arm. The adapted one-shot arm
matched 7/19 gold directive kinds plus exact action quotes in 12 API calls;
staged matched 5/19 in 37 calls. OnionL-like compiled 0 directives in 111
calls; NL2Logic-like compiled one incorrect directive in 134 calls. The
recursive trees sometimes found individual conditions, but confused check
gates with business ordering or lost source anchors when normalizing atoms.
These results reject *our current adaptations* as contest candidates, not
the original research systems. The dataset is small, partly previously viewed,
and exact span scoring is intentionally strict. Raw calls, per-case errors,
metric definitions, method-to-paper mapping and limitations are in
`docs/searh_23/REQ2LTL_NL2LOGIC_ARCHITECTURE_COMPARE_2026-09-27.md`.

## 28. Source preservation and sequential search integration (2026-10-02)

Isolated branch `research/source-search-20261002` integrates an immutable
complete source index, plain KB retrieval, typed entity navigation, actual
BFS/DFS, shared quote references, source-bound arithmetic, and a judge that
may request further evidence. Mechanical admission/source round trips pass
46/46; 11 cases have structural hits. Retail29's second order is reachable;
banking plain-text results are indexed; original amounts yield 75.00%;
19 airline dates reach the literal extractor. These are component checks,
not model quality or proof that an automatically chosen date pair is relevant.

A stopped historical V4 comparison produced 69/92 records. Each arm's six
TP were structural; direct had one TN, all other records UNKNOWN. The search
arm had 27 transport/format failures, so this run does not establish whether
the architecture helps. Real small probes found native function-call replies
being rejected as empty text and ordinary reads past EOF being rejected.
Both issues were fixed. A subsequent real probe completed two source reads
and reached the judge, but still returned UNKNOWN because required checks
were omitted. V7 offers one bounded follow-up to investigate missing checks;
16 local regressions pass. Live HTTP checks pass 11 structural cases without
model calls. Thirty-two new authored contrasts are frozen; independent label
review and transfer inference remain outstanding. No predictor promotion.
Full traces, partial metrics, resource accounting, and limitations:
`docs/searh_23/SOURCE_SEARCH_SYSTEM_2026-10-02.md`.

## 29. Typed latest move and counterevidence (2026-10-03)

Completed the 24-record source-search preflight. Under pending author labels,
Ministral direct produced 2 TP / 1 FP / 3 UNKNOWN; the other three model/arm
groups each produced six UNKNOWN. Search often exhausted steps before deciding.
Controller now reserves judgment steps and a final assessment. Replaying saved
Gemma direct replies with JSON-fence support alone recovered no assessments:
checks had the wrong type or additional data followed JSON.

A six-case short API screen with explicit user requests found GPT-OSS:120b
correctly distinguish both omitted-search and both numerical contrasts with
exact evidence. Its two order-case decisions matched authored expectations but
had nonliteral shortened JSON quotations, so validation retained UNKNOWN.
AI Horde Gemma and Llama replies were unsuitable; other APIs were not called
after the budget reserve stop. These are authored diagnostics, not held-out proof.

An opt-in Pydantic move/intent parser, code-owned native call inventory,
act/tool/performer scope gate, full initial system sources and per-finding
counterevidence review are implemented. Mismatches remain UNKNOWN; matching
labels do not certify entailment. 37 mechanical regressions pass locally and
on the server. The completed 18-record direct/typed-BFS/typed-DFS ablation
established no gain: each arm had one TN and five UNKNOWN. Four of six typed
cases never reached the judge; surviving cases had no graph roots, so that
ablation did not demonstrate actual graph benefits.

A separate 32-case EN/RU component probe completed eight Mistral HTTP calls
(11,098 tokens). All frames were structurally valid; act kinds and intent
status each matched 30/32 authored expectations, all fields jointly 18/32.
No USER evidence leaked into assistant acts. Several actor gold expectations
are questionable; future/conditional are incorrectly exclusive in the schema.
This bank has 16 bilingual families, pending human review, and is not an
independent detector-quality measurement. Canonical parser replay matches
all 32 saved frames with zero API calls.

Per-finding review on four viewed authored situations (eight source views)
failed. The first quote-copying interface passed provenance in 1/8 and returned
eight UNKNOWN (12,462 tokens). Frozen source-ID selection passed provenance
8/8 but confirmed every accusation, including four negative controls
(18,631 tokens). Four real nonempty BFS/DFS views changed no decisions.
Source preservation fixed quotation fidelity, not semantic entailment or bias
toward a supplied accusation. A restricted executable-formula compiler pilot
then completed 16/16 records on the same eight sources for both models:
four viewed controls plus four new authored contrasts. Ministral and GPT-OSS
each retained eight UNKNOWN; cost 52,932 tokens. Gap declarations conflated
agent omissions with researcher uncertainty; multiple formulas also had invalid
quantifier bindings or boolean types. A zero-API replay that
only bypassed declared gaps evaluated one Ministral and two GPT-OSS positive
conditions, with all other replies still unresolved/invalid. This counterfactual
is not an improved official score or evidence of full-policy completeness.
Navigation roots are chosen by code, not the model. Competition predictor
is unchanged. Details:
`docs/searh_23/TYPED_MOVE_AND_COUNTEREVIDENCE_2026-10-03.md`.
