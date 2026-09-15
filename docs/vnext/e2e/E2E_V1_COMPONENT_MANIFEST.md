# E2E V1 — Component Manifest

Assembly branch `experiment/guardian-e2e-v1`. Full provenance (commits, hashes,
seals, evidence status per component) is in
`../E2E_COMPONENT_MANIFEST_V1.md` (24 components, prior Phase 0). This
manifest is the E2E-V1 view: what each component IS in the E2E architecture
(spec §184 requires `outputs/vnext/e2e_v1_component_manifest.json`; this
document is its human-readable source of truth).

Statuses: `REUSE_FROZEN` (byte-identical sealed implementation wired into
E2E), `REUSE_BASELINE` (baseline `8b0d13c` code wired unchanged),
`NEW_V1` (new versioned implementation per spec §176–§178; never claimed to be
a historical artifact), `DECLARED_OUT` (excluded with reason).

## A. Policy axis

| Component | Implementation | Status | Notes |
|---|---|---|---|
| H0 flat frontend | `scripts/evaluate_vnext_c_alr_reimpl.py` PARSE_TASK/REPAIR_TASK/STRUCTURE_SCHEMA/CONFIG | REUSE_FROZEN | byte-identity chain C-ALR→PHV1→PSB→GRS→final; final-freeze `h0_identity` recorded |
| H0 compiler | `policy_v3_benchmark.compile_v3_structure` + `evaluate_v3_program` | REUSE_FROZEN | shared behavioral program space |
| GRS grounder | `policy_grs.py` GRS_GROUND_TASK/SCHEMA (+ repair) | REUSE_FROZEN | catalog-only atoms, exact spans, no roles |
| GRS synthesizer (B1) | `policy_grs.py` GRS_SYNTH_TASK + `policy_grs_emission.py` frozen-B1 boundary | REUSE_FROZEN | final-cycle selected boundary: frozen B1 prompt + canonicalizer |
| GRS canonicalizer | `policy_grs_emission.py` (RULE-wrapper repair only) | REUSE_FROZEN | token-multiset-proven semantics-preserving |
| GRS DSL validator/compiler | `policy_grs.py` parse_dsl/validate_ruleset_ast/compile_dsl | REUSE_FROZEN | reject-only; compiles to v3 program space |
| Policy composition (H0/GRS equivalence + retention) | NEW `e2e/policy_composition_v1.py` | NEW_V1 | deterministic behavioral equivalence over distinguishing-world surface (spec §51); no winner selection |
| Policy lowering (program → obligations) | NEW `e2e/policy_lowering_v1.py` | NEW_V1 | conditional rules, ATTEMPT/EFFECT levels via binding axis |
| PSB graph frontend | — | DECLARED_OUT | ACTOR-overbinding collapse on fresh active-voice texts (POLICY_FINAL_RESULTS.md) |

## B. Goal axis

| Component | Implementation | Status | Notes |
|---|---|---|---|
| Conservative Goal frontend | NEW `e2e/goal_conservative_v1.py` | NEW_V1 | HISTORICAL_SOURCE_UNAVAILABLE; one bounded pass; explicit-only extraction with ExtractiveRefs (spec §63–§68) |
| Rule Frames frontend | NEW `e2e/goal_rule_frames_v1.py` | NEW_V1 | HISTORICAL_SOURCE_UNAVAILABLE; source-linked frames, LLM decides semantics only (spec §69–§72) |
| E5 resolver | NEW `e2e/goal_e5_v1.py` | NEW_V1 | strict 4-case deterministic resolver; no fuzzy recovery (spec §74–§75) |
| Trusted assembler | NEW `e2e/goal_assembler_v1.py` | NEW_V1 | canonical IDs/ordering/dedup; no semantic repair (spec §76–§77) |
| Goal composition | NEW `e2e/goal_composition_v1.py` | NEW_V1 | canonical lowering + deterministic equivalence; retain both when different (spec §78–§79) |
| Goal binding (PASS 2) | NEW `e2e/goal_binding_v1.py` (shared semantic binding pass) | NEW_V1 | goal interpretations + trajectory → grounded instances (spec §80–§81); never sees gold |
| Goal lowering | NEW `e2e/goal_lowering_v1.py` | NEW_V1 | DESIRED_OUTCOME→alignment obligation (ANY-OF encoding); PROHIBITION→per-call forbid; OBLIGATION→require with guards/temporal (spec §82–§84) |
| Baseline goals.py frontend | `goals.py::parse_goal_plan` | DECLARED_OUT for E2E arms | firewall violation (receives history+target_action); kept for baseline reproducibility |

## C. Lower layers

| Component | Implementation | Status | Notes |
|---|---|---|---|
| Source adapter | NEW `e2e/source_adapter_v1.py` | NEW_V1 | trajectory sources with role/actor/authority metadata → AnalysisInput channels (spec §8–§13) |
| EvidenceLedger + normalize | baseline `ledger.py`, `normalize.py` | REUSE_BASELINE | append-only; call_id correlation, AMBIGUOUS kept |
| T1 contract registry | baseline `tools.py` | REUSE_BASELINE | versioned TrustedContract; per-case registry |
| T2 neural candidates | baseline `tools.py::propose_t2` | REUSE_BASELINE | OFF in E2E arms unless case declares unknown-tool semantics; candidates → worlds only |
| Claim graph (10 passes) | baseline `claims.py` | REUSE_BASELINE | claim parser never sets truth |
| Claim binder | baseline `binder.py` | REUSE_BASELINE | exact-identity alternatives; ambiguity preserved |
| Solver + worlds | baseline `solver.py`, `proof_records.py`, `proof_evidence.py` | REUSE_BASELINE | exact Cartesian; no top-k; budget → UNRESOLVED |
| Certificates + checker | baseline `certificates.py`, `decision.py` | REUSE_BASELINE (+ extended context) | `certificate_context_v1.py` extends the hashed context with e2e axes/programs/bindings and validates the new obligation shapes |
| Adapter | baseline `adapters.py` | REUSE_BASELINE | AUDIT mode for scoring; binary mapping versioned |

## D. Composition

| Component | Implementation | Status | Notes |
|---|---|---|---|
| World integration | NEW `e2e/world_integration_v1.py` | NEW_V1 | axes from policy/goal/binding/claims/effects; obligations per choice; world budget fail-safe |
| Core entry point | NEW `e2e/core_v1.py::analyze_e2e_v1` / `GuardianE2EV1` | NEW_V1 | explicit dependency injection (spec §109–§110); does not modify baseline `analyze` |
| Semantic binding pass (shared) | NEW `e2e/semantic_binding_v1.py` | NEW_V1 | catalog atoms + goal propositions → tool/argument/observation bindings; deterministic validation; candidates → binding axis |

## E. Experiment infrastructure

| Component | Implementation | Status |
|---|---|---|
| Dev corpus builder (isolated cases → trajectories) | NEW `e2e/dev_corpus_v1.py` | NEW_V1 |
| Fresh holdout corpus builder (~96 cases, 8-gram-disjoint) | NEW `e2e/fresh_corpus_v1.py` | NEW_V1 |
| Runner (frontends once per case, arms composed deterministically) | NEW `scripts/evaluate_vnext_e2e_v1.py` | NEW_V1 |
| Scorer + McNemar/Newcombe + gates | NEW (runner module) | NEW_V1 |
| Oracle diagnostics + failure taxonomy | NEW (runner module) | NEW_V1 |
| External benchmark audit (AgentDojo, tau2-bench, ToolSandbox, ATBench) | `docs/vnext/e2e/E2E_V1_EXTERNAL_BENCHMARK_AUDIT.md` | NEW_V1 (audit only; adaptation per audit outcome) |

## F. Provider continuity

All neural frontends run on provider `bai`, model `qwen3.8-flash`
(CONFIG from the frozen H0 definition; temperature 0, reasoning_effort low,
max_retries 0, one pre-registered transport/format repair re-ask per request
slot where the frozen protocol allows it). Provider smoke PASSED this session
(`scripts/e2e_v1_provider_smoke.py`). A different model would constitute a
separate arm/version and is out of scope for E2E V1.
