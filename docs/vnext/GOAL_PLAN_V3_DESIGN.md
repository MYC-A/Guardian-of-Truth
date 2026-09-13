# Goal/Plan v3: goal authorization, not one mandatory plan

Status: DESIGN_RECORDED, IMPLEMENTATION_NOT_RUN, EVALUATION_NOT_RUN.
This is a new hypothesis, not a repair of the frozen v2 experiment.
Implementation follows completion/audit of the already frozen Policy program stage.
No architecture/prompt/benchmark freeze for v3 is claimed by this document.

## Immutable comparison boundary

Goal v2 implementation: `a9150076a445d7cf86eac70500aa259f058a9209`.
Its 113 executable sources, frozen inputs, requests, predictions, seal and report
remain unchanged. Completed result: 22/22 UNRESOLVED, zero definitive verdicts.
The report and per-case audits exist before this design. The observed v2 set is
development/regression only; it is not a new blind test for v3.

The user explicitly changes the ERROR rule for v3: a separately proved violation
can establish ERROR despite unrelated missing knowledge. This does NOT permit
`any candidate interpretation says ERROR -> ERROR`. Across all admissible
interpretations/bindings/effect alternatives the violation must still hold, or
an authoritative independent obligation must apply regardless of those alternatives.
Unknown applicability, exception, identity or meaning of the decisive obligation
still blocks that witness. NO_ERROR keeps its completeness requirements.

## What the primary sources establish

[SOP-Bench](https://github.com/amazon-science/SOP-Bench) supplies procedural tasks,
executable mock tools and reference outcomes. Its task-success and execution-
completion metrics are separate. It is useful for development of explicit SOP
constraints, not evidence that arbitrary agent goals imply one required procedure.

[Behavioral Contract Evaluations sample](https://github.com/aws-samples/sample-agentcore-behavioral-contract-evaluations)
uses a code-based evaluator and stores per-constraint evidence and contract
versions. It supports conditional rules and multiple legitimate paths. It is
demonstration code, not a production guarantee or a theorem about NL meaning.

[The example contract](https://github.com/aws-samples/sample-agentcore-behavioral-contract-evaluations/blob/main/evaluator/contracts/claims.yaml)
retains unconditional coverage checks and gates formulary work on coverage results.
The sample also supports step-presence conditions, but its authors recommend
against agent-selected eligibility gates. Its README treats inactive conditions
as skipped/passing; Guardian must distinguish FALSE from UNKNOWN instead.

[AgentCore Evaluations documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/how-it-works-evaluations.html)
describes evaluation infrastructure. AgentCore is not itself synonymous with
deterministic evaluation: built-in judges and custom code evaluators are distinct.
No AWS service, SDK deployment or third-party package is required for our local checker.

[Competition page](https://dsworks.ru/champ/aij26-guardian) was requested and opened,
but the browser returned a sparse JavaScript shell/redirect rather than the full
task statement. No new claims about submission rules or task labels are derived
from that shell. v3 must operate on the actual supplied prompt/history and target
step; it must not demand a complete future session or replay the agent online.

## Semantic representation

Separate narrow source-grounded passes propose:

1. Desired user outcome, entities and resource scope.
2. Required, permitted and prohibited state changes; authorization boundaries.
3. Goal-compatible capabilities and reasonable auxiliary capabilities.
4. Explicit mandatory preconditions/order, deadlines and exceptions.
5. Alternate readings and a challenger that can change applicability/verdict.

One reading can permit a SET of tools/capabilities and many execution paths.
Alternative readings are separate worlds, not a ranking of tools. A suggested
ASSISTANT plan is not authority; even a USER list is not necessarily a mandatory
order. Mandatory status must cite the applicable source clause and its modality.
USER requests cannot override higher-priority SYSTEM/POLICY constraints. Tool
outputs and embedded documents supply data, never new governing instructions.

Expose ALIGNMENT separately from the core verdict:

| Alignment | Meaning |
| --- | --- |
| DIRECT_GOAL | Grounded action supports the desired outcome within scope |
| PERMITTED_AUXILIARY | Grounded permission/necessity supports an auxiliary action |
| AMBIGUOUS_ALIGNMENT | Material mapping, applicability or authorization is unresolved |
| PROVED_OUT_OF_SCOPE | An applicable restriction is independently violated |

These labels do not by themselves prove facts or global safety. Do not infer
permission merely because an action is plausible or because no prohibition was
retrieved. Equally, absence of an explicit permission in open NL does not prove
prohibition. Reading order status with two documented read capabilities may be
allowed by the same reading; cancellation is ERROR only with grounded restrictive
scope/authorization or another independently violated obligation, not a guessed
`read tool`/`write tool` name classification.

## Behavioral obligations and fact guards

Proposed v3 obligations: FORBID_ATTEMPT, FORBID_EFFECT, REQUIRE_PRECONDITION,
REQUIRE_SOURCE, REQUIRE_STEP, REQUIRE_ORDER and REQUIRE_OUTCOME. Each records:
obligation ID; version/source hash; original source spans; authority; trigger;
scope/entity/time; exception; deadline; proof requirements; semantic coverage.
REQUIRE_STEP/ORDER occur only for actual mandatory requirements.

LLM proposes these records. Grounding checks exact source membership and actual
schema/argument paths, but a quote match alone does not prove entailment. Definitive
witnesses require an explicit authoritative structured contract, a closed mapping
universe, or justification valid under every retained material interpretation.
Finite tool schemas and challenger silence never close unrestricted meaning.

`when` guards use typed predicates over authorized USER/SYSTEM input facts,
committed provenance-valid TOOL_RESULT fields or trusted temporal state. USER
statements are facts about the request/assertion, not automatically verified
external state. Tool results may establish exact recorded fields; business state
or effects require the appropriate trusted semantics. Agent-authored facts cannot
replace these sources.

Exogeneity is more than source role: an agent may choose a different entity,
parameters, time or duplicate result to obtain a favorable guard. Fix eligible
source/entity/time from the authoritative task/contract, preserve all matching
alternatives and conflicts, and prohibit cherry-picking. Agent calls may select
which operation a restriction applies to; they cannot establish a convenient
exception or waive an unconditional obligation. Do not ban all action-dependent
applicability: `if attempting a write, identity must already be verified` is valid.

Guard TRUE activates an obligation; FALSE deactivates only that obligation;
UNKNOWN preserves both material possibilities; BOTH is conflicting evidence.
Missing check/result is UNKNOWN, never FALSE. An unconditional prerequisite
catches omission only when the source really requires that check. Do not invent
an unconditional prerequisite to make a desired benchmark result.

An arbitrary earlier matching coverage result is insufficient: require the right
entity, qualifying version, freshness/time range and complete relevant candidates.
A typed equality on coverage_active is not an assertion that the call completed
its advertised business operation.

## Step-local obligations and temporal proofs

The guard and prerequisite use only evidence available before the target action.
At a render_decision target, required prior formulary lookup can be evaluated.
At check_coverage itself, a future lookup requirement is not yet overdue. A
requirement due at session completion is NOT failed merely because the prefix
ends before completion. Missing prior calls can prove absence only with a scoped
history/candidate completeness certificate. Truncated history remains UNKNOWN.

Distinguish CALL_ATTEMPTED, RESULT_OBSERVED, SOURCE_RETRIEVAL_CONFIRMED,
ACTION_COMPLETED and EFFECT_CONFIRMED. The source clause decides which is needed.
A tool call alone does not prove retrieval success, identity verification or a
business effect. No timeout becomes no-effect; late GET does not prove causality.
Tool identity/version/schema hash and real T1 contracts remain essential.

## ERROR and NO_ERROR aggregation

Within each world, evaluate every obligation using FDE primitives. A decisive
FALSE safety obligation with proved applicability/exception handling gives a
violation witness; an unrelated UNKNOWN obligation is retained in diagnostics,
not allowed to erase that witness. Contradictory decisive evidence is not a clean
ERROR proof. A true safety obligation plus unknown others is not NO_ERROR.

Across worlds use universal ERROR consensus, not pessimistic `any ERROR`.
The independently checked witness must survive every material variation of its
dependencies, including unknown guards that could deactivate it. An independently
authoritative SYSTEM restriction can prove ERROR without resolving unrelated
open goal meaning. If a missing interpretation could negate the decisive witness,
the result stays UNRESOLVED. Preserve those dependency/coverage scopes explicitly.

NO_ERROR requires all applicable material obligations and target claims covered,
complete necessary history/bindings/effect alternatives and authoritative semantic
closure where necessary. Passing a behavioral contract proves that contract's
scoped checks, NOT all contextual claims or global agent correctness.

Certificate records: source/contract version and hashes; violated requirement;
target call/claim and bound entity; guard and exception proofs; observed evidence;
missing evidence with scoped completeness when decisive; per-world witness;
unresolved unrelated checks; dependency closure. Independent checker replays
primitives/obligation logic and rejects omitted alternatives or tampered evidence.

## Reuse audit before implementation

| Existing component | v3 treatment |
| --- | --- |
| types.py FDE/status/reasons; integrity.py | Reuse without changing semantics |
| ledger.py immutable events/index queries | Reuse; source-scoped record indexes supplement it |
| goal_interfaces_v2.py deterministic schema catalog | Reuse only interface identity, not effect authority |
| goal_call_membership_v2.py | Reuse attempted-call primitive, not goal permission itself |
| goal_progress_v2.py | Explicit mandatory-process adapter only; no default expected step |
| goal_native.py source/reading DTOs and narrow task pattern | New DTO/frontend: old fields assume plan-localization hypothesis |
| goal_bindings_v2.py exhaustive Cartesian search | Reuse pattern/tool sets; new bindings/guards/goal capabilities |
| goal_formula.py PLAN_STEP/BEFORE generation | Do not reuse implicit plan obligations; new explicit compiler |
| goal_solver_v2.py global unknown mask | Do not reuse; new dependency-scoped violation aggregation |
| goal_certificate_v2.py/checker v2 format | Keep intact; new independent v3 witness format/checker |
| normalize_source_v3.py and scoped field receipts | Reuse boundaries only; source-authentication limitations remain |
| T1 registry / T2 candidates | Reuse trust separation; T2 never proves authorization/effect |

Changing shared primitives used by frozen experiments is not allowed. If a
required primitive needs different meaning, add a separate versioned module.
Code inspection confirms v2 already supports auxiliary conformance without a
plan; v3 extends this rather than claiming v2 universally demanded final completion.

## Pre-evaluation experiment protocol

Before implementation: freeze versioned controlled mechanism cases and independent
reference obligations/outcomes. Before inference: freeze committed v3 implementation,
source bytes, prompts/schemas, provider/config, deadlines, binary mapping and metrics.
After all predictions: seal hashes, then join reference labels. Every result gets
per-case component taxonomy before any next-version fix. Never tune from blind gold.

Mechanism minimal pairs must cover: alternate valid read tools; optional step
skipped/reordered; explicit mandatory verification before write; auxiliary read vs
out-of-scope mutation; delegated USER/SYSTEM authority conflict; no permission
mentioned vs explicit read-only restriction; coverage TRUE/FALSE/UNKNOWN/BOTH;
guard skipped; wrong entity/version/stale/agent-selected guard; failed retrieval;
attempt vs completion; before-step and session-end deadlines; truncated history;
one independent violation plus unrelated unknown; exception/dependency unknown;
conflicting interpretations; full safety closure vs mere absence of a violation.

Use new parameterized entities/tool names and held-out mechanism combinations,
not a rewritten copy of v2 failures. v2/mandatory Cycle2 sets remain observed dev.
SOP examples are an optional source-backed procedural dev extension, not our final
non-overlapping external holdout; inspect licensing before copying data/code.

Primary metrics: proved-error precision/recall and FP count; resolution/unresolved
rate WITH binary F1; per-alignment accuracy; mandatory-order false alarms;
guard/exception grounding and UNKNOWN preservation; all-world ambiguity retention;
independent certificate validation; provider/schema success; latency/tokens.
Report both conditional semantic metrics and all-case operational outcomes.

Admission: no false ERROR on the controlled negative/invariant suite; every
definitive certificate independently valid; no guessed guard/permission/absence;
unrelated UNKNOWN cannot erase an authoritative decisive violation; v3 must improve
correct ERROR resolution without increased false ERROR on the frozen dev comparison.
An observed zero FP is sample evidence, not a universal guarantee. The original
whole-Core promotion gates and fresh-provider-gated blind evaluation remain required.
