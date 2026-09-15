# E2E V1 — Baseline Audit (Phase 0)

Spec: `GUARDIAN OF TRUTH — E2E V1` (196 sections), delivered as
`upload/Pasted Content_1789496168906.txt`.
Baseline commit: `8b0d13c1147531f4513d084ed99dc7133bfdcc92`
(remote tip of `origin/experiment/guardian-vnext-from-0199bf9` at audit time).
Assembly branch: `experiment/guardian-e2e-v1` = merge(`8b0d13c`, policy research
line tip `892093f`) at `a199252` + Phase-0 audit commit `06ae7a2`.
This document maps the REAL `core.analyze` flow at the baseline and states the
per-step input/output types, source file, trust status and known limitation
(spec §7 format). It supersedes nothing; it complements
`E2E_COMPONENT_MANIFEST_V1.md` (component provenance, 24 components) and
`E2E_COMPOSITION_V1_PHASE0_AUDIT.md` (spec-103 audit of the prior 113-section
protocol) produced in the prior Phase-0 pass on the same branch.

Historical-source status for the Goal axis (spec §176, recorded verbatim):

```
HISTORICAL_SOURCE_UNAVAILABLE   (Conservative Goal incumbent, FR1 Rule Frames,
                                 E5 resolver, trusted frame assembler, Goal
                                 sweep freeze/predictions/results — exhaustive
                                 negative search documented in
                                 E2E_COMPONENT_MANIFEST_V1.md §G)
ARCHITECTURE_CONTRACT_KNOWN     (this spec §54–§88 defines the contracts)
NEW_VERSIONED_IMPLEMENTATION_REQUIRED (goal_conservative_v1, goal_rule_frames_v1,
                                 goal_e5_v1, goal_assembler_v1 — new versions,
                                 never presented as the historical FR1/E5)
```

Per spec §177/§178 the same rule applies to any H0/GRS delta: the frozen H0
(byte-identity chain C-ALR→PHV1→PSB→GRS→final, sha256 recorded in
`outputs/vnext/policy_final_holdout_freeze.json`) and the frozen GRS
(grounder prompt, B1 prompt, DSL grammar, canonicalizer; hashes in
`outputs/vnext/policy_grs_*` freezes) ARE the historical implementations and are
reused byte-identically; no new policy frontend is authored.

---

## 1. The real `core.analyze` flow at baseline `8b0d13c`

Entry point: `src/guardian_truth/vnext/core.py::analyze(data: AnalysisInput,
backend: SemanticBackend, *, registry, policy_universe, enable_t2,
adapter_mode, max_worlds, escalation_callbacks, max_escalation_steps)
-> CoreAnalysis`.

| # | Step | Input type | Output type | Source file / function | Trust status | Known limitation |
|---|------|-----------|-------------|------------------------|--------------|------------------|
| 1 | input | `AnalysisInput` (prompt, response, policy, declared_goal, ordered_plan, allowed_scope, history, target_action, tool_metadata, tool_schemas, history_complete, completeness_basis) | — | `core.py` | EXPLICIT_PRODUCT_INPUT | legacy text-channel shape: full trajectory flattened into `prompt` string with event markers (Gap A) |
| 2 | normalization | prompt+response strings + tool identities | `tuple[LedgerEvent, ...]` | `normalize.py::normalize` → `guardian_truth.parsing.parse_events` | DETERMINISTIC_TRUSTED | authority from document channel (prompt/response) + attributes, not full SourceEnvelope v4 metadata; call/result correlation by call_id, ambiguous pairing kept `AMBIGUOUS` |
| 3 | evidence ledger | events + history_complete + completeness_basis | `EvidenceLedger` (+`LedgerIndex`) | `ledger.py::EvidenceLedger.from_events`, `observations()` | DETERMINISTIC_TRUSTED | append-only; observations = flattened result payloads only (assistant/user text is never an observation) |
| 4 | T1 trusted effects | registry `ContractRegistry` + (call,result) pairs | `ToolSemantics` (trusted `EffectRecord`s) | `tools.py::evaluate_t1` | DETERMINISTIC_TRUSTED | requires versioned `TrustedContract`; absent contract → UNKNOWN_EFFECT |
| 5 | T2 neural effect candidates | call/result + backend + schema | `ToolSemantics` (POSSIBLE_EFFECT) | `tools.py::propose_t2` | NEURAL_CANDIDATE (never fact) | only when no T1 contract; effects retained as interpretation worlds, never as facts |
| 6 | claim graph | response text + backend (10 narrow passes) | `ClaimGraph` (`TypedClaim`s + relations) | `claims.py::build_claim_graph` | NEURAL_CANDIDATE + DETERMINISTIC span inventory | claim parser never sets truth; 10 LLM passes per response; disposition UNKNOWN_SEMANTICS blocks |
| 7 | Policy parse | policy text + backend (+ optional `ClosedUniverse`) | `PolicyHypotheses` (`EvaluationHypothesis` ×≤8 with challenger) | `policy.py::parse_policy` | NEURAL_CANDIDATE | baseline P1-like frontend — NOT the frozen H0/GRS (Gap C); challenger adds missing readings, never closes semantics |
| 8 | Goal/plan parse | declared_goal + ordered_plan + backend + **history + target_action** | `GoalPlanHypotheses` | `goals.py::parse_goal_plan` | NEURAL_CANDIDATE | **Gap B: firewall violation — receives history + target_action**; E2E V1 replaces with Conservative/RuleFrames behind a firewall |
| 9 | operational grounding | each hypothesis + normative text + ledger + tool catalog + backend | `OperationalBindings` (`OperationalChoice` with `TARGET_CALL_MATCH` atoms + `ArgumentConstraint`s) | `grounding.py::bind_evaluation_hypothesis` | NEURAL_CANDIDATE + DETERMINISTIC validation (literal grounding, scope equality) | Gap E: exact-invocation + literal-argument lowering only; hypotheses with conditions/exceptions → UNSUPPORTED (kept OPEN → UNRESOLVED); **no ATTEMPT/EFFECT level choice** |
| 10 | claim binding | each verifiable claim + ledger | `ClaimBinding` (alternatives over exact identities) | `binder.py::bind_claim` | DETERMINISTIC_TRUSTED | same-name/different-ID → ENTITY_AMBIGUOUS (never collapsed); time binding for NOW claims |
| 11 | axes/worlds | groups of choices (policy, goal_plan, per-claim bindings, T2 effect alternatives) | `tuple[InterpretationAxis, ...]`, exact Cartesian `WorldPlan`s ≤ `max_worlds` | `core.py` (product), `proof_records.py` | DETERMINISTIC_TRUSTED | budget overflow → `WORLD_BUDGET_EXCEEDED` → UNRESOLVED (no top-k) |
| 12 | proof | worlds + ledger + registry | `SolverResult` (per-world `WorldProof`, 4-valued error) | `solver.py::solve`, `proof_evidence.py::prove_atom` | DETERMINISTIC_TRUSTED | material implication over conjunctive conditions; per-world error = ¬conjunction(obligation safety); independent violation wins even with unrelated UNKNOWN |
| 13 | certificate + decision | solver result + `CertificateContext` | `CertifiedCoreResult` (status, certificate, check) | `decision.py::decide`, `certificates.py::make_certificate/check_certificate`, `solver.py::make_certificate` | DETERMINISTIC_TRUSTED | definitive without valid certificate impossible (constructor-enforced); invalid certificate → UNRESOLVED; PROVED_NO_ERROR requires closure assumptions incl. provably-closed semantic axes |
| 14 | escalation | escalation state + callbacks | possibly refined state | `escalation.py::escalate` | DETERMINISTIC (callbacks explicit) | OFF for E2E arms (spec §158) |
| 15 | adapter | `CertifiedCoreResult` | `ProductDecision` (core_status, binary_label, used_fallback) | `adapters.py::adapt` | DETERMINISTIC_TRUSTED | UNRESOLVED never binary 0 as proven safe; AUDIT mode → label None |

Baseline behavioral invariants verified by controlled tests
(`tests/test_vnext_core.py` 31 cases, `tests/test_vnext_solver.py`,
`tests/test_vnext_certificates.py` tampering suite, `tests/test_vnext_decision.py`):
append-only ledger; USER_ACTION ≠ ASSISTANT_ACTION (actor equality checked in
`prove_atom`); CALL_ATTEMPTED ≠ ACTION_COMPLETED (separate `AtomKind`s,
completed requires trusted effect with `causal_action_confirmed`);
FAILED_CALL ≠ SUCCESS/NO_EFFECT (`evaluate_t1` failure_semantics; T2 candidates
never facts); CLAIM ≠ OBSERVED_FACT (claims only create factual-consistency
obligations proven against observations); UNKNOWN ≠ FALSE (4-valued truth
lattice); NOT_FOUND ≠ ABSENT (absence requires `AbsenceScope` with closed
universe + complete history); OBSERVED_AT_TIME ≠ CURRENT_STATE (TimeMode +
LATEST_OBSERVATION); NO_VIOLATION ≠ PERMITTED (v3 program semantics);
PERMISSION ≠ OBLIGATION (v3 semantics + goal conservative contract).

## 2. Late experimental findings that must be reproduced architecturally

From the sealed policy-line results (all numbers machine-verified by
`scripts/verify_grs_results.py` 38/38 and the policy-final revalidation 27/27;
seals `gold_joined=false` at prediction time):

1. **Closed leaf vocabularies eliminate hallucinated semantic content.**
   GRS Stage A: invented permission 21.4%→0%, hallucinated leaves 0 across all
   persisted outputs; final holdout: C2 GRS-refined unsafe-definitive 2% vs H0
   14%, zero hallucination, 2 calls/policy.
2. **Format-serialization burden, not semantic reasoning, breaks small models
   on structured Policy representations.** All 5 GRS Stage A DSL-invalid
   outputs and all 5 H0-correct regressions were ONE systematic
   `RULE(...)`-wrapper omission; the deterministic canonicalizer
   (`policy_grs_emission.py`) recovered all 5 with 0 semantic changes.
3. **Retention is a downstream mechanism, not a frontend.** H0/GRS union on the
   final holdout: 90/100 vs H0 60/100 — but as a frontend union it must appear
   as an interpretation AXIS (all-world semantics), never as vote/judge.
4. **Flat H0 cannot represent per-clause structure.** Capacity classes
   (per-clause modality/actor, separate-vs-together) 0% under H0 vs 100% under
   GRS on Stage A; the same limitation motivates RuleFrames on the Goal axis.
5. **PSB-style graph emission is not promotion-grade** (ACTOR-overbinding
   channel, 54/83 errors on active-voice fresh texts) — excluded from E2E arms.

E2E V1 therefore: Policy axis = {frozen H0, frozen GRS-refined
(grounder+B1+canonicalizer)}, Goal axis = {new Conservative v1, new
RuleFrames+E5+assembler v1}, both compiled to the shared v3 behavioral program
space (policy) / canonical goal contract space (goal), alternatives retained as
interpretation axes, decisions certificate-gated by the existing Core.

## 3. Interfaces to reuse unchanged (spec §6 "do not build a second solver")

- `solver.py`, `proof_records.py`, `proof_evidence.py`, `decision.py`,
  `certificates.py` (extended context only), `ledger.py`, `normalize.py`,
  `binder.py`, `tools.py` (T1/T2), `claims.py`, `adapters.py`,
  `escalation.py`.
- Frozen policy frontends: `scripts/evaluate_vnext_c_alr_reimpl.py`
  (PARSE_TASK/REPAIR_TASK/STRUCTURE_SCHEMA = H0),
  `policy_grs.py` (grammar/validator/compiler/grounder tasks),
  `policy_grs_emission.py` (canonicalizer), `policy_v3_benchmark.py`
  (shared program space + `evaluate_v3_program` + distinguishing-world
  machinery).
- Lower-layer sealed components wired by the e2e source adapter where their
  interfaces admit it: SourceEnvelope v4 (authority metadata model),
  Identity/Binding v2, Scoped Result Evidence v2, Temporal v4 query surface —
  consulted for semantics; the E2E ledger remains the baseline
  `EvidenceLedger` (the sealed layers are evaluation harnesses of their own
  stages, not drop-in Core replacements; where their semantics disagree with
  the baseline proof layer, the baseline proof layer governs and the delta is
  documented in `E2E_V1_SEMANTICS.md`).

## 4. Gaps A–E (carry-over, addressed by E2E V1 in `core_v1.py`)

- Gap A (legacy source path): E2E source adapter constructs the trajectory
  text channels with explicit role/actor markers and supplies
  `tool_metadata`; authority stays metadata-driven (spec §8–§10).
- Gap B (goal firewall): new goal frontends receive ONLY the firewall-safe
  USER/SYSTEM source projection (spec §55–§56); metamorphic firewall test is
  a mandatory dev test (spec §116).
- Gap C (baseline policy frontend): replaced by frozen H0/GRS behind
  `policy_composition_v1` (spec §51–§53).
- Gap D (factual layers sealed but unwired): T1 registry is the wired trusted
  path; T2 remains the only neural effect channel (spec §14–§15).
- Gap E (lowering expressiveness): `world_integration_v1` lowers conditional
  rules (WHEN/ONLY_WHEN/IFF/EXCEPT/BEFORE/AFTER/ACTOR) into obligations with
  conjunctive condition atoms over `OBSERVED_STATE`/`CALL_ATTEMPTED` evidence,
  ATTEMPT/EFFECT target levels as binding-axis alternatives (spec §85–§88).

## 5. Baseline test state on the assembly branch

Prior Phase-0 verified run on `a199252`: 1549 passed / 6 failed / 482 subtests
(failures = documented EOL/env class, machine-classified by
`scripts/audit_baseline_freeze_drift.py`). Re-verified on `06ae7a2` in this
Phase 0 pass (results recorded in `E2E_V1_WORKLOG.md`).
