# vNext progress — protocol checkpoint

This is not the final decision. The offline T1 fixture stage has run; model
semantic stages and blind evaluation have not run.

Completed: isolated branch from 0199bf9; BAI integration imported without changing
incumbents; protocol/requirements; five controlled stage extensions; new pinned
150-case metadata-selected holdout excluding Cycle 2; separate ignored gold
storage; immutable input hashes and pre-gold prediction-seal utilities.

Stage counts: claim graph 41, policy Phi 16, Goal/Plan 22, tool semantics 18,
binding/temporal 32. The extension has partially annotated relation/duplicate-name
cases; score only explicitly annotated fields with disclosed denominators, never
invent unannotated gold. The old 209-span set supplies unsupported-claim regression
gold; the new response-only extension cannot establish unsupported truth alone.

The freeze manifest is a protocol/benchmark freeze, NOT a blind candidate freeze.
Prompts, executable schemas and final architecture commit must be separately
sealed before major evaluation. Historical BAI gate: 15/16 transport/schema,
14/15 semantic correctness conditional on valid response, one 429; a fresh gate
is still required before blind network predictions.

Implemented since the protocol checkpoint: immutable canonical types; strict
call/result normalization; append-only field observations and temporal queries;
all seven retrieval indexes and no top-k cap; ten-pass typed Claim Graph with
explicit unknown dispositions; policy candidates plus challenger with authoritative
closed-universe boundary; separate Goal/Plan parser; conditional version/hash-bound
T1 and grounded nontrusted T2; indexed Binder retaining duplicate-name ambiguity.
These are implementations with unit tests, NOT established model semantic gains.

Full project test command: `python -m pytest tests -q`: 773 passed, including
the frozen T1 result-integrity check. Proof/decision subset: 46 passed.
Machine-readable unit/integrity checkpoint: `outputs/vnext/checkpoint_checks_v1.json`
at implementation commit `694c32d`: zero integrity errors, protected incumbent HEADs
unchanged, no API requests. This is not a model-semantic or blind evaluation result.
Frozen offline T1 stage: 16/16 applicable cases exact; two missing-contract cases
NOT_APPLICABLE_T1; false no-effect=0; false causal action confirmation=0.
Real-world tool generalization and downstream gain remain NOT_ESTABLISHED.

New proof/decision checkpoint: six typed evidence primitives, four-valued implication
and exhaustive world aggregation; independent certificate checker with source
reconstruction and all-world checks; certificate-gated Core decisions and structured
diagnostics; separate audit/safety/competition adapters; three-step bounded
post-UNRESOLVED escalation preserving trusted observations/contracts and admitted
meanings. ERROR under empirical Phi carries conditional semantic assumptions;
NO_ERROR additionally needs provable semantic closure and completeness.
See `PROOF_BOUNDARIES.md` and `CORE_DECISION_BOUNDARIES.md` for exact limits.

Integrated core entry point: core.analyze now connects the frontends, operational
invocation grounding, ledger/T1/T2, indexed factual bindings, all-world solver,
certificate checker, bounded escalation and explicit product adapter. 31 new
controlled integration tests pass. Exact wrong-call/argument witnesses validate;
missing arguments, user actor substitutions, material unknown claims, unsupported
conditions/effects, ambiguous mappings and world-budget overflow remain explicit.
See CORE_INTEGRATION.md; general scalar/alias/causal lowering and automatic
escalation callback construction remain partial, not established semantic gains.

Current full project verification: 809 tests pass (the earlier checkpoint above
still records its original 773-test snapshot unchanged).

Remaining: general semantic lowering and automatic escalation orchestration;
all model semantic stage evaluations, stage integration,
regression and dev-only ablations;
candidate freeze; fresh gate; sealed blind predictions/gold join; all result JSON,
certificate JSONL, failure audit, result documents, final manifest and final decision.
The 23 requirement rows remain unverified until their authoritative evidence exists.

Frozen Goal/Plan development v1 completed: all 22 rows (11 independent semantic
inputs), 22/22 transport, 15/22 schema-valid, 22/22 unresolved, zero definitive
certificates, zero downstream binary gain over X0. Predictions were sealed before
scoring; per-case failure audit and GOAL_PLAN_RESULTS.md precede any repair.
This contradicts readiness of the current large Goal/Plan frontend/lowering,
not the full architecture objective. Semantic/schema causes remain explicit.
Current full project units: 825 passed, including five new claim-scoring checks.
Latest full verification: 828 passed after immutable Goal/Plan artifact checks
and direct claim-runner entrypoint validation. Unit/integrity checkpoint v5
records implementation 60cabfa, zero frozen-input errors and unchanged incumbents.
Claim Graph v1 fixed C2/vNext comparison is now RUNNING on all 41 extension cases.
Its first complete case has valid C2 schema and zero narrow-pass failures.
Final metrics/gold join are pending; no semantic gain is inferred from that case.

Post-audit Goal/Plan v2 development now adds exact source-ID inventory, nine
bounded semantic tasks, separate plan/order/scope/conditional clause records,
four-valued formula lowering and value-free JSON/schema diagnostics. It does not
alter the currently running Claim Graph v1 implementation or its prompts.
Current full unit verification: 912 passed, including 84 new v2 development
checks. Read-only verification of all 100 Claim Graph v1 frozen source hashes
found zero mismatches. Eight of 41 claim cases were complete at this checkpoint;
the job remains live, and no final comparison score or semantic gain is inferred.
See GOAL_PLAN_V2_DEVELOPMENT.md for unimplemented grounding/certificate integration
and the required separate freeze before a v2 model evaluation. No blind labels
were opened and no additional live request was started by these development tests.

New Goal proof development checkpoint: the Goal-layer solver evaluates every
structural clause in every supplied binding choice and certificate-gates ERROR.
The independent checker imports neither solver nor formula compiler/evaluator;
it reconstructs source/ledger and rechecks primitives, clauses and every world.
Fresh-plan progress has a distinct source-protocol premise, never an LLM estimate
or synthetic ledger effect. Only an explicitly trusted activation contract plus
a complete empty prefix establishes the initial step/bounded noncompletion.
Wrong first dispatch and skipped-step order pass independent witness validation.
Without that contract, after intervening events or with incomplete source history,
progress remains UNKNOWN. Goal-layer compliance is not full Core safety; this
development format cannot certify NO_ERROR under empirical semantic coverage.
Current full units: 939 passed, including 27 Goal proof/progress checks. All 100
Claim Graph v1 source hashes remain unchanged. Fifteen of 41 claim cases were
complete at this checkpoint; final predictions/seal/metrics are still pending.
Remaining: semantic binding generation, documented source activation adaptation,
single Core policy/claim/effect-world composition and authoritative safety closure;
then separate v2 freeze/model evaluation. See GOAL_PROOF_V2_BOUNDARIES.md.

Fresh development provider gate v1: 12/12 transport, schema and controlled
semantic microtasks; latency p50 4860.504 ms, p95 6805.173 ms; 5354 reported
tokens. A preceding connection smoke succeeded. Artifacts and per-case failure
audit are immutable; no blind inputs or labels were opened. This is not stage
quality or final blind admission evidence; see PROVIDER_GATE.md.

Latest continuation: Claim Graph v1 finished all 41 cases, with sealed predictions,
100 archived frozen source files and immutable original/detailed failure audits.
Both span detectors achieved F1 1.0 on fully annotated cases. The shared typed
gain gate failed; unavailable C2 fields and exact-surface-form limitations remain
explicit. Native transport was 409/410, all 409 received payloads schema-valid.
See CLAIM_GRAPH_RESULTS.md. This is controlled development, not blind evidence.

Goal v2 now has narrow source-owned operational binding generation and an
explicit-backend invocation entry point. Multiple permitted tools in one meaning
remain a set, distinct alternatives remain exhaustive worlds. No-plan GOAL
conformance does not imply completed goal; no fresh activation is inferred.
Extra proposition grounding, nonliteral scope, later progress, authoritative
closure and single Core composition remain incomplete. See
GOAL_BINDING_V2_BOUNDARIES.md. No new live requests or blind gold reads were made
by these implementation/audit checks.
Full project verification at this continuation: 968 tests passed; read-only
verification of all 100 Claim Graph v1 frozen source hashes found zero errors.
The new native Goal v2 stage runner freezes committed implementation and exact
request hashes, persists safe schema diagnostics, seals all predictions before
controlled gold scoring and produces per-case failure taxonomy. It uses no
invented activation contract; Goal-layer metrics are not reported as full Core.

Independent T2 stage implementation now adds an input-only fixture adapter,
raw/accepted proposal audit, exact known-true candidate metrics and actual
primitive-prover boundary checks for state/completion/causality with untrusted
effects. Twenty-four new controlled tests pass; current full project units are
992. See T2_STAGE_PROTOCOL_V1.md. The T2 network phase has not started and must
wait for the active Goal v2 process to terminate; no concurrent API batch was
started. At this checkpoint three Goal cases are complete. The second case has
two schema failures diagnosed as JSON_INVALID, not assumed semantic errors or
truncation. Native Goal v2 code/prompts remain unchanged while that job runs.

Source-owned identity development adds provider/system-scoped stable IDs,
record-group-preserving aliases, temporal full/partial snapshot handling and
name/time/entity-event indexes. Scoped result-field primitives compare typed
JSON without mixing different records, preserve binding alternatives/BOTH and
do not claim current state or causality. Thirty-four new controlled tests cover
duplicates, renames, namespaces, user-role rejection, incomplete source and
2000-record candidate/lookup behavior. Main Core/source-adapter/certificate
integration remains pending; see IDENTITY_BINDING_V2_BOUNDARIES.md. These new
modules are unused by the frozen Goal/T2 versions; no frozen source was edited.
Latest complete project verification after the source-owned identity tests:
1026 passed. This is unit behavior only, not stage or end-to-end semantic gain.

Checkpoint commits: protocol `8e9c3fb`; types/ledger `8e87649`; Claim Graph
`e69a406`; T1/T2 `9e0b2f4`; policy/Goal `f0fb124`; indexed Binder `f562c8b`;
T1 evaluator `8d2c532`; T1 pre-prediction freeze `af2e3ee`.
Proof/certificate engine `3b36b5d`; certificate-gated decisions/escalation/adapters
`694c32d`. No stage/prompt/configuration in frozen T1 v1 was changed.
