# E2E V1 — Baseline Audit (commit 8b0d13c)

Audit date: 2026-09-16. Auditor: E2E V1 implementation agent.
Scope: real control/data flow of `guardian_truth.vnext.core.analyze` at commit
`8b0d13c1147531f4513d084ed99dc7133bfdcc92`, mapped against the E2E V1 specification.

## 1. Environment facts

* Repository cloned from `https://github.com/MYC-A/Guardian-of-Truth`, checked out at `8b0d13c` (detached HEAD).
* Python 3.12.14, pytest available. `PYTHONPATH=src`.
* Baseline suite: **1478 passed, 9 failed, 482 subtests passed** (excluding `test_next_evaluate_live.py`).
* All 9 failures are pre-existing archival-state failures, not Core logic failures:
  * `test_runtime.py::test_mistral_and_cerebras_lowercase_keys_bind_to_their_own_hosts` — legacy env-casing expectation (`mistral_api_key` vs `MISTRAL_API_KEY`) in the old (non-vnext) runtime module.
  * 8 × frozen-artifact hash mismatches (`test_vnext_integrity`, `test_vnext_binding_scaling_v1_artifacts`, `test_vnext_binding_temporal_v2_artifacts`, `test_vnext_completed_goal_t2_artifacts`, `test_vnext_experiment`, `test_vnext_goal_alignment_reference_v1`, `test_vnext_policy_artifact_audit_v1`, `test_vnext_t1_artifacts`) — historical seals in `outputs/` reference file hashes that drifted after archival; the Core test surface itself is green.
* Conclusion: baseline Core is reproducible; archival drift is recorded as historical state and is not touched by E2E V1.

## 2. Actual `core.analyze` flow (per-step audit)

Entry: `AnalysisInput` → `CoreAnalysis` → `ProductDecision`.

| # | Step | Input type | Output type | Source file / function | Trust status | Known limitation (E2E V1 view) |
|---|------|-----------|-------------|------------------------|--------------|-------------------------------|
| 1 | marker normalization | `prompt: str`, `response: str`, `tool_metadata` | `tuple[LedgerEvent]` | `vnext/normalize.py::normalize` + `guardian_truth/parsing.py::parse_events` | trusted deterministic | source authority comes from transport markers (⟦USER⟧ / ⟦ASSISTANT_TOOL_CALL name=…⟧ / ⟦TOOL_RESULT requestor=…⟧); body text never re-derives authority. FIFO call/result fallback is eligibility-filtered (role+tool) and marks `AMBIGUOUS_CALL_IDENTITY` instead of guessing |
| 2 | ledger build | events | `EvidenceLedger` + `Observation` flattening | `vnext/ledger.py::EvidenceLedger.from_events` | trusted deterministic | append-only; only `result` payloads become observations; completeness is an explicit application premise |
| 3 | T1 effect evaluation | correlated call/result + `ContractRegistry` | `ToolSemantics` (TRUSTED_EFFECT) | `vnext/tools.py::evaluate_t1` | trusted (contract-gated) | no contract → UNKNOWN; failure does not prove no-effect |
| 4 | T2 effect proposals | unregistered call/result + backend | `POSSIBLE_EFFECT` records | `vnext/tools.py::propose_t2` | UNTRUSTED neural (NEURAL_INTERPRETATION) | never becomes fact; retained only as world alternatives |
| 5 | claim graph | `response` + backend | `ClaimGraph` (TypedClaim per span) | `vnext/claims.py::build_claim_graph` (10 narrow passes) | neural interpretation, schema+inventory validated | candidate semantics only; spans come from deterministic `response_spans` inventory, never model offsets |
| 6 | policy parse | `policy` text + backend | `PolicyHypotheses` (1–4 readings + challenger) | `vnext/policy.py::parse_policy` | neural (EMPIRICAL_CANDIDATE_SET) | no semantic closure without supplied `ClosedUniverse`; challenger is a separate proposal pass, not a vote |
| 7 | goal/plan parse | `declared_goal`, `ordered_plan`, `history`, `target_action`, `allowed_scope` | `GoalPlanHypotheses` | `vnext/goals.py::parse_goal_plan` | neural | **FIREWALL GAP vs E2E V1 spec §55–56**: payload includes `history` and `target_action`, so the baseline goal frontend is not invariant to the future trajectory |
| 8 | operational binding | each `EvaluationHypothesis` + normative text + target calls | `OperationalChoice` (TARGET_CALL_MATCH atoms + `ArgumentConstraint`) | `vnext/grounding.py::bind_evaluation_hypothesis` | neural proposal + deterministic validation | v1 lowering supports exact invocation + literal argument scope only; conditions/exceptions/COMPLETED_EFFECT readings stay UNKNOWN (never silently simplified) |
| 9 | claim binding | each verifiable claim + ledger | `ClaimBinding` alternatives | `vnext/binder.py::bind_claim` | deterministic | ambiguity preserved (no confidence collapse); unbound entity ⇒ hard reason |
| 10 | axes/worlds | policy options ∪ goal options ∪ claim options ∪ T2 alternatives | `ProofProblem` (axes + Cartesian `WorldPlan`s) | `vnext/core.py` lines 101–193 | deterministic | exact all-world product, `max_worlds` budget; budget exceeded ⇒ no worlds ⇒ UNRESOLVED (`WORLD_BUDGET_EXCEEDED`) — no top-k |
| 11 | solve | problem + ledger + registry | `SolverResult` (per-world 4-valued error) | `vnext/solver.py::solve` | deterministic | material implication over obligations; `consensus` requires `material_space_complete` |
| 12 | certificate | result + context | `ProofCertificate` + `CertificateCheck` | `vnext/solver.py::make_certificate`, `vnext/certificates.py::check_certificate` | deterministic independent checker | no LLM; PROVED_NO_ERROR additionally requires `SOURCE_HISTORY_COMPLETE`, `BINDING_SPACE_COMPLETE`, `SEMANTIC_SPACE_PROVABLY_CLOSED` |
| 13 | decision | checked result | `CertifiedCoreResult` | `vnext/decision.py::decide` | deterministic | invalid certificate ⇒ downgrade to UNRESOLVED |
| 14 | escalation | UNRESOLVED state | bounded retries | `vnext/escalation.py::escalate` | deterministic, monotonicity-checked | OFF by default (`max_escalation_steps=0`) |
| 15 | product adapter | certified result | `ProductDecision` (binary label, fallback flag) | `vnext/adapters.py::adapt` | deterministic | UNRESOLVED never presented as proven NO_ERROR; audit mode returns `None` label |

## 3. Baseline invariant coverage (against E2E V1 spec §5)

* Present and tested: `CALL_ATTEMPTED != ACTION_COMPLETED`, `FAILED_CALL != SUCCESS` (failure does not trigger no-effect), `CLAIM != OBSERVED_FACT`, `TOOL_NAME != TOOL_EFFECT`, `UNKNOWN != FALSE` (missing argument), `NOT_FOUND != ABSENCE` (retrieval miss is not absence), `OBSERVED_AT_TIME != CURRENT_STATE` (state_at samples exact index), `LATER_STATE != CAUSAL_PROOF` (causal atoms need contract-confirmed effects), `USER_ACTION != ASSISTANT_ACTION` (user target call not an assistant violation), literal prefix identity (`Q-1 != Q-10`), ambiguous bindings never collapsed, world budget fail-safe, certificate gating of definitives.
* **Gaps that E2E V1 must repair architecturally (motivating the E2E composition core):**
  1. *Global unresolved masking*: `core.analyze` attaches **all** hard reasons to **every** `WorldPlan.unresolved_reasons`, and `consensus` requires `material_space_complete` over **all** axes. A proved independent violation is therefore masked by any unrelated hard failure or incomplete axis. E2E V1 spec §96/§100/§125 requires PROVED_ERROR to survive unrelated UNKNOWN.
  2. *Goal firewall*: baseline goal frontend input includes `history` and `target_action` (see step 7). E2E V1 requires the PASS-1 goal contract to be byte-invariant across 10 divergent futures (§56).
  3. *Single policy frontend / single goal frontend*: no H0 vs GRS and Conservative vs RuleFrames alternatives with equivalence-dedup retention (§25, §52, §78, §142).
  4. *No E2E entry point*: no versioned `analyze_e2e_v1` with explicit dependency injection (§109–110).

## 4. Reuse decisions (E2E V1)

Reused as-is: `types.py` (CoreStatus/Truth/EvaluationHypothesis/…), `normalize.py`, `ledger.py`, `tools.py` (T1/T2 + ContractRegistry), `claims.py`, `binder.py`, `grounding.py` (`bind_evaluation_hypothesis`, `literal_grounded`, `clause_ids`, `operational_schema`), `proof_records.py` (atom/obligation/world/problem records + Truth algebra), `proof_evidence.py::prove_atom`, `solver.py::world_space_complete` + `types.py::consensus`, `integrity.py` (canonical/digest/seals), `certificates.py::AuthoritativeAxis`, `decision.py::CertifiedCoreResult` pattern, `adapters.py::adapt`, `escalation.py` (left OFF), `llm_client.py` (BAI provider via `runtime.provider_config`).

New (versioned, in `src/guardian_truth/vnext/e2e/`): source adapter with TEXT_VIEW/ACTION_VIEW split; H0; GRS (grounder, DSL, synthesizer, canonicalizer); policy compilation/composition/lowering; Conservative Goal; Rule Frames; E5; assembler; goal composition/lowering; claim adapter; world integration with per-world decisive-vs-unrelated unknown semantics; E2E certificate context/checker; `core_v1.GuardianE2EV1.analyze_e2e_v1`; experiment runner with sealing and metrics. The baseline modules are NOT modified; B0 (untouched `core.analyze`) remains runnable for historical reference.

## 5. Historical artifact integrity

Archival drift listed in §1 is recorded here and excluded from E2E V1 gates. No frozen baseline artifact is rewritten. E2E V1 writes only to `docs/vnext/e2e/`, `outputs/vnext/e2e_v1_*`, and new source/test files.
