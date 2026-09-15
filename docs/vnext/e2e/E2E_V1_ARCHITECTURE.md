# E2E V1 — Architecture (Phase 1)

Reference: spec §3 (LLM proposes / trusted code validates, preserves
provenance, binds identities, builds obligations; trusted observations
establish evidence; versioned contracts establish effects; solver proves;
independent checker verifies), §109–§110 (explicit versioned entry point,
dependency injection, no hidden API client or global state).

## Entry point

`src/guardian_truth/vnext/e2e/core_v1.py::analyze_e2e_v1(sources, semantic,
arm, *, max_worlds, adapter_mode) -> E2EAnalysisResult` with
`run_semantic_passes(sources, deps) -> E2ESemanticOutputs` executing all
arm-independent LLM passes once per case.  The baseline `core.analyze` is
untouched and remains reproducible.

## Component graph

```
E2ECaseSources (source_adapter_v1)
  ├── render_prompt/render_response  ──► normalize ──► EvidenceLedger (+LedgerIndex)
  ├── user_source_index ─────────────► [FIREWALL] ──► goal frontends
  │                                                      ├── goal_conservative_v1 (task)
  │                                                      └── goal_rule_frames_v1 (task)
  │                                                   ──► E5 (goal_e5_v1) ──► assembler
  │                                                   ──► GoalContracts ──► goal_composition_v1
  ├── policy_text + atom_catalog ────► H0 frontend (injected frozen tasks)
  │                                 ──► GRS grounder+B1+canonicalizer (injected)
  │                                 ──► v3 programs ──► policy_composition_v1
  ├── trajectory_view + schemas ─────► semantic_binding_v1 (PASS 2, shared)
  │                                 ──► BindingRecord (candidates, observations)
  └── response ──────────────────────► claims.py (10 passes, baseline)
                                    ──► binder.py claim bindings (baseline)

analyze_e2e_v1(arm):
  policy composition (arm-selected frontends)
  goal composition (arm-selected frontends)
  policy_lowering_v1 + goal_lowering_v1  ──► E2EAxisChoice obligations
  world_integration_v1 (claim axes, exact Cartesian, budget fail-safe)
  solver.solve (baseline) ──► make_e2e_certificate ──► check_certificate_e2e
  decision (baseline constructor semantics) ──► adapters.adapt ──► binary
```

## Trust boundaries (full detail in E2E_V1_TRUST_BOUNDARIES.md)

- LLM proposes ONLY: H0 structure, GRS inventory+DSL, goal frames, semantic
  bindings, claim field semantics.  All five outputs pass deterministic
  reject-only validation (schema, exact spans, catalog membership, literal
  grounding, path existence).
- Trusted deterministic code owns: ledger construction, identity/correlation,
  T1 effects, program compilation, equivalence/dedupe, lowering, world
  enumeration, proofs, certificates, the binary adapter.
- Gold NEVER enters any system input; corpus gold lives only in the runner's
  sealed gold store, joined after prediction seals.

## Frozen interfaces

- Frontends are injected callables (`make_h0_frontend`, `make_grs_frontend`
  factories bind the frozen task strings/schemas imported by the runner from
  their canonical locations — byte-identity by construction).
- `LoweringContext` (target calls, all calls, end index) is the ONLY
  trajectory view the lowering reads; it is serialized into the certificate
  context for re-derivation.
- The E2E certificate context extends the baseline `CertificateContext`
  (dataclass subclass); all e2e evidence is hashed into `source_sha256`.
