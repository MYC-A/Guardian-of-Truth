# STEP 2 — Evidence / Tool Effects / World State: Research Report (2026-09-28)

Branch: `codex/step2-evidence-effects-20260928` (worktree `/workspace/guardian/step2_wt`)
Scope: **STEP 2 ONLY** — "what is actually provable from observed tool calls, tool results
and tool contracts". Step 1 (policy parsing) and Step 3 (agent claims) are out of scope;
a small claim-probe diagnostic (§31 of the brief) is included only to test ledger
usefulness. `scripts/predict.py` untouched; frozen competition path untouched.

## 0. Executive summary

Step 2 was implemented as a **proof-carrying evidence layer** and evaluated on a frozen
73-case dataset (22 hard categories × 6 domains, committed before any inference). The
central architectural hypothesis — *LLM proposes, deterministic code witnesses* — is
empirically confirmed:

| Evidence regime (sealed test) | WorldFact P | R | invented facts |
| --- | ---: | ---: | ---: |
| LLM, name+description only (A) | 0.00 | 0.00 | **100%** |
| LLM, +input schema (B) | 0.00 | 0.00 | **100%** |
| LLM, +actual result, unwitnessed (C) | 0.59 | 0.68 | **40.9%** |
| LLM, name-blind, unwitnessed (E) | 0.70 | 0.74 | 30.0% |
| **LLM name-blind + deterministic witness (H)** | **1.00** | **0.74** | **0%** |
| Pure structural classifier, no LLM (F) | **1.00** | 0.74 | 0% |
| Conservative extractive mapper (G) | 1.00 | 0.58 | 0% |
| Oracle contracts (I) | 1.00 | 0.47 | 0% (strength exactness 1.00) |

The four-level distinction demanded by the brief — *tool succeeded / operation
requested / operation executed / world state observed / world state confirmed* — is
enforced by an effect-strength lattice plus an authority ladder, and the claim probe
answers SUPPORTED / CONTRADICTED / PENDING / UNSUPPORTED correctly on **12/12**
diagnostic propositions (including "audit succeeded ≠ business action succeeded",
wrong-entity, no-echo, async, stale state and read-beats-self-report cases).
Counterfactual flip rate is 1.0 (C/E/H/F) and rename invariance is 1.0 for E/H/F while
the name-using LLM arm drops to 0.6 — names are a real leakage channel, and removing
them costs nothing once a witness is present.

**Recommendation**: promote the H architecture (narrow name-blind LLM proposer +
deterministic witness + event-sourced ledger) as the Step 2 candidate; F is a
zero-LLM fallback with the same sealed-test precision. What still blocks integration
is coverage of semantic business predicates (request/exchange/refund tier), the
read-vs-mutation ambiguity, and result-born entities — see §22.

## 1. The problem

Guardian observes `TOOL CALL → TOOL RESULT` but needs `WORLD FACT`:

* `create_refund_request(...) -> {"success": true}` proves at most that a request
  record flow succeeded — not that money returned;
* `write_audit(device=17) -> success` does not prove `device_replaced(17)`;
* `exchange_delivered_order_items(...) -> success` proves `exchange_requested`, not
  `exchange_completed`.

Prior Guardian probes (2026-09-26, `tool_effect_probe`) had already shown: with
description-only input the model selected the correct DIRECT tool on **0/18** rows;
with the result added it produced **false support** (audit results accepted as proof
of replacement; generic `"status":"completed"` read as completion of the *claim*).
This phase therefore asked whether a deterministic, provenance-carrying layer can
separate the five levels above without ever collapsing them silently.

## 2. External systems: what transfers

Prior audit (`EXTERNAL_TOOL_TRACE_SYSTEMS_AUDIT_2026-09-26.md`) covered ten adjacent
projects (AgentDojo, ToolEmu, ToolSandbox, Invariant, Snyk Agent Scan, NeMo
Guardrails, Guardrails AI, MFOTL/formal-rv, Gravit, Hefesto). New reviews this phase:

| System | What it does | What transfers | Boundary |
| --- | --- | --- | --- |
| **AgentRx** (arXiv:2602.02475, Microsoft) | synthesizes guarded constraints from tool schema + policy + trajectory prefixes; step-by-step evaluation; auditable violation log with evidence; LLM judge only over that log | the "constraints + auditable log + judge on top of verified evidence" shape — exactly the Step 2 evidence graph; guarded evaluation = strength witnessing | diagnoses *failed* trajectories; Guardian must also judge successes honestly (UNKNOWN vs FALSE) |
| **tau-bench** (Sierra, arXiv:2406.12045) | evaluates agents by comparing the final DB state against the annotated goal | the authoritative-post-state pattern: actions judged by state, not success acks — our CONFIRMED tier + read-confirmation layer | Guardian has no live DB at inference; only trace-visible evidence |
| **Evidence-tracing survey** (arXiv:2606.04990) | execution provenance = typed graph of an agent execution; evidence tracing = its projection onto support relations | validates ToolCall→ToolResult→Evidence→WorldFact with typed nodes | survey; no runnable component |
| **"When Tools Lie" post-condition pattern** (2026 practitioner literature) | every state-changing call followed by a deterministic read that confirms the change | arm J formalizes this with explicit no-retroactive-justification semantics | — |

No external system supplies the missing semantics of a generic status field. The
"authoritative post-state vs trace-report" distinction remains the core idea; it is
now implemented as the authority ladder `TOOL_SELF_REPORT < CONTRACT_GUARANTEE <
READ_OBSERVATION`.

## 3. Architecture (implemented as `src/guardian_truth/step2/`)

```
TRAJECTORY (call/result pairs, explicit call_id)
   ↓  result interpreter: ResultType (FAILURE / SUCCESS_ACK / BUSINESS_STATE /
      ASYNC_ACCEPTED / OBSERVATION / PARTIAL_SUCCESS / EMPTY / MALFORMED / UNKNOWN)
      — deterministic, payload-only, never sees the tool name
   ↓  effect candidates (arms A–J)
   ↓  deterministic witness: pairing → decode → json_path resolves → typed value
      equality → entity binding (call argument = result echo) → strength witnessing
      (a bare SUCCESS_ACK can never witness EXECUTED/CONFIRMED)
   ↓  FACT LEDGER: append-only FactEvents (OBSERVE / EFFECT / INVALIDATE),
      each proof-carrying (call_id, result index, json_path, authority)
   ↓  temporal queries: LATEST / PRIOR_TRUE / AT_TIME with as_of
   ↓  claim probe (§31): SUPPORTED / CONTRADICTED / PENDING / UNSUPPORTED / UNKNOWN
```

Type decisions validated by the dataset construction:

* **Truth vs SupportStatus are separate axes.** `device_replaced(17) = UNKNOWN`
  (no evidence) while the claim "device was replaced" is `UNSUPPORTED`. Absence of
  evidence is never FALSE.
* **Effect-strength lattice** `REQUESTED < INITIATED < EXECUTED < CONFIRMED`, with
  `OBSERVED` on a separate read axis; comparing OBSERVED with mutation tiers raises
  `TypeError` — the axes cannot be silently merged.
* **Authority ladder** `TOOL_SELF_REPORT < CONTRACT_GUARANTEE < READ_OBSERVATION`.
* **Proof-carrying WorldFact**: predicate, entity, value, truth, strength, authority,
  provenance (call_id, result index, exact json_path), observed_at, valid_from,
  invalidated_at. Nothing enters the ledger without a resolvable path.
* **Entity binding by argument echo** (§16): the entity must be a call argument AND
  appear in the result; a result naming a *different* id is an explicit contradiction
  (ENTITY_MISMATCH), and a result with no id-shaped content leaves the entity unbound
  (ENTITY_UNBOUND → honest UNKNOWN). Contracts that document result bindings bypass
  the echo requirement because their own join rules are checked.
* **Event sourcing** (§18): the ledger is an append-only log; LATEST/PRIOR_TRUE/
  AT_TIME are queries over it, so stale state and conflicting observations are
  retained, and `evidence_time <= claim_time` holds by construction (queries take
  `as_of`).

## 4. Frozen dataset `step2_evidence_v1`

Committed (`3bff69b0`, refined gold in `d75678dd`) **before any inference**. 73 base
cases, 6 domains (retail / airline / telecom / banking / shipping / insurance),
22 categories: read_explicit_status, mutation_poststate, generic_success_only,
async_accepted, request_creation, audit_logging, notification_sent,
mutation_failure, partial_result, later_confirmation, later_contradiction,
wrong_entity, wrong_field, result_no_echo, stale_state, repeated_mutation,
conflicting_observations, malformed_result, misleading_tool_name, renamed_tool_ids,
same_result_diff_contract, same_desc_diff_output.

* **Minimal pairs** (§26): same tool with explicit post-state vs generic success;
  request_created vs operation_completed; the same result payload under a read vs a
  mutation contract; identical descriptions with different output shapes; same value
  different entity; same entity different field; earlier vs latest observation;
  successful audit vs successful business mutation.
* **Gold** has two layers: structural reference gold (top-level scalar report fields,
  entity-echo bound, true strengths — what a perfect structure-only extractor with
  correct read/mutation knowledge could prove) and semantic gold (business predicates
  reachable only via contracts or LLM proposals). Unsupported/contradicted candidates
  are separate lists.
* **Splits**: dev 39 / calib 21 / sealed test 13; **cf_suite** 20 (one evidence source
  flipped — status value or call entity — gold flips with it); **rename_suite** 66
  (opaque `tool_###` identifiers, semantics unchanged).
* **Oracle track**: documented contracts for catalog-documented tools only
  (contract-rich), absent elsewhere (contract-poor) — the REAL track sees exactly
  what a deployed Guardian sees: name, description, input schema, arguments, results.

## 5. Arms

| Arm | Inputs | Witnessed | Role |
| --- | --- | --- | --- |
| A | name+description | no | name/description leakage baseline |
| B | +input schema | no | does documented shape suffice? |
| C | +arguments+result | no | unwitnessed LLM danger zone |
| D | result payload shape only | yes | structure floor |
| E | description+schema+arguments+result, name masked by trajectory order | no | LLM semantics without names |
| F | deterministic ontology rules over result shape | yes | automatic READ/REQUEST/MUTATE split |
| G | conservative extractive mapper (reads fully; mutations only `new_*`/status) | yes | precision-first mapper |
| H | E's proposals + deterministic witness | yes | **central hypothesis** |
| I | oracle postconditions, deterministic (contract_bound bypasses echo) | yes | ORACLE ceiling |
| J | post-layer over any base | — | later read → CONFIRMED upgrade / CONTRADICTED invalidation |

## 6. Metrics

PRIMARY: **WorldFact precision** (established ∧ gold-TRUE / established; deduplicated
by triple so event-sourced repeats don't double-count). Then recall; unsupported
effect rate (unsupported / contradicted / invented counted separately); strength
exact/over/under; provenance accuracy (call_id + json_path); temporal accuracy;
UNKNOWN-on-unsupported calibration; rename invariance; counterfactual flip rate.

## 7. Results

### 7.1 Main table (sealed test, 13 cases; dev/calib in parentheses where informative)

| Arm | WorldFact P | R | unsupported rate | strength exact | provenance | temporal |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A name+desc | 0.00 (0.00/0.00) | 0.00 | 1.00 | — | — | 0.00 |
| B +schema | 0.00 (0.00/0.00) | 0.00 | 1.00 | — | — | 0.00 |
| C full unwitnessed | 0.59 (0.65/0.69) | 0.68 (0.73/0.86) | 0.41 (0.35/0.31) | 0.54 | 1.00 | 0.00 |
| D result-only | — (—/—) | 0.00 | — | — | — | 0.00 |
| E name-blind unwitnessed | 0.70 (0.62/0.63) | 0.74 (0.70/0.79) | 0.30 (0.38/0.37) | 0.50 | 1.00 | 0.00 |
| **F structural** | **1.00** (1.00/1.00) | 0.74 (0.75/0.71) | **0.00** | 0.50 | 0.93 | **1.00** |
| G extractive | 1.00 (1.00/1.00) | 0.58 (0.55/0.57) | 0.00 | 0.55 | 1.00 | 1.00 |
| **H hybrid** | **1.00** (0.97/0.94) | **0.74** (0.66/0.61) | **0.00** (0.03/0.06) | 0.50 | 1.00 | **1.00** |
| I contracts (ORACLE) | 1.00 (1.00/1.00) | 0.47 (0.43/0.36) | 0.00 | **1.00** | **1.00** | 1.00 |

Notes: A/B/D establish nothing verifiable, so their temporal queries are all UNKNOWN
(accuracy 0.00 — they have no ledger at all); C/E likewise (unwitnessed facts never
enter the ledger). UNKNOWN-on-unsupported is 1.00 for every witnessed arm and even
for A/B (their inventions simply do not align with the specific unsupported probes);
the honest calibration signal is the combination P + unsupported rate.

### 7.2 What the witness rejects (H, sealed test)

`ENTITY_MISMATCH` ×2 (wrong-entity results), `ENTITY_UNBOUND` ×2 (results with
business state but no entity echo), `FAILURE_RESULT` ×2 (failed mutations suppressed).
On dev, the same categories plus `PATH_MISSING` (invented paths) and
`VALUE_MISMATCH` (hallucinated values) dominate — exactly the §36 taxonomy.

### 7.3 Where unwitnessed LLM invents (C, sealed test, per category)

`mutation_failure` 3/3, `generic_success_only` 2/2, `audit_logging` 2/2,
`request_creation` 2/2 — i.e. **every hard negative from §15 of the brief is
produced by the unwitnessed LLM**: business effects from failed calls, from bare
`{"success": true}`, from audit records, and completed-operation claims from
request-creation results. This reproduces the 2026-09-26 finding under controlled,
minimal-pair conditions and quantifies it (31–41% of everything it "establishes").

### 7.4 J layer (later read confirmation)

On the sealed test: 4 CONFIRMED upgrades and 2 CONTRADICTED invalidations. A
mutation self-report upgraded by a later agreeing read becomes CONFIRMED with
READ_OBSERVATION authority and the read's provenance; a disagreeing read marks the
self-report `invalidated_at` and the read wins in LATEST. No retroactive
justification: PRIOR_TRUE before the read still returns the earlier state.

### 7.5 Rename and counterfactual controls

| Control | F | I | C | E | H |
| --- | ---: | ---: | ---: | ---: | ---: |
| rename invariance | **1.00** | 0.543 | 0.60 | **1.00** | **1.00** |
| counterfactual flip rate | **1.00** | 0.917 | **1.00** | **1.00** | **1.00** |

* **C drops to 0.60 under opaque rename**: 14/35 cases change their established-fact
  set when tool names are replaced by `tool_###` — tool names are a real semantic
  leakage channel for an unwitnessed LLM.
* **E/H are invariant by construction** (masking by trajectory order makes the prompt
  byte-identical) — the check verifies the implementation, which is the point of a
  structural guarantee.
* **I drops to 0.543 because the toy contracts are name-keyed**: renaming the tool
  breaks the contract lookup. The existing vnext `ToolIdentity` (provider/version/
  schema-hash) is the correct binding — this result is a controlled demonstration of
  why name-keyed contracts are fragile.
* **Counterfactuals flip everywhere except one I case** (a contract postcondition
  whose value is pinned to the original status value — flipping the result makes the
  contract reject, which is the correct conservative behavior, but the specific probe
  expected a flip in the established set; recorded as a measurement artifact, not a
  soundness issue).

### 7.6 Claim probe (§31 diagnostic)

12/12 correct on hand-authored propositions over the full dataset:

* SUPPORTED: confirmed cancellation, active line, earlier-pending (as_of query);
* CONTRADICTED: "order cancelled" vs a later read showing pending (read wins);
* PENDING: refund/exchange request created (REQUESTED strength, not completed);
* UNSUPPORTED: generic success, audit success, notification success, wrong entity,
  no entity echo, misleading `replace_device` (request-only).

## 8. Answers to the 22 questions

**1. Which ToolResults really allow establishing world facts?**
Only results that carry an explicit business-state field (`status`, `new_status`, …)
with a resolvable json_path, a successful outcome, and an entity echo binding the
result to the called entity — or results governed by a documented contract whose
result bindings hold. Bare acknowledgements, failures, malformed text and
entity-less business state establish nothing.

**2. When is generic success insufficient?**
Always, for business predicates. In the sealed test the unwitnessed LLM converted
`{"success": true}` into business facts in 2/2 generic-success cases and 3/3
mutation-failure cases; the witness-based arms converted it in 0 cases. `success`
witnesses only that the *tool call* completed — the brief's "tool succeeded ≠
operation executed" is enforced structurally (SUCCESS_ACK is absent from the witness
map for every mutation strength).

**3. Can READ / REQUEST / MUTATE / CONFIRM be distinguished automatically?**
Partially, and the boundary is now measured. From payload shape alone, F separates
OBSERVATION-shaped reads, ASYNC_ACCEPTED (queued/processing/pending/…) and
BUSINESS_STATE self-reports at P=1.0, but it *cannot* tell a read that happens to
report a status (read-with-status classifies as BUSINESS_STATE) from a mutation
self-report — the price is strength errors (strength exact ≈ 0.5 for F/H vs 1.00
for I). The descriptions/contracts disambiguate: effect_class READ in a contract
restores OBSERVED typing (I: strength exactness 1.00). CONFIRM is not a tool class
at all — it is a *temporal* property (later read agrees), which is what arm J
encodes.

**4. How useful are tool descriptions?** As the *only* signal they are worthless for
establishing facts (A: 100% inventions; this also reproduces the 0/18 result of the
2026-09-26 description-only probe). As a *proposer* signal for a name-blind LLM that
is then witnessed (E→H) they contribute usable candidates.

**5. How useful are schemas?** Adding the input schema to the description changed
nothing (B ≡ A at 100% inventions). Output *shape* — the actual result — is what
matters. Input schemas contribute only argument names for entity fields.

**6. How useful is the actual result?** Decisive. C vs A/B: +0.59 precision and
+0.68 recall. But unwitnessed it is still unsafe (0.59/0.41); with the witness it
becomes safe (H: 1.00/0.00).

**7. Is an LLM needed for effect mapping?** Not for the extractive core: F (pure
code) matches H's sealed-test precision and recall. An LLM is useful only as a
*semantic predicate proposer* under a witness; without the witness it is a liability
(31–41% inventions), and its strength guesses are half wrong (0.50) where contracts
are perfect (1.00).

**8. Can a deterministic verifier check its proposals?** Yes — that is the central
positive result. The witness checks pairing, decodability, path resolution, typed
value equality, entity echo and strength witnessing, and its rejections are exactly
the right ones (§7.2). What it *cannot* verify is the read-vs-mutation nature of a
result and the semantic truth of a predicate label — those remain proposer risks,
bounded by precision 0.97–1.00 on dev/calib and 1.00 on the sealed test.

**9. Which false business effects remain?** On the sealed test: none for F/G/H/I.
On dev/calib H retained 2.6–5.6% unsupported before the entity-echo rule and 2.6%
after; the residual cases are junk predicates over genuine echoes
(`replacement_request.device_id`) — proposer labeling noise, not state invention.

**10. How are entity/value bindings solved?** Two-sided: the claimed entity must be
a call argument AND appear in the result (echo). A same-key result field carrying a
different id is an explicit contradiction (wrong-entity results are rejected); a
result with no id-shaped content is ENTITY_UNBOUND → UNKNOWN; contracts with
documented result bindings bypass the echo because their join is itself verified.
Value binding is exact typed equality at a cited json_path. Counterfactual entity
flips (call entity changed) make the original entity's facts vanish — flip rate 1.0.

**11. How is stale state solved?** Event sourcing: observations are never
overwritten. LATEST returns the newest observation with `conflicted_history` when
values disagreed; PRIOR_TRUE answers "was it ever true before t"; AT_TIME answers
as-of queries. `ever_approved ≠ currently_approved` is answered correctly
(airline_stale probe: SUPPORTED for "pending at some earlier point" via as_of=1
while LATEST returns the newer state).

**12. How are temporal facts stored?** As FactEvents with observed_at/valid_from/
invalidated_at on an append-only ledger; queries are LATEST/PRIOR_TRUE/AT_TIME with
an explicit `as_of`. Temporal accuracy: 1.00 for F/G/H on dev, calib and test;
0.875 for I (two stale_evidence misses from contract coverage gaps).

**13. How does later authoritative confirmation work?** Arm J: a later OBSERVE of
the same (entity, predicate) with the same value upgrades EXECUTED → CONFIRMED
(authority READ_OBSERVATION, provenance = the read); a disagreeing read invalidates
the self-report from that index and wins in LATEST. Sealed test: 4 upgrades, 2
invalidations. No retroactive justification — the upgrade carries its own
observed_at, and PRIOR_TRUE before it keeps the old strength.

**14. How rename-robust is the system?** E/H/F: invariance 1.00 (E by construction:
masking by trajectory order makes prompts byte-identical under rename; the empirical
check verifies the implementation). C: 0.60 — 40% of cases change verdicts from
names alone. I: 0.543 — *name-keyed contracts* break; the fix is the existing vnext
ToolIdentity binding (provider/version/schema hash), which this experiment now
justifies with numbers.

**15. What do counterfactual tests show?** Flip rate 1.0 for C/E/H/F: changing one
status value or one entity id in the evidence changes the established-fact set.
This is the grounding proof — the system reads the result, not its prior.

**16/17/18. WorldFact precision / recall / UNKNOWN rate?** Sealed test: H 1.00 /
0.74 / 0 unsupported; F 1.00 / 0.74 / 0; G 1.00 / 0.58 / 0; I 1.00 / 0.47 / 0.
UNKNOWN-on-unsupported 1.00 for all witnessed arms. Dev/calib numbers in §7.1 —
stable across splits, no cherry-picking (configuration frozen on dev+calib before
the test run; the only post-freeze change was two bug fixes — E/H separation and
the pending-status witnessing — applied uniformly and re-scored on all splits).

**19. Which external systems actually helped?** Conceptually: tau-bench
(state-based evaluation → authority ladder), AgentRx (auditable constraint log →
proof-carrying facts, judge over verified evidence), the evidence-tracing survey
(typed provenance graph), "When Tools Lie" (arm J pattern). No code was imported;
nothing transferred as a runnable component — consistent with the 2026-09-26 audit.

**20. Is Step 2 reliable enough for integration?** As an *evidence layer under a
witness*: yes with caveats — precision is perfect on the sealed suite, rename-proof,
counterfactually grounded, and the claim probe is 12/12. The caveats: (a) the
dataset is authored diagnostics, not real contest traces — a real-trace transfer
run is still required; (b) semantic predicate coverage (the request/exchange/refund
tier) is LLM-guessed and contract-dependent; (c) the read-vs-mutation ambiguity
caps strength exactness at ~0.5 without contracts; (d) result-born entities
(request_id/audit_id as first-class entities) are out of scope.

**21. What remains for Step 3?** Claim extraction and typing from agent messages
(Step 3 proper), mapping claims onto ledger predicates, and the final
verdict/decision layer. Step 2 hands Step 3 a queryable ledger with LATEST /
PRIOR_TRUE / AT_TIME and a probe returning SUPPORTED / CONTRADICTED / PENDING /
UNSUPPORTED — Step 3 should only need to *phrase* candidate propositions, not to
re-derive evidence.

**22. What is the main bottleneck after this phase?** Semantic coverage, in three
parts: (1) contract-poverty — without documented postconditions, REQUESTED-vs-
EXECUTED typing and business-predicate naming are guessed (recall of the semantic
gold stays at 0.47 for I and ~0.6 effective for H); (2) the read-vs-mutation
ambiguity of status-bearing results; (3) result-born entities and cross-entity
effects (an exchange request touching order + items + payment method). None of
these is safely solvable by more LLM confidence — they need either contracts
(authored or LLM-proposed-then-frozen per tool version) or accepted UNKNOWN.

## 9. Failure analysis (§36 categories, observed instances)

* **wrong effect type / overclaim (strength)**: 19–20 per split for F and H — the
  read-with-status-as-EXECUTED confusion (measured; contracts fix it: I = 1.00).
* **overclaim finality**: C on request_creation/async (completed from "created"/
  "queued"); eliminated by the witness.
* **wrong entity**: wrong-entity cases pass only when the result explicitly names
  another id — detected (ENTITY_MISMATCH); no-echo cases stay UNKNOWN
  (ENTITY_UNBOUND). Both verified by probes.
* **wrong value / wrong result pairing**: LLM path/value hallucinations rejected by
  PATH_MISSING / VALUE_MISMATCH; provenance accuracy 0.93–1.00.
* **stale evidence / wrong time**: none for F/G/H (temporal 1.00); 0.875 for I from
  contract coverage gaps.
* **contract ambiguity**: I's name-keyed contracts under rename (0.543) — fixed in
  production by ToolIdentity binding.
* **result ambiguity**: pending/queued statuses are legitimate observed states, not
  only async acceptances — the witness now allows OBSERVED from ASYNC_ACCEPTED
  results (a bug found and fixed by the claim probe: 10/12 → 12/12).

## 10. Reproducibility

* Frozen dataset + implementation commits BEFORE inference: `3bff69b0` (dataset v1 +
  module + tests), `d75678dd` (dataset v2 + E/H separation + entity-echo witness),
  `1013db74` (two bug fixes applied uniformly, all splits re-scored), `6c4db047`
  (sealed-test results + control suites).
* Runner: `experiments/searh_23/step2_evidence.py` (run / score / rename-check /
  cf-check / claim-probe); dataset builder:
  `experiments/searh_23/build_step2_dataset.py` (deterministic, seed 20260928).
* Tests: 18 unit tests (`tests/test_step2_core.py`) — taxonomy, lattice, ledger
  as-of semantics, witness rejection paths, arms, J layer, claim probe.
* LLM: Mistral `ministral-14b-latest`, temperature 0, json_object; 357 unique
  requests total (on-disk cache in `outputs/searh_23/step2_evidence_v1/llm_cache/`,
  ~300 duplicate requests eliminated); ≈170K tokens. Environment: Vast.ai RTX 3090
  (idle for this phase — API only), Python 3.12, no new dependencies.
* Cost of the phase: ~3.5 h wall clock including two mid-run code fixes; every
  prediction file carries input/output SHA-256 in its run meta.

## 11. Stop-condition review (§41)

* "LLM alone has high recall but invents effects" — confirmed (C: R 0.68 with 41%
  inventions) → not promoted as-is; only the witnessed variant advances.
* "Exact contracts work, real descriptions don't" — partly: contracts give perfect
  typing but *lower* recall (0.47) than structure (0.74); real-track H reaches
  1.00/0.74 without contracts. The oracle/real split is reported honestly.
* "Tool descriptions insufficient → UNKNOWN, not dictionary" — enforced; the
  contract-less tools in the dataset produce UNKNOWN, never guessed semantics.
* "Formal engine doesn't improve semantic accuracy → don't complicate": the ledger
  is deliberately plain Python event sourcing; no Datalog/LTL engine was needed for
  the measured queries (event-calculus-style initiated/terminated semantics emerged
  as INVALIDATE events + validity intervals). Formal backends remain a Level-2
  option if Step 1/3 need heavier temporal logic.
* "External system doesn't transfer" — fixed in §2/§19: concepts only, no code.

## 12. Level-2 priorities (next phase)

1. **Real-trace transfer**: run H/F over the 46-case `valid.parquet` trajectories
   (parsed by the existing ledger/event infrastructure) and measure precision on
   real tool catalogs, including the echo-pairing read tools.
2. **Contract acquisition**: LLM-proposed per-tool contracts frozen per tool version
   (the T2→T1 promotion question) with the same witness discipline.
3. **Result-born entities**: request_id/audit_id as first-class entities with their
   own binding rules (audit/notification categories currently score as pure hard
   negatives).
4. **Read/mutation discriminator**: a trained classifier or contract field for
   effect_class, to fix strength exactness without full contracts.
5. **Cross-entity effects** and value-preservation checks (before/after evidence
   for update policies).
