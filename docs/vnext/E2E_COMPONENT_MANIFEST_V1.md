# E2E COMPONENT MANIFEST V1

Status: PHASE_0_AUDIT_COMPLETE — integration NOT started (Goal-axis required inputs missing, see §G).
Assembly branch: `experiment/guardian-e2e-v1` (merge commit `a199252`,
first parent = integration baseline `8b0d13c1147531f4513d084ed99dc7133bfdcc92`,
second parent = policy research line tip `892093f`).
Baseline definition: spec §3 — repository `MYC-A/Guardian-of-Truth`, baseline
`8b0d13c` (= remote tip of `origin/experiment/guardian-vnext-from-0199bf9`
at audit time; the local policy line diverged from merge-base `6ab4af0`).

Evidence statuses (spec §7 vocabulary): `FRESH_MEASURED`, `DEVELOPMENT_MEASURED`,
`CONTROLLED_TESTED`, `IMPLEMENTED_NOT_E2E_MEASURED`, `HYPOTHESIS_ONLY`, `REJECTED`.
This manifest adds exactly one assembly-level status, used only for absent required
inputs (never for present code): `REQUIRED_INPUT_MISSING`.

Merged-tree verification: 1549 tests passed / 6 failed / 482 subtests passed
(`PYTHONPATH=src python -m pytest tests -q` on `a199252`). All 6 failures are
byte-state class (freeze-manifest EOL drift, content-equivalence machine-verified
by `scripts/audit_baseline_freeze_drift.py` over 28 manifests: every non-exact
entry matches its frozen hash under LF or CRLF normalization) plus one
provider-env test (`tests/test_runtime.py` mistral/cerebras key binding, requires
absent env keys). Four additional pre-existing CONTENT_DRIFT entries
(`scripts/evaluate_vnext_policy_psb.py`, `scripts/evaluate_vnext_policy_final.py`,
`scripts/policy_final_grs_dev.py` vs their earlier dev freezes) are the disclosed
post-seal runner fixes documented in PSB_RESULTS.md / POLICY_FINAL_RESULTS.md;
sealed predictions/gold were hash-verified untouched in those reports and all
14 prediction seals in the merged tree retain `gold_joined=false`.

Provider continuity (spec §81): every neural frontend below was measured on
provider `bai`, model `qwen3.8-flash` (`.env` BAI_API_KEY present; provider gate
`provider_gate_v1.json` PASSED 12/12). No silent model substitution is permitted;
a different model would constitute a separate arm/version.

---

## A. Core / proof skeleton (baseline 8b0d13c — REUSE AS-IS per spec §4/§42)

### A1. core.analyze pipeline
- exact source commit: `8b0d13c` (unchanged by the policy line; diff empty)
- source files: `src/guardian_truth/vnext/core.py`
- tests: `tests/test_vnext_core.py`, 31 controlled integration tests
  (`tests/test_vnext_integration.py` set at baseline)
- prompt/schema: none (orchestrator)
- provider/model: n/a (deterministic)
- result artifact: —
- freeze/seal: —
- evidence status: CONTROLLED_TESTED
- known limitations: Gap A (legacy `normalize(prompt, response)` source path),
  Gap B (goal frontend receives `history` + `target_action`), Gap C (baseline
  policy frontend is P1-like, not frozen H0/GRS), Gap E (operational lowering
  exact-invocation/literal-args only)
- role in E2E: the single auditable entry point; extended, not replaced

### A2. Four-valued solver + all-world enumeration
- commit: `8b0d13c`; files: `solver.py`, `proof_records.py`
- tests: `tests/test_vnext_proofs.py`, `tests/test_vnext_solver.py`
- evidence status: CONTROLLED_TESTED (exhaustive Cartesian product, `max_worlds`
  guard, no top-k — verified)
- known limitations: exact product can hit world budget; overflow maps to
  UNRESOLVED + `WORLD_BUDGET_EXCEEDED` (spec §44 behavior already implemented)
- role in E2E: REUSE unchanged; measure world explosion as a metric (spec §90)

### A3. Certificate builder + independent checker
- commit: `8b0d13c`; files: `certificates.py`, `decision.py`
- tests: `tests/test_vnext_certificates.py`, `tests/test_vnext_decision.py`
  (+ tampering tests)
- evidence status: CONTROLLED_TESTED
- known limitations: `CertificateContext`/`AuthoritativeAxis` currently hash the
  baseline axes only; new semantic axes (H0+GRS, Conservative+FR1) must be
  reflected in the hashed context (spec §51) — integration task, not rewrite
- role in E2E: REUSE + extend certificate context to admit the new axes

### A4. EvidenceLedger + indexes
- commit: `8b0d13c`; files: `ledger.py`
- evidence status: CONTROLLED_TESTED (append-only; delete/restore history
  preserved; no latest-state overwrite)
- role in E2E: REUSE AS-IS

### A5. Escalation framework
- commit: `8b0d13c`; files: `escalation.py`
- evidence status: IMPLEMENTED_NOT_E2E_MEASURED
- known limitations: OFF in primary E0–E4 comparison (spec §83)
- role in E2E: preserved, disabled for the primary experiment

### A6. Adapters (binary mapping after Core)
- commit: `8b0d13c`; files: `adapters.py`
- evidence status: CONTROLLED_TESTED
- role in E2E: REUSE AS-IS (Core stays four-valued; binary only post-Core)

---

## B. Source layer

### B1. SourceEnvelope v4
- commit: `8b0d13c`; files: `source_envelope_v4.py`, `factual_envelope_v4.py`,
  `envelope_field_certificate_v4.py`
- tests: `tests/test_vnext_source_envelope_v4.py` (one EOL-drift freeze check)
- result artifact: `outputs/vnext/source_delimiter_envelope_v4_audit_v1.json`
  (+ counterexample replay, recorded UNFIXED, not a safety pass)
- evidence status: CONTROLLED_TESTED
- known limitations: DTO/hash is not an authentication oracle (spec §13);
  trusted application premise must be declared in DESIGN
- role in E2E: primary candidate for the explicit source-owned metadata path
  (Gap A replacement)

### B2. External Source Views v6
- commit: `8b0d13c` (baseline version — includes `declared_plan_actor`, which
  the policy line never had); files: `external_source_views_v6.py`
- tests: `tests/test_vnext_external_source_views_v6.py`
- docs: `EXTERNAL_SOURCE_VIEWS_V6_BOUNDARIES.md`
- evidence status: CONTROLLED_TESTED
- role in E2E: label-free external-format projection for external corpora
  (spec §68–71 adapter path)

### B3. Legacy normalize path
- commit: `8b0d13c`; files: `normalize.py`, `normalize_source_v3.py`
- evidence status: IMPLEMENTED (baseline core path; role inference from text)
- role in E2E: RETIRED from the primary E2E path per Gap A; retained for the
  B0 replay arm only

---

## C. Factual / evidence layers

### C1. T1 trusted contract registry
- commit: `8b0d13c`; files: `tools.py`, `fixture_contracts.py`
- tests: `tests/test_vnext_t1_artifacts.py`, frozen T1 integrity check
- result artifacts: `tool_t1_freeze_v1.json`, `tool_t1_predictions_v1.json`,
  `tool_t1_results_v1.json` (16/16 applicable exact; false no-effect = 0;
  false causal confirmation = 0)
- evidence status: CONTROLLED_TESTED (frozen offline stage)
- role in E2E: the only trusted effect bridge; regressions must stay green

### C2. T2 nontrusted effect proposals
- commit: `8b0d13c`; files: `tools.py` (`propose_t2`), `stage_tool_t2_v1.py`
- result artifacts: `tool_t2_v1_{freeze,predictions,prediction_seal,results,
  failure_audit}.json` (18/18 transport/schema valid; known-true recall 1/4;
  unsafe trusted candidates 0)
- evidence status: DEVELOPMENT_MEASURED
- known limitations: NOT a trusted effect source; if enabled, proposals enter
  as world alternatives only; separate T2 on/off ablation required (spec §18)
- role in E2E: optional nontrusted layer; primary path stays T1

### C3. Identity / Binding v2
- commit: `8b0d13c`; files: `identity_aliases_v2.py`, `binder.py`
- result artifacts: `binding_temporal_v2_{freeze,predictions,prediction_seal,
  results}.json` (34/34 truth/binding/completeness; 12 expected UNKNOWN
  preserved; ambiguous duplicate names retained; 0 forced false bindings;
  0 unsupported causal proofs; 34 independent receipts valid)
- evidence status: CONTROLLED_TESTED
- role in E2E: primary identity/binding candidate (ambiguity-preserving)

### C4. Claim Graph v1 (narrow claim extraction + typed field/method bindings)
- commits: baseline `8b0d13c` + policy-line additions `claim_field_bindings_v3.py`,
  `claim_method_bindings_v5.py`, `claim_field_certificate_v3.py`,
  `claim_method_certificate_v5.py` (present in merged tree)
- result artifacts: `claim_graph_v1_{freeze,predictions,prediction_seal,results,
  source_archive}.json` (41 extension cases; per-kind F1 incl. ABSENCE 1.0,
  ATTRIBUTION 1.0, ACTION_COMPLETED 0.833, CAUSAL_ATTRIBUTION 0.857; paired
  shared-field gain mean +0.028 on denominator 109)
- evidence status: DEVELOPMENT_MEASURED (sealed run)
- known limitations: proposal layer only — a claim is never a fact (spec §37)
- role in E2E: text-view consumer for target assistant claims

### C5. Factual Invocation v3 / Native Factual v5 / External Factual Runtime v6
- commits: `8b0d13c`; files: `factual_invocation_v3.py`, `factual_envelope_v5.py`,
  `external_factual_runtime_v6.py`
- result artifacts: `native_factual_v5_dev_v1_freeze.json` (+ dev outputs)
- docs: `FACTUAL_INVOCATION_V3_BOUNDARIES.md`, `NATIVE_FACTUAL_V5_BOUNDARIES.md`
- evidence status: DEVELOPMENT_MEASURED (v5 dev), CONTROLLED_TESTED (v3/v6 units)
- known limitations: exact compatible combination for E2E must be decided in
  DESIGN (spec §38) — baseline `bind_claim` path is weaker than the v6 runtime
- role in E2E: factual evidence primary candidates (typed field evidence per §39)

### C6. Temporal Queries v4
- commit: `8b0d13c`; files: `temporal_queries_v4.py`, `temporal_certificate_v4.py`
- tests: `tests/test_vnext_temporal_queries_v4.py`
- docs: `TEMPORAL_QUERY_V4_BOUNDARIES.md`
- evidence status: CONTROLLED_TESTED
- known limitations: OBSERVED_AT_TIME vs CURRENT_STATE vs HISTORICAL_ACTION vs
  ACTION_COMPLETED vs CAUSAL_ATTRIBUTION are distinct predicates (spec §20);
  freshness/persistence not provable without contracts (timeout example §21,
  freshness example §22 semantics already encoded)
- role in E2E: REUSE AS-IS

### C7. Scoped Result Evidence v2
- commit: `8b0d13c`; files: `scoped_result_evidence_v2.py`
- tests: `tests/test_vnext_scoped_result_evidence_v2.py`
- evidence status: CONTROLLED_TESTED
- role in E2E: result-scoped observations; call/result pairing via authoritative
  identity (spec §16), no FIFO repair

---

## D. Policy frontends (standalone research CLOSED)

### D1. H0 — frozen flat frontend (THE promotion-grade frontend)
- exact chain: C-ALR reimpl freeze `377a785` → PHV1 freeze `12bec0b` →
  PSB freeze `7d055ca` → GRS Stage A freeze `01f8b20` → Policy final freeze
  `08142ac`; byte-identity machine-verified at every link
  (`parse/repair/structure/definition` match, `h0_continuity` blocks)
- source files: H0 definition + prompts + schemas in
  `scripts/evaluate_vnext_c_alr_reimpl.py` (imported byte-identical by every
  later runner); evaluator = policy v3 program space
  (`policy_v3_benchmark.py` compiler/evaluator)
- definition hash: `d7316e6f2f260c991ba6b0474aa9d20da0e0d5fc8ddc06621c08a982ad763361`
  (identical across PHV1/PSB/GRS/final freezes)
- task hashes (final freeze `identity_continuity`): parse
  `0b56f7a2...`, repair `b3cc0e29...`, structure schema `fc3b3ee2...`
- provider/model: bai / qwen3.8-flash
- result artifacts (fresh final holdout, 100 cases, 8-gram-disjoint):
  `policy_final_holdout_v1_h0_{predictions,prediction_seal,results}.json`
  — correct-definitive coverage 0.60, unsafe definitive 0.14, simple 1.00,
  capacity 0.086, NL 0.429
- freeze/seal: `policy_final_holdout_v1_freeze.json` (gold frozen before
  predictions, `gold_joined=false` in seal)
- evidence status: FRESH_MEASURED
- known limitations (carried into E2E as measured residuals): invented explicit
  permission 10–14% on unseen phrasings; relation binding (PHV1 dominant
  residual 9/21); NL prose 42.9%
- role in E2E: Policy frontend of arms E0/E2; one member of the E4 Policy axis

### D2. GRS-refined — grounder + frozen B1 synthesis + canonicalizer
- exact chain (frozen as boundary "frozen B1 prompt + canonicalizer", simplest
  successful per the frozen selection rule): grounder task
  (`policy_grs.py` inventory model + grounder contract) → frozen B1 synthesis
  prompt (`scripts/evaluate_vnext_policy_grs.py`, Stage A B1 arm) →
  deterministic canonicalizer (`policy_grs_emission.py`: RULE-wrapper-only
  token insertion, proven by token-multiset) → DSL validator → compiler into
  the shared v3 program space (field parity with frozen PSB compiler,
  test-verified)
- task hashes (final freeze `identity_continuity.grs`): ground
  `524a50ce...` (+ synth/canon recorded in freeze)
- provider/model: bai / qwen3.8-flash (2 calls/policy)
- result artifacts (fresh final holdout): `policy_final_holdout_v1_synth_*`
  and `policy_final_holdout_v1_ground_*` — cdc 0.81, definitive accuracy
  0.818, unsafe 0.02, validity 0.99, simple 1.00, capacity 0.657, NL 0.714;
  paired vs H0: 30 corrections / 9 regressions, McNemar p = 0.0011
- freeze/seal: `policy_final_holdout_v1_freeze.json` + per-arm seals
- evidence status: FRESH_MEASURED
- formal verdict: historical KEEP_H0 stands (G7 regression gate 15% > 10%);
  GRS-refined recorded on the Pareto frontier as the more-accurate/safer
  alternative — NOT promoted, but explicitly an active E2E candidate per
  spec §24–§26 (terminal decision belongs to the E2E experiment, not this audit)
- known limitations (targeted E2E mechanisms, not to be fixed in E2E V1):
  negation-in-condition; REQUIRE separate-vs-together; grounder atom misses
- role in E2E: Policy frontend of arms E1/E3; second member of the E4 Policy axis

### D3. PSB — REJECTED
- verdict chain: frozen INFRASTRUCTURE_FAILURE (validity 84.09% < 0.90 floor)
  → terminal POLICY_LIMITATION_CONFIRMED; collapsed on active-voice fresh texts
  in the final cycle (54/83 errors = invented ACTOR nodes)
- evidence status: REJECTED
- role in E2E: NONE (excluded from active path per spec §24); its permission
  gate mechanism is documented as validated-but-redundant

### D4. Shared Policy program space (v3) + evaluator
- files: `policy_v3_benchmark.py` (compiler/evaluator), v4/v5 benchmark layers
- evidence status: CONTROLLED_TESTED (H0 and GRS compile into the same space;
  composed verdict VIOLATION > PERMITTED > NO_VIOLATION)
- role in E2E: the common behavioral program space both frontends lower into;
  integration boundary per spec §28 (deterministic adapter → proof obligations,
  no second solver)

---

## E. Goal frontends (standalone research CLOSED per spec §30–§31)

### E1. Conservative Goal incumbent (from final Goal sweep)
- exact source commit: **REQUIRED_INPUT_MISSING** — no implementation, freeze,
  or sealed result exists in this environment (verified: full worktree, all
  branches, reflog 110 entries, dangling objects, `upload/`, `download/`,
  remote `origin` at audit time)
- user-reported fresh evidence (unverifiable here): validity 80.8%,
  behavioral 63.5%, correct|valid 78.6%
- provider/model: REQUIRED_INPUT_MISSING (must match measured config per §81)
- evidence status: REQUIRED_INPUT_MISSING (spec §7 vocabulary has no status for
  absent inputs; the honest classification is that the artifact does not exist
  in this environment and its numbers are user-reported)
- role in E2E (once supplied): Goal frontend of arms E0/E1; member of the E4
  Goal axis

### E2. FR1 (Rule Frames) + E5 source recovery + trusted frame assembler
- exact source commits: **REQUIRED_INPUT_MISSING** (same negative verification
  as E1; terms "FR1", "Rule Frames", "E5", "trusted frame assembler",
  "STRUCTURED_GOAL_EMISSION_LIMITATION_CONFIRMED" appear nowhere in the
  repository or its history)
- user-reported evidence (unverifiable here): dev 20/24 valid, 18/24 behavioral;
  fresh validity 80.8%, behavioral 63.5%, correct|valid 78.6%; formal verdict
  STRUCTURED_GOAL_EMISSION_LIMITATION_CONFIRMED
- evidence status: REQUIRED_INPUT_MISSING
- role in E2E (once supplied): Goal frontend of arms E2/E3; second member of
  the E4 Goal axis

### E3. Old Goal v2 frontend (baseline core path) — EXCLUDED
- commit: `8b0d13c`; files: `goals.py` (`parse_goal_plan`)
- result artifacts: `goal_plan_v1_*` (22/22 transport, 15/22 schema-valid,
  22/22 unresolved, zero definitive certificates, zero downstream binary gain)
- evidence status: REJECTED (readiness contradicted; spec §30 excludes it)
- role in E2E: NONE as active frontend; the B0 replay uses it only as the
  untouched baseline behavior

### E4. Goal v3 isolation v1/v2/v3 — REJECTED at baseline
- commits: up to `8b0d13c` (the baseline commit IS the extraction v3 rejection
  archive); files: `goal_v3_isolation_frontend_{v1,v2,v3}.py`, runners,
  scoring, semantics, user-authority/contract/certificate/execution v2,
  goal_alignment_v3 line
- result artifacts: `goal_v3_isolation_v{1,2,3}_*` sealed sets (all UNRESOLVED-
  dominated; v2 10 cases behavioral 0.0; v3 12 cases certified resolution 0.0;
  futility/accounting stops)
- evidence status: REJECTED (spec §30 excludes the Goal-v3 isolation frontend)
- role in E2E: NONE

### E5. Goal proof v2 machinery (representation, not a frontend)
- commit: `8b0d13c`; files: `goal_proof_records_v2.py`, `goal_solver_v2.py`,
  `goal_bindings_v2.py`, `goal_invocation_v2.py`, `goal_grounding_v2.py`,
  `goal_formula.py`, `goal_progress_v2.py`, `goal_certificate_v2.py`,
  `goal_call_membership_v2.py`, `goal_interfaces_v2.py`, `goal_native.py`
- docs: `GOAL_PROOF_V2_BOUNDARIES.md`, `GOAL_BINDING_V2_BOUNDARIES.md`
- evidence status: CONTROLLED_TESTED (units; independent checker imports
  neither solver nor formula compiler)
- role in E2E: candidate lowering/proof representation for Goal candidates
  (spec §34: reuse if it can carry the new Goal semantics; otherwise lower
  only supported semantics and keep explicit UNKNOWN)

---

## F. Benchmarks / corpora available for the development corpus (spec §56)

All present in the merged tree with sealed artifacts (see component entries
above for the flagship results):

| Corpus | Cases | Status | Notes |
|---|---|---|---|
| V4/V5 policy benchmarks (recovered) | 142 | DEVELOPMENT (recovered, provenance-hashed) | `policy_v4/v5_benchmark.py` |
| PHV1 holdout (now development) | 80 | FRESH_MEASURED → development after viewing | 73.75% H0 result |
| PSB causal | 44 | FRESH_MEASURED → development | binding-heavy |
| GRS Stage A | 56 | FRESH_MEASURED → development | oracle-inventory |
| GRS Stage B (built, never run) | 72 | IMPLEMENTED (frozen corpus, zero inference) | b_ namespace, disjoint |
| Policy final holdout (now development) | 100 | FRESH_MEASURED → development | KEEP_H0 cycle |
| Goal 24 dev | 24 | DEVELOPMENT_MEASURED | goal-only isolation corpus |
| Goal v3 isolation corpora (60 + v2/v3 subsets) | 60+ | DEVELOPMENT_MEASURED | gold-free source projections + behavioral gold |
| Binding v2 | 34 | CONTROLLED_TESTED | binding/temporal |
| Claim graph extension | 41 | DEVELOPMENT_MEASURED | 209-span unsupported-claim regression gold separately |
| T1/T2 fixtures | 16/18 | CONTROLLED_TESTED | |
| SourceEnvelope counterexamples | small | CONTROLLED_TESTED | recorded UNFIXED |

External benchmarks (spec §68–71) — availability probed at audit time:
- AgentDojo — located at `ethz-spylab/agentdojo` (825 stars), reachable
- tau2-bench — `sierra-research/tau2-bench`, reachable
- ToolSandbox — `apple/ToolSandbox`, reachable
- ATBench — `LiYu0524/ATbench` ("A Diverse and Realistic Agent Trajectory
  Benchmark for Safety Evaluation"), reachable
Adoption audits (repo/commit/license/format/gold provenance per spec §69) are
Phase 2 work; no dataset has been imported at this time.

---

## G. Required inputs blocking integration (spec §6 provenance rule)

Per spec §6 ("Нельзя собирать GRS или FR1 «по описанию»") the following must be
supplied as exact implementations + sealed artifacts before Phase 1 can
complete and before any E2E arm runs:

1. Conservative Goal incumbent — exact implementation, prompts, schema,
   provider/model/config, sweep freeze, predictions, results.
2. FR1 (Rule Frames) — same.
3. E5 source recovery — same.
4. Trusted frame assembler — same.
5. Goal architecture sweep freeze + predictions/results (the artifacts behind
   validity 80.8% / behavioral 63.5% / correct|valid 78.6% and the
   STRUCTURED_GOAL_EMISSION_LIMITATION_CONFIRMED verdict).

Negative verification performed (2026-09-16): worktree grep (exact terms and
word-boundary FR1/E5), all branches (`main`, experiment branch local+remote),
full object inventory (`git rev-log --all --objects`), reflog (110 entries),
`git fsck --unreachable --dangling` (clean), `upload/` (only the E2E spec,
four identical copies), `download/` (policy result bundles + the V6 C-ALR
handoff, no Goal artifacts), GitHub API + ls-remote probes. The goal_v3 line
present in the repository ended at the extraction v3 REJECTION (= the baseline
commit) with materially different results (10–12 S1 cases, behavioral 0.0,
certified resolution 0.0) than the spec's sweep numbers.

Delivery contract (any of):
- a git ref (branch/commit) in `MYC-A/Guardian-of-Truth` containing the
  implementations + sealed artifacts, fetchable by this sandbox; or
- a bundle/tarball uploaded to `upload/` with a provenance manifest (sha256
  per file + the sweep's architecture commit).

On arrival, Phase 0 continues: hash/seal verification, manifest entries E1/E2
upgraded from REQUIRED_INPUT_MISSING to their true evidence statuses, and only
then Phase 1 (integration design) begins.
