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

New P1-like Policy development preserves several grounded behavioral programs
and a separate challenger, without P2 parsing or confidence voting. Missing
atoms remain UNKNOWN; finite schemas do not close meaning. The separate
104-case observed-dev runner retains exact P1 semantic prompts/validation and
declares its common transport-envelope changes. Native and baseline requests
share a single throttle/quota stream; predictions are sealed before world
scoring. Model phase remains NOT_RUN while Goal v2 is active, with T2 next in
sequence. Joint Core atom grounding/certificates and the closed/open Phi stage
are still pending. See POLICY_PROGRAM_V2_BOUNDARIES.md. Twenty-seven controlled
frontend/wire/scoring tests pass; full project verification is 1059 passed,
not model quality or end-to-end gain. Frozen Goal/T2 source is unchanged.

Factual invocation v3 now connects original source, the deterministic C2 graph,
source-owned identity/field indexes, value-aware narrow meanings and independently
rechecked primitive receipts. It preserves numeric/scalar types, all compatible
record/result alternatives and original span dispositions. Target-forged roles
or TOOL results do not create evidence; USER/ASSISTANT source attribution is not
interchanged. Receipts certify conditional exact-field evidence, never current
state/completion/causality or a whole-Core verdict. Fifty-five new controlled checks
pass, including ungrounded relative/current time; full project verification is 1114 passed. See
FACTUAL_INVOCATION_V3_BOUNDARIES.md for missing joint Core/certificate composition
and source-adapter limitations. No frozen model-stage source was edited, no
parallel API batch was started and no blind gold was opened.

Completed native Goal v2 now has all 22 predictions sealed before scoring and
full original/supplementary failure audits. Result: 22 UNRESOLVED, no definitive
certificates; 190/190 transport and 176/190 schema-valid requests. Frozen v2
implementation/inputs/results remain untouched. T2 v1 subsequently completed
18/18 transport/schema-valid cases: known-true candidate recall 1/4, zero unsafe
trusted candidates out of 19 and zero ledger/primitive-prover pollution. Neither
stage establishes whole-Core gain. Three artifact checks validate these full
seals, source hashes, audit linkage and unchanged outcomes.

The user supplies a new Goal v3 hypothesis: goal authorization and genuinely
mandatory restrictions, not one assumed plan; independently decisive violations
may prove ERROR despite unrelated unknowns, but never an unknown decisive guard
or an interpretation-dependent violation selected pessimistically. Primary-source
review of SOP-Bench/AgentCore and component reuse audit are recorded in
GOAL_PLAN_V3_DESIGN.md. v3 is not implemented/evaluated yet; freeze fresh mechanism
checks before implementation, then freeze architecture before inference. The
already frozen Policy stage precedes v3 implementation. No blind labels opened.

Preimplementation Goal v3 mechanism specification now contains 36 controlled
cases with explicit fixture SYSTEM premises and separate reference expectations.
Four structural/reference-link checks pass; these are not a model evaluation
or independent adjudication of the expected statuses. The specification has a
separate no-API freeze command; architecture/inference freeze is still pending.
All 114 frozen T2 executable source files are byte-archived and independently
hash-checked, including the original fixture reference. The frozen Policy process
(session 61614) is verified live, with its first case complete; it remains the
only API job. No frozen source has been edited and no blind gold opened.

Independent preimplementation shipment-fixture reference now validates all 36
frozen status expectations and excludes labels/IDs/families from its execution.
It pins explicit source-premise hashes and rejects contract changes; six reference
tests pass. This is not Goal v3 inference or whole-Core evaluation. A separate
public synthetic source counterexample distinguishes safe escaped valid JSON
from an unterminated/unescaped source body that creates a false SYSTEM event in
the legacy marker parser. This remaining boundary is documented before repair;
no frozen source was changed. See GOAL_V3_REFERENCE_AND_SOURCE_AUDIT_V1.md.

New source envelope v4 replaces body-marker role inference only in its separate
explicit-adapter input path. It validates original offsets/metadata/framing,
blocks malformed JSON observations and incomplete/unknown-role history closure,
retains every ambiguous full-identity call binding and preserves target ASSISTANT
provenance. Its actual T1/scoped-field compatibility is tested. A runnable new
field entry point connects the envelope, C2, record indexes and independent v4
receipts with no implicit client. Thirty-two controlled checks pass; this is
not the joint Core or a model score. Public counterexample replay and exact
remaining source-authentication/adapter boundaries are documented in
SOURCE_ENVELOPE_V4_BOUNDARIES.md. All frozen Goal/T2/Policy source stays unchanged.

Source-backed binding v2 is now completed separately from the under-grounded
symbolic v1. Its 34 typed-query predictions are sealed before scoring: 34/34
truth/binding/completeness, 12 expected UNKNOWN preserved, both ambiguous name
bindings retained, zero false forced bindings and zero unsupported causal proofs.
All 34 independent typed receipts validate (22 definite primitive results); these
are not whole-Core certificates. The full report and per-case audit explicitly
retain native/Core/blind limitations and cached name/alias linear-scan costs.
No API requests, frozen old source changes or blind labels were involved.

The explicit scaling supplement now covers 100/1000/10000 **events**, not just
many entities: all nine controlled runs and primitive receipts pass. At 10000
events all 4998 matching method calls/9996 result-call events are retained. Index
query/build and independent receipt cost are reported separately; the count
receipt replay dominates at 9.075 s. No native/Core performance claim is made.

Native factual v5 now builds C2 once, routes attribution to source fields and
unqualified completed/absence claims to candidate source-method meanings and
all historical-ID/alias bindings, then actual T1/temporal proofs and independent
native source receipts. Nineteen controlled-backend checks pass. Model inference,
joint all-world policy/goal/certificate composition and blind gains remain pending.
Qualified count/time/causality and unsupported codecs remain explicit UNKNOWN.
Goal v2 is immutable; v3 is still deferred until Policy finishes and is audited.

Native factual v5 now has a separate frozen twelve-case executable-source dev
integration experiment at candidate f36bdf54fecd90c2cfc9829ef2fef7b804a9b690.
Four protocol/source checks pass; no model predictions or whole-Core gains are
claimed. Network admission requires the complete preceding Policy report and
linked 104-case audit. A pre-inference source check excludes a retired-name query
whose latest-alias reference differs from native historical alias semantics.

The old Policy session handle is unavailable and no matching Python process was
found. Its immutable runner is resumed as session 70770, replaying 39 completed
cases; an admitted request without captured result becomes explicit remote
UNKNOWN and is never resent. Progress reached 42/104 at this checkpoint; this is
not a terminal report or inferred liveness guarantee. Full unrestricted discovery
now passes 1227 tests, with zero recorded old frozen-source integrity errors and
unchanged protected heads (checkpoint_checks_v19.json). Whole-Core/blind and Goal
v3 implementation remain pending.

External source views v6 and their runnable native factual adapter now separate
original target assertions from attempted-call argument data. Twelve synthetic
source/runtime checks pass: role markers remain literal, source step pairing is
preserved, unknown versions cannot acquire a contract via agent-authored metadata,
and the actual ten-pass C2 runtime never sees target argument strings as factual
assertions. No dataset, blind gold or API request is accessed by this component.
The caller must supply declared-goal authority and any completeness premise;
non-call environment observations stay UNKNOWN-source, never SYSTEM. Goal/Policy
all-world composition and lowering non-call action assertions are still pending.

Checkpoint commits: protocol `8e9c3fb`; types/ledger `8e87649`; Claim Graph
`e69a406`; T1/T2 `9e0b2f4`; policy/Goal `f0fb124`; indexed Binder `f562c8b`;
T1 evaluator `8d2c532`; T1 pre-prediction freeze `af2e3ee`.
Proof/certificate engine `3b36b5d`; certificate-gated decisions/escalation/adapters
`694c32d`. No stage/prompt/configuration in frozen T1 v1 was changed.

The Policy program regression is now complete: all 104 frozen cases ran on
B.AI qwen3.8-flash and predictions were sealed before benchmark-world scoring
(`policy_programs_v1_prediction_seal.json`, gold_joined false). Transport
retained 299/312 successes and 12 UNKNOWN remote captures from interrupted
processes; none were resent, and the runner is now immutable. On the conditional
semantic subsets the fixed P1 baseline is correct on 30/50 valid-schema cases
(0.6) while the native multi-program arm reaches 0.45 any-candidate case
accuracy, 0.0 all-candidate accuracy and 0.207 per-candidate accuracy; the
paired 29-case delta is -0.5517 in favor of P1. The native arm is therefore
recorded as not beating the incumbent baseline on this observed development
regression; nothing is promoted and whole-Core/blind gains remain unclaimed.
Boundaries and telemetry are documented in
`docs/vnext/POLICY_PROGRAM_V2_BOUNDARIES.md`.


C-ALR reimplementation study (policy_c_alr_reimpl_v1, 2026-09-14): preregistered
at commit 377a7856 before any call (docs/vnext/C_ALR_REIMPL_STUDY_V1.json), run
on the recovered V5 benchmark (142 cases, sealed gold, blind inputs) with
bai/qwen3.8-flash. H0 conservative single-parse primary: 136/142 = 95.77%
behavioral accuracy, 142/142 valid structures (1 via the registered one-shot
repair), 143 requests total, predictions sealed before gold join. Stage A prime
deterministic STOP gate: 0 of 6 residual errors are reachable by the frozen
mutation catalog (recoverable share 0.000 < 0.05, oracle gain 0.0 pp < 4) ->
REJECT_EARLY; ZERO verifier requests sent per the frozen stop rule. Deterministic
failure audit: 2x UNLESS-exceptions-placed-as-conditions, 1x condition-negation
flip, 1x modality-only (permission/obligation), 2x multi-axis (provenance,
AND_NOT_EACH+scope). Machine-verified conclusion: the C-ALR hybrid
(local-mutation admission) cannot improve on H0 on this data; the conservative
parser remains the baseline; the error classes that remain require
representation-level changes, not local patches. Full record:
docs/vnext/C_ALR_REIMPL_STUDY_V1_BOUNDARIES.md.


PHV1 prospective frozen holdout (policy_phv1_holdout_v1, 2026-09-14): one
validation cycle of the UNCHANGED frozen H0 (byte-identical prompt/schema/config
to the sealed C-ALR run, continuity machine-verified at freeze) on 80 NEW
gold-by-construction policy texts (20 simple / 20 structural / 20 multi-axis /
12 NL stress / 8 ambiguity; 8-gram-disjoint from V4+V5; preregistered gates in
docs/vnext/PHV1_PREREG_GATES_V1.json frozen before inference; corpus gold frozen
and hashed before the first request; one synthetic transport smoke before the
first semantic request; predictions sealed before gold join; no judges, no
mutation catalog, 0 verifier requests). RESULT: overall behavioral accuracy
59/80 = 73.75% (Wilson 95% CI [63.18%, 82.14%]), validity 79/80 = 98.75%,
simple 95.0%, structural aggregate 72.5%, NL stress 50.0% (family collapse),
ambiguity 62.5%, invented explicit permission 10.0% (safety breach).
Preregistered verdict: REOPEN_POLICY_RESEARCH - the controlled-distribution
95.77% is predominantly an in-development-distribution effect; the conservative
permission invariant does not generalize to unseen phrasings; the dominant
residual class is relation binding (9/21), then multi-axis composition (6/21).
The viewed holdout is now development data; any repaired candidate requires a
new holdout. Full record: docs/vnext/PHV1_RESULTS.md.

PSB causal experiment (policy_psb_causal_v1, 2026-09-15): the LAST standalone
Policy architecture cycle after PHV1 (per protocol: no V8/V9/V10, hard stop
afterwards). Preregistered docs/vnext/PSB_PREREG_GATES_V1.json before any
inference: arms H0 (frozen flat, byte-identical chain C-ALR -> PHV1 -> PSB,
machine-verified) vs H1 (typed attachment graph: 6 node types, 8 edge types,
explicit polarity, deterministic per-clause compilation into the same v3
program space) vs H2 (the same sealed parse compiled with the frozen
positive-evidence permission gate); 44 fresh gold-by-construction
binding-heavy cases (8-gram-disjoint from V4+V5+PHV1; 32 H0-representable by
merge-equivalence + 12 capacity cases; machine-checked binding
discriminability); one synthetic smoke per schema; both arms sealed before
gold join; no judges. RESULT (corrected rescoring; one disclosed post-seal
fix of the paired-statistics counter, seals/gold untouched): H0 24/44 =
54.55%, H1 = H2 32/44 = 72.73% (+18.2pp, McNemar p=0.134, Newcombe CI
[+0.0, +35.0]; corrections 15 : regressions 7 = 29.2% of H0-correct);
binding micro-F1 0.820 -> 0.856 (CONDITION 0.706 -> 0.863, ACTOR 0.714 ->
0.833, CLAUSE 0.865 -> 0.891); capacity subset 0% -> 75%; exception cohort
62.5% -> 100%; multi-clause 0% -> 87.5%; multi-axis 75% -> 50%; validity H0
95.45% vs PSB 84.09% (7 model-side graph-format assimilation failures);
invented permission 22.73% -> 0% at H1 (structured extraction alone; the H2
gate fired once, clause precision 0.95 -> 1.00, behaviorally inert).
GATES: H1 binding PASS, behavioral PASS, regression FAIL (29.2% > 5%);
H2 all PASS (supported-but-redundant); primary +18.2pp >= 15pp numerically
passed but promotion requires H1 AND H2; frozen verdict field
INFRASTRUCTURE_FAILURE (validity floor 0.841 < 0.90). TERMINAL DECISION per
protocol section 62: STOP standalone Policy research; no final holdout;
POLICY_LIMITATION_CONFIRMED - integrate with the documented limitation (H0
frontend; parser errors to be absorbed downstream by abstention / UNKNOWN /
certificates / independent witnesses and measured end-to-end). Full record:
docs/vnext/PSB_RESULTS.md.
