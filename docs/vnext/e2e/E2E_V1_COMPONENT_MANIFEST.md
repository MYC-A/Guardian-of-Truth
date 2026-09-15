# E2E V1 — Component Manifest

Mapping of E2E V1 responsibilities to concrete modules. "REUSE" = baseline module used unmodified; "NEW" = versioned component in `src/guardian_truth/vnext/e2e/`.

| Responsibility | Module | Status | Notes |
|---|---|---|---|
| Source normalization (markers → events) | `vnext/normalize.py` | REUSE | transport-marker authority; ambiguity-preserving call/result correlation |
| Evidence ledger | `vnext/ledger.py` | REUSE | append-only; observations only from `result` payloads |
| T1 trusted effects | `vnext/tools.py::evaluate_t1` | REUSE | contract-gated |
| T2 untrusted effect proposals | `vnext/tools.py::propose_t2` | REUSE | NEURAL_INTERPRETATION, world alternatives only |
| Claim extraction (TEXT_VIEW) | `vnext/claims.py::build_claim_graph` | REUSE | 10 narrow passes; deterministic span inventory |
| Claim entity binding | `vnext/binder.py::bind_claim` | REUSE | ambiguity-preserving |
| Operational action grounding (semantic action ↔ tool call ↔ arguments) | `vnext/grounding.py::bind_evaluation_hypothesis`, `literal_grounded`, `clause_ids`, `operational_schema` | REUSE | LLM proposal + deterministic literal/clause validation |
| Proof atoms / obligations / worlds / problems | `vnext/proof_records.py` | REUSE | unchanged records; Truth algebra reused |
| Primitive proofs | `vnext/proof_evidence.py::prove_atom` | REUSE | deterministic |
| World-space completeness / consensus | `vnext/solver.py::world_space_complete`, `vnext/types.py::consensus` | REUSE | |
| Authoritative axis records | `vnext/certificates.py::AuthoritativeAxis` | REUSE | 4 fixed authority bases |
| Prediction seals | `vnext/integrity.py` | REUSE | write-new, seal, gold-after-seal |
| Product adapter | `vnext/adapters.py::adapt` | REUSE | binary only after CoreStatus |
| LLM transport | `guardian_truth/llm_client.py` + `runtime.provider_config('bai')` | REUSE | BAI provider, qwen3.8-flash; credentials via gitignored `.env` |
| E2E source adapter (TEXT_VIEW / ACTION_VIEW; firewall goal source) | `e2e/source_adapter_v1.py` | NEW | splits target assistant output into text/call projections; isolates user request |
| H0 flat policy frontend | `e2e/policy_h0_v1.py` | NEW | one semantic attempt; frozen schema; format-only repair |
| GRS grounder | `e2e/policy_grs_grounder_v1.py` | NEW | grounded inventory atoms, quote-validated |
| GRS DSL | `e2e/policy_grs_dsl_v1.py` | NEW | closed grammar; validator |
| GRS B1 synthesizer | `e2e/policy_grs_synth_v1.py` | NEW | composes only inventory IDs |
| GRS canonicalizer | `e2e/policy_grs_canonicalizer_v1.py` | NEW | structure-preserving serialization repair only |
| Policy compilation + H0/GRS equivalence + axis | `e2e/policy_composition_v1.py` | NEW | common program space; structural-canonical dedupe; no winner selection |
| Policy lowering | `e2e/policy_lowering_v1.py` | NEW | compiled rules → EvaluationHypothesis (+ per-rule trusted scope) → operational bindings |
| Conservative goal frontend | `e2e/goal_conservative_v1.py` | NEW | direct-positive-textual-support frames only |
| Rule Frames goal frontend | `e2e/goal_rule_frames_v1.py` | NEW | source-linked frames, LLM emits semantic fields only |
| E5 extractive resolver | `e2e/goal_e5_v1.py` | NEW | strictly deterministic: EXACT / UNIQUE_QUOTE / AMBIGUOUS / UNRESOLVED |
| Trusted goal assembler | `e2e/goal_assembler_v1.py` | NEW | canonical IDs/order/arity; no semantic repair |
| Goal composition + equivalence | `e2e/goal_composition_v1.py` | NEW | canonical lowering; dedupe or retain |
| Goal lowering | `e2e/goal_lowering_v1.py` | NEW | goal contract → hypotheses + scopes → operational bindings (PASS 2) |
| Claim adapter (TEXT_VIEW/ACTION_VIEW invariant) | `e2e/claim_adapter_v1.py` | NEW | wraps build_claim_graph; documents projection invariant |
| World integration (all-world product; decisive-vs-unrelated UNKNOWN) | `e2e/world_integration_v1.py` | NEW | per-world local verdicts; violation survives unrelated unknown; budget fail-safe |
| E2E certificate context + independent checker | `e2e/certificate_context_v1.py` | NEW | no LLM; recomputes primitives; closure premises; downgrade on invalid |
| E2E entry point | `e2e/core_v1.py` | NEW | `GuardianE2EV1.analyze_e2e_v1`; explicit DI; arms E0–E4 |
| Experiment runner (sealing, metrics, oracle) | `e2e/experiment_v1.py` | NEW | prediction seals; McNemar; oracle substitutions |
| Semantic backend wrapper (caching + telemetry) | `e2e/backend_v1.py` | NEW | memoizes pure frontend passes; one semantic attempt per case/pass |

Historical components referenced by the spec but NOT reused as-is (recorded per §176–178): FR1/E5/Conservative exact historical sources are absent at `8b0d13c`; GRS historical grammar not found in vnext Core path. Status: `HISTORICAL_SOURCE_UNAVAILABLE / ARCHITECTURE_CONTRACT_KNOWN / NEW_VERSIONED_IMPLEMENTATION_REQUIRED`. New implementations are `*_v1` versions and are NOT claimed to be the historical artifacts.
