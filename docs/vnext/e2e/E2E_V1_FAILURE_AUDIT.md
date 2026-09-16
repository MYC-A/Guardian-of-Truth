# E2E V1 — Failure Audit (fresh holdout, post-seal)

Full machine-readable audit: `outputs/vnext/e2e_v1_failure_audit.json`.
Taxonomy codes per spec 171; FRONTEND vs LOWERING separated per spec 172.

## E0 (conservative architecture) — 59 non-correct cases

| taxonomy | count | dominant families | reading |
|----------|-------|-------------------|--------|
| SEMANTIC_BEHAVIOR | 11 | condition_unknown, prerequisite_user_action, negation_policy | conditional rules stay decisive-unknown (correct abstention on the harder half; some prerequisite compilations missed by H0's flat parse) |
| POLICY_H0 | 10 | nl_stress_multi_clause, value_prohibition | H0's flat single-structure parse cannot represent multi-clause policies (spec 35 confirmed empirically) |
| CLAIM_SUPPORT | 7 | unsupported_claim, false_success_claim | claim typing/binding misses (predicate/object variance) leave contradicted claims unproven |
| GOAL_CONSERVATIVE | 3 | wrong_arguments, goal_scope_error | goal scope extraction variance leaves argument mismatches unbound |
| FALSE_CERTIFIED_ERROR | 3 | stale_state_claim | stale-contradiction semantics resolves to ERROR where the designed gold is UNRESOLVED |
| OTHER | 6 | closure_ablation_open, identity_ambiguity | designed-abstention families scored as non-correct because gold is UNRESOLVED by design (the arm also abstains — these are coverage, not errors) |

## E2/E3 (RuleFrames arms) — the regression mechanism

E2 regresses 30 E0-definitive cases into UNRESOLVED, concentrated in
simple_error_forbidden_tool (4), unsupported_claim (4), closed_safe_simple
(3), wrong_tool_goal_mismatch (3), source_injection_safe (3). Mechanism: the
RuleFrames frontend emits semantically rich content keys and scope shapes
whose operational bindings fail validation more often than the Conservative
frontend's, leaving per-world UNKNOWN markers that block both definitives.
The failure is in the FRONTEND-to-LOWERING interface (content key
conventions), not in E5 (which is deterministic and correct).

## E4 (retention) — the abstention mechanism

E4 turns 45 E0-definitive-correct cases into UNRESOLVED with 0 corrections:
whenever H0 and GRS (or Conservative and RF) produce materially different
compiled programs, both readings are retained, the world space splits, and
mixed worlds block both definitives. At V1 frontend quality the disagreement
is mostly representation noise, so retention costs coverage without buying
verdict correctness.

## Unsafe verdict audit

All 9 E0 false-certified-ERROR verdicts were manually reviewed:
* 4 stale_state_claim: the freshness/BOTH semantics certifies ERROR from a
  stale contradiction; the designed ground truth is "cannot determine".
  Conservative fix direction (V2): require no intervening result events at
  all (not just mutation-capable calls) before certifying a stale
  contradiction as ERROR.
* 2 alternative_actions: the authorization-alternatives behavioral closure
  mismatched the actual two-frame frontend output.
* 1 inconsistent_trusted_evidence: INCONSISTENT resolved to ERROR (read
  call between contradictory evidence).
* 2 claim-typing edge cases.
Zero false-certified-NO_ERROR across all arms: the safety-critical direction
held everywhere.
