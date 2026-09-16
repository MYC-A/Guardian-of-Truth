# E2E V1 — Failure Audit (post-seal)

Machine-generated taxonomy: `outputs/vnext/e2e_v1_failure_audit.json`;
oracle attributions: `outputs/vnext/e2e_v1_oracle_attribution.json`.

## The residual bottleneck is the CLAIM layer, not the semantic frontends

1. **Claim-typing variance → global hard markers (~32/69 cases).**  The
   baseline claim machinery (10 narrow passes) is provider-nondeterministic
   on identical inputs at temperature 0: the same response text types as
   ACTION_COMPLETED in one run and CAUSAL_ATTRIBUTION or UNKNOWN_SEMANTICS
   in another.  An untyped material span is a GLOBAL unresolved reason
   (spec section 125: "unknown material response span blocks known plan
   violation") — it masks even proven, certificate-valid policy violations.
   In the dev shakeout the same case (err_flat_0) alternated between
   PROVED_ERROR (valid certificate) and UNRESOLVED across runs purely from
   claim-pass variance.  This is the single largest error-budget item
   (+11.6pp oracle delta from perfect claims).

2. **Binding abstention on unexercised atoms (~12/69 cases).**  The shared
   binding pass must map EVERY policy-relevant atom (targets, conditions,
   exceptions) to trajectory evidence.  When the atom's tool never appears
   in the trajectory (verify_sender never called, exception never approved),
   the model abstains (returns no binding) instead of binding to the catalog
   tool — leaving the rule's condition unbound → POLICY_OPEN_SEMANTICS
   marker → UNRESOLVED.  Honest behavior (no invention), but it means
   prerequisite/deadline/exception cohorts cannot resolve without the
   binding pass proposing catalog-tool bindings for unexercised tools.

3. **Goal-outcome channel fragility.**  The goal frontends extract
   DESIRED_OUTCOME frames reliably (54/69 cases have frames from both), but
   the outcome bindings' entity checks are frequently rejected by the
   literal-grounding validator (the model quotes the response instead of
   the normative text), leaving entity-pinned outcomes unenforceable.

4. **Retention multiplies unresolved surfaces (E4).**  31/69 policy
   disagreements and 54/69 goal disagreements are mostly ABSORBED downstream
   (same final verdict), but each additional retained world carries its own
   unresolved markers: E4 has 5 net regressions and zero salvage.

5. **Frontend substitution effects are below the noise floor.**  E1 vs E0
   and E3 vs E0: 3 corrections / 3 regressions, p = 1.0.  The GRS-vs-H0 and
   RuleFrames-vs-Conservative differences that were large in STANDALONE
   frontend evaluation (GRS +21pp CDC on the policy final holdout) vanish
   in the E2E composition — the claim/binding blockers dominate before the
   frontend difference can express itself.

## Spec section 193 — the fifteen questions

1. **What did GRS really improve (E2E)?**  Nothing measurable: +3/-3 vs H0
   (p=1.0); error recall +3.1pp, no-error recall -4.2pp.
2. **What did Rule Frames really improve?**  Nothing measurable: E2 vs E0
   0/-1 (p=1.0).
3. **Is H0 needed after GRS?**  Indistinguishable at this bottleneck level.
4. **Is Conservative Goal needed after Rule Frames?**  Indistinguishable.
5. **Decisive disagreements?**  5, all E4-retention-caused regressions.
6. **Absorbed disagreements?**  The majority (26+ of 31 policy, most goal)
   compose to identical verdicts.
7. **Does one frontend's errors get rescued by the other?**  Zero salvage
   events in E4.
8. **Common-mode errors remaining?**  Not separable at this coverage; both
   frontends' outputs are usually masked by claim/binding blockers first.
9. **Is lowering the bottleneck?**  No — the lowering is verbatim-v3-equivalent
   (45 offline tests) and certificates re-derive it exactly.
10. **Is Binding the bottleneck?**  Second: ~12 cases of abstention on
    unexercised atoms.
11. **Is Claim evidence the bottleneck?**  FIRST: ~32 cases, +11.6pp oracle.
12. **How many verdicts do certificates reject?**  Zero (all 85 definitive
    certificates valid).
13. **How much safety do they preserve?**  The certificate gate did not need
    to downgrade anything this run; unsafe-definitive = 0 in all arms.
14. **World explosion from multi-frontend?**  Mean 1.0 → 2.59 worlds; max 4;
    no budget overflows — but each extra world multiplies unresolved-marker
    exposure (the E4 regression mechanism).
15. **Is Guardian usable as a proof-based evaluator today?**  As an
    ABSTENTION-heavy verifier: definitive accuracy 94% with 0 unsafe — but
    74% unresolved coverage is too low for practical evaluation use.
