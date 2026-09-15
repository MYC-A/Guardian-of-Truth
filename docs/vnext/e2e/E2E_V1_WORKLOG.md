Guardian of Truth — E2E V1 work log (repo)
==========================================

---
Task ID: p0
Agent: main (Super Z)
Task: Phase 0 — baseline audit at 8b0d13c

Work Log:
- Cloned https://github.com/MYC-A/Guardian-of-Truth, checked out 8b0d13c1147531f4513d084ed99dc7133bfdcc92 (detached HEAD).
- Read full E2E V1 specification (upload/Промт.txt, 5110 lines).
- Read vnext Core: core.py, types.py, solver.py, proof_records.py, decision.py, certificates.py, policy.py, goals.py, semantic.py, ledger.py, normalize.py, grounding.py, tools.py, adapters.py, claims.py, binder.py, proof_evidence.py, operational_records.py, escalation.py, integrity.py, source_envelope_v4.py, llm_client.py, parsing.py (markers).
- Ran baseline suite: 1478 passed / 9 failed (all pre-existing archival/env drift; Core logic green).
- Wrote docs/vnext/e2e/E2E_V1_BASELINE_AUDIT.md (flow table, trust statuses, gaps: global unresolved masking; goal firewall gap — parse_goal_plan sees history+target_action; single frontends; no E2E entry point).
- LLM backend verified: BAI provider (api.b.ai/v1, model qwen3.8-flash) through guardian_truth.llm_client.ChatClient with strict JSON schema; .env written (gitignored).

Stage Summary:
- Baseline reproducible; reuse map fixed (see BASELINE_AUDIT §4). E2E V1 composition core must repair §3 gaps 1–4 without touching baseline modules. Next: Phase 1 formal contracts in src/guardian_truth/vnext/e2e/.

---
Task ID: p1-p5
Agent: main (Super Z)
Task: Phases 1-5 — formal contracts, e2e package implementation, unit/regression tests

Work Log:
- Implemented src/guardian_truth/vnext/e2e/ (15 modules): e2e_types_v1 (frozen contracts), source_adapter_v1 (TEXT_VIEW/ACTION_VIEW, SYSTEM-marker policy framing, firewall goal source), policy_h0_v1, policy_grs_grounder_v1, policy_grs_dsl_v1 (closed grammar), policy_grs_synth_v1 + canonicalizer, policy_composition_v1 (H0/GRS -> CompiledRule program space, canonical equivalence dedupe, BEFORE-inversion compilation), policy_lowering_v1 (FORBID_CALL/REQUIRE_PRESERVE/REQUIRE_CALL lowering via baseline bind_evaluation_hypothesis), goal_conservative_v1, goal_rule_frames_v1 (+assembler), goal_e5_v1 (strict deterministic resolver), goal_composition_v1, goal_lowering_v1 (GOAL_CALL/GOAL_ALTERNATIVES disjunctive groups), claim_adapter_v1 (value anchoring + LATEST mode), world_integration_v1 (per-world verdicts: violation survives unrelated UNKNOWN; markers block NO_ERROR only; exact Cartesian product; budget fail-safe), certificate_context_v1 (independent checker + closure premises incl. FRESH_STATE_EVIDENCE), core_v1 (GuardianE2EV1.analyze_e2e_v1, DI, arms E0-E4, oracle substitutions), backend_v1 (memoized one-attempt backend, 4 registered deterministic transport repairs), json_extract_backend_v1 (fence/prose-stripping).
- BAI endpoint constraint found: strict response_format schemas with uniqueItems rejected (HTTP 400) -> provider runs response_format_mode='none' (same mode as repository's own BAI tests).
- Tests: tests/e2e/ 31 tests green (DSL closed-vocabulary attacks, E5 cases, canonicalizer semantic-modification rejection, cross-layer example 1 (passengers) PROVED_ERROR, closed-safe NO_ERROR with closure, no-closure -> UNRESOLVED, goal firewall invariance across 10 futures, policy ERROR survives unrelated goal binding failure, H0 unavailable never safe, world budget, GRS arm, E4 dedupe, false-success RESULT_FIELD ERROR, prerequisite user-vs-assistant, incomplete-history unknown, certificate tampering rejection).
- Live smoke (qwen3.8-flash): passengers case -> PROVED_ERROR with valid certificate; GRS+RF prerequisite case -> PROVED_ERROR with valid certificate.

Stage Summary:
- Baseline modules untouched (B0 reproducible); all reuse via import. E2E semantics decisions documented in code: axis-incompleteness (frontend failure) blocks both definitives; reading/rule/claim-level unknowns are per-world UNKNOWN markers (block NO_ERROR, never mask ERROR); PROVED_ERROR needs SEMANTIC_CANDIDATES_COVERED only; PROVED_NO_ERROR needs full closure set (material coverage, history, bindings, closed semantics, fresh state evidence).
- Next: Phase 6 dev corpus + experiment runner; Phase 7 freeze; Phase 8 fresh E2E.
