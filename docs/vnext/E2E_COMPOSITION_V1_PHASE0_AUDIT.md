# E2E COMPOSITION V1 — PHASE 0 AUDIT (spec §103 first deliverable)

Audit date: 2026-09-16. Audited by: direct code reading at the integration
baseline + machine verification of the assembled E2E branch.
Baseline: `8b0d13c1147531f4513d084ed99dc7133bfdcc92`.
E2E assembly branch: `experiment/guardian-e2e-v1` (merge `a199252` =
baseline + policy research line `892093f`).
Full component inventory with hashes/seals/evidence statuses:
`E2E_COMPONENT_MANIFEST_V1.md`.

---

## CURRENT CORE
===============

Machine-confirmed exact flow of `guardian_truth.vnext.core.analyze` at
`8b0d13c` (file `core.py`, 204 lines, read in full; unchanged by the policy
line — diff empty):

```
AnalysisInput(prompt, response, policy, declared_goal, ordered_plan,
              allowed_scope, history, target_action, tool_metadata,
              tool_schemas, history_complete, completeness_basis)
→ normalize(prompt, response, tool_identities)          # Gap A: legacy text path
→ EvidenceLedger.from_events(...)                        # append-only
→ LedgerIndex
→ per result event: evaluate_t1(registry, call, result)  # trusted effects
   else propose_t2(...) if enable_t2                     # nontrusted proposals
→ build_claim_graph(response, backend)                   # text view (claims)
→ parse_policy(policy, backend, universe, context)       # Gap C: P1-like + challenger
→ parse_goal_plan(declared_goal, ordered_plan, backend,
                  history, target_action, allowed_scope) # Gap B: sees target_action
→ per policy/goal hypothesis:
    bind_evaluation_hypothesis(...)                      # Gap E: exact-invocation +
                                                          # literal-arg lowering only
→ per claim: bind_claim(...) → entity/time alternatives
→ T2 nontrusted effect candidates → extra axes (never facts)
→ groups = [policy axis] + [goal axis] + [claim binding axes] + [effect axes]
→ required_worlds = Π len(axis.choices)
→ if required_worlds <= max_worlds:
      exact Cartesian product → WorldPlan[] (each with obligations)
  else: WORLD_BUDGET_EXCEEDED → no top-k (verified in code)
→ ProofProblem → solve()                                 # 4-valued, material implication
→ make_certificate() → check_certificate()               # independent checker
→ decide()                                               # certificate-gated;
                                                          # checker reject → UNRESOLVED
→ escalate(...) [steps=0 by default; OFF for primary]
→ adapt(mode=AUDIT/SAFETY/COMPETITION)                   # binary only after Core
```

Four-valued decision boundary verified: PROVED_ERROR / PROVED_NO_ERROR /
UNRESOLVED / INCONSISTENT; `consensus()` requires all-worlds TRUE (resp. FALSE)
for definitive, ANY BOTH → INCONSISTENT, incomplete space or ANY UNKNOWN →
UNRESOLVED. NO_ERROR asymmetrically requires, in addition to the certificate:
MATERIAL_RESPONSE_COVERED, SOURCE_HISTORY_COMPLETE, BINDING_SPACE_COMPLETE,
SEMANTIC_SPACE_PROVABLY_CLOSED (checker code read in full; matches spec §49).

Baseline test suite at `8b0d13c`: 1484 passed / 6 failed / 482 subtests.
Merged E2E branch: 1549 passed / 6 failed. All failures are byte-state EOL
drift (content-equivalence machine-verified) or provider-env class; zero
functional failures. 14 policy-line prediction seals intact, all
`gold_joined=false`.

Confirmed baseline gaps (all five verified in code, spec §5):
- Gap A: source path = `normalize(prompt, response)` role inference; the
  stronger source-owned layers exist but are NOT in the core path.
- Gap B: `parse_goal_plan` receives `history` and `target_action`
  (core.py lines 94–95) — the anti-causal Goal boundary; metamorphic
  invariant of spec §33 currently VIOLATED by construction.
- Gap C: baseline policy frontend is the P1-like + challenger parser, not the
  frozen H0 / GRS composition.
- Gap D: Identity/Binding v2, Scoped Result Evidence v2, Factual Invocation
  v3, Native Factual v5, External Factual Runtime v6, Temporal Queries v4 all
  exist as sealed/tested modules outside `core.analyze`.
- Gap E: `bind_evaluation_hypothesis` supports exact target invocation +
  literal argument constraints only; conditions/exceptions/completed-effects
  are returned UNSUPPORTED (reason POLICY_OPEN_SEMANTICS / GOAL_PLAN_AMBIGUOUS)
  — honest boundary, no regex fixes present.

---

## REUSE AS-IS
==============

- Core pipeline skeleton `core.analyze` (extended, not rewritten; no second
  Core — spec §3/§8).
- Four-valued solver + exact Cartesian world enumeration + max_worlds guard
  (spec §42–§44 semantics already implemented).
- Independent certificate checker + certificate-gated decision (spec §50).
- EvidenceLedger (append-only; delete/restore history preserved).
- Temporal Queries v4 (OBSERVED_AT_TIME vs CURRENT_STATE vs HISTORICAL_ACTION
  vs ACTION_COMPLETED vs CAUSAL_ATTRIBUTION predicates distinct).
- Identity/Binding v2 (ambiguity-preserving; 34/34 controlled).
- T1 contract registry (only trusted effect bridge; 16/16).
- Adapters (binary mapping post-Core; audit/safety/competition modes).
- Escalation framework (kept; disabled in primary E0–E4 comparison).
- Shared Policy v3 program space + evaluator (both H0 and GRS compile into it;
  single-solver invariant preserved).

## REPLACE / UPGRADE
====================

- Source path: legacy `normalize(prompt, response)` → explicit source-owned
  metadata path (SourceEnvelope v4 + External Source Views v6 as primary
  candidates; Gap A). DESIGN must define what counts as a trusted application
  premise (spec §13) — the envelope DTO is not an authentication oracle.
- Goal frontend boundary: remove `history`/`target_action` from the Goal
  input; Goal interpretations must be computed BEFORE the target action with
  the metamorphic invariant of spec §33 enforced by an integration test.
- Factual/claim path: baseline `bind_claim` path → the strongest compatible
  factual combination (Factual Invocation v3 / Native Factual v5 / External
  Factual Runtime v6 / Scoped Result Evidence v2 / claim field+method
  certificates) — exact combination to be fixed in DESIGN (spec §38).
- Certificate context: extend `CertificateContext`/`AuthoritativeAxis` so the
  certificate hashes which interpretations were admitted/merged/discarded and
  which worlds were evaluated (spec §51) — extension of the existing checker,
  not a second checker.
- Policy lowering: exact H0/GRS program → deterministic adapter → existing
  proof obligation representation (InterpretationAxis + Obligation +
  ProofAtom/supported formula structure), with losslessness criteria per
  spec §28 (per-clause modality, conditions, exceptions, negation,
  separate/together). No second solver.
- Goal lowering: FR1/Conservative candidates → existing Goal proof v2 /
  clause records / plan progress representations if they carry the semantics
  losslessly; otherwise lower only supported semantics and keep explicit
  UNKNOWN (spec §34).

## IMPORT FROM LATE EXPERIMENT
==============================

H0 (exact frozen final):
- Implementation: H0 definition/tasks byte-identical along the machine-verified
  chain C-ALR `377a785` → PHV1 `12bec0b` → PSB `7d055ca` → GRS `01f8b20` →
  final `08142ac`; definition sha256
  `d7316e6f2f260c991ba6b0474aa9d20da0e0d5fc8ddc06621c08a982ad763361`.
- Fresh sealed evidence: final holdout 100 cases — cdc 0.60, unsafe 0.14,
  simple 1.00, capacity 0.086, NL 0.429. Provider bai/qwen3.8-flash.
- Import action: adapter from the H0 program output into InterpretationAxis +
  Obligation + ProofAtom structure; H0 prompt/schema/model/config frozen.

GRS (exact refined chain):
- Implementation: grounder → frozen B1 synthesis prompt → deterministic
  canonicalizer (`policy_grs_emission.py`; RULE-wrapper-only insertion proven
  by token multiset) → DSL validator → compiler into the shared v3 program
  space (parity with frozen PSB compiler test-verified).
- Fresh sealed evidence: cdc 0.81, unsafe 0.02, validity 0.99, capacity 0.657,
  NL 0.714; paired vs H0 p=0.0011. Historical verdict KEEP_H0 stands (G7);
  GRS-refined is an ACTIVE E2E candidate per spec §24–26.
- Import action: same adapter boundary as H0 (shared program space); 2
  calls/policy.

Conservative Goal incumbent: **REQUIRED INPUT MISSING** — no implementation,
freeze, or sealed artifact in this environment (negative verification in
manifest §G). User-reported: validity 80.8%, behavioral 63.5%,
correct|valid 78.6%.

FR1/E5 (+ trusted frame assembler): **REQUIRED INPUT MISSING** — same negative
verification; user-reported dev 20/24 valid, 18/24 behavioral; verdict
STRUCTURED_GOAL_EMISSION_LIMITATION_CONFIRMED.

Per spec §6 these may NOT be reconstructed "by description". The Goal axis of
every E2E arm (E0/E1 need Conservative; E2/E3 need FR1/E5; E4 needs both) is
therefore blocked until the exact artifacts are supplied (delivery contract in
manifest §G). This is the same input-blocker discipline previously applied in
the C-ALR cycle (V5/V6 bundle) and resolved by user handoff.

## INTEGRATION GAPS
===================

1. GOAL_AXIS_INPUTS_MISSING (blocker): see above; blocks Phase 1 completion
   and all arm runs.
2. Source-path adapter: SourceEnvelope v4/External Source Views v6 are sealed
   but not wired into `core.analyze`; adapter + trusted-premise declaration
   required (Gap A/D).
3. Policy lowering adapter: H0/GRS → proof obligations with losslessness
   criteria; separate-REQUIREMENT merge-divergence subtlety already documented
   from the Stage A flattenability witness (per-clause obligations are NOT
   losslessly flattenable — must lower per-clause, not merged).
4. Goal semantic firewall: new boundary + metamorphic test (same USER prefix,
   different future trajectories → identical Goal candidate sets).
5. Certificate context extension for multi-frontend axes (spec §51).
6. Operational grounding semantics: conditions/exceptions/completed-effect
   obligations remain honestly UNRESOLVED unless the richer program space
   lowers them losslessly (Gap E) — no regex bridging.
7. External corpora adoption audits (AgentDojo/tau2-bench/ToolSandbox/ATBench
   located and reachable; license/format/gold-provenance audits pending —
   spec §69–70; external data is EXTERNAL_PUBLIC evidence, never
   INTERNAL_FRESH, per spec §72).
8. World-explosion measurement: no data yet on required worlds under multi-
   frontend axes (spec §43: measure before any relevance optimization).

## DO NOT USE
=============

- PSB in the active path (frozen INFRASTRUCTURE_FAILURE; terminal
  POLICY_LIMITATION_CONFIRMED; ACTOR-overbinding collapse on active-voice
  texts).
- Old Goal v2 frontend (`parse_goal_plan` baseline form) as an active E2E
  frontend (spec §30; 22/22 unresolved, zero definitive certificates).
- Goal-v3 isolation frontends v1/v2/v3 (all REJECTED; the baseline commit is
  the extraction v3 rejection archive).
- policy_programs native multi-program arm (RUN_COMPLETED_SEALED_NOT_PROMOTED;
  all-candidate accuracy 0.0).
- Any reconstructed-by-description FR1/E5/Conservative Goal (spec §6).
- Forbidden mechanisms list (spec §100): GRS v2, new negation heuristics,
  PSB v2, new Goal parser/ontology, new LLM judge, confidence router,
  majority vote, benchmark-specific patches, top-k interpretations/identities/
  worlds.
- Adaptive escalation in the primary comparison (spec §83).
- Post-hoc semantic fixes after the first fresh request (spec §85).

---

## Phase 0 completion state (spec §113 order)

1. ✅ Baseline checked out (worktree `guardian-e2e-baseline`, detached at
   `8b0d13c`); E2E assembly branch created and merged.
2. ✅ Complete test suite run (baseline 1484P/6F; merged 1549P/6F; failure
   class machine-classified as EOL/env, content-equivalent).
3. ✅ Existing Core/proof/source/factual boundaries read in full (8 files per
   spec §4 + policy.py/goals.py/semantic.py/normalize.py).
4. ✅ Late components located: H0 (byte-identity chain verified), GRS-refined
   (chain + canonicalizer verified), all factual/source/identity/temporal
   layers (sealed artifacts present); Goal sweep components NOT FOUND
   (blocker).
5. ✅ Hashes/seals/results verified where present (28 freeze manifests
   classified; 14 prediction seals intact gold_joined=false; 4 disclosed
   pre-existing runner-script drifts match the documented post-seal fixes).
6. ✅ Component Manifest produced (`E2E_COMPONENT_MANIFEST_V1.md`).
7. ✅ Current-vs-target mapping produced (this document).

Phase 1 (integration design) is NOT started: the Goal-axis required inputs
(spec §6/§30/§31) are absent, and per the spec's own provenance rule the
audit must be returned and the missing artifacts supplied or the Goal arms
explicitly re-scoped by the user before integration begins.
