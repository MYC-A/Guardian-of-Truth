# E2E V1 — Fresh Experiment Results

Frozen at commit `2a07bc58f05dabb71600724f279df98c9a9d7215` (freeze v2; the
premature freeze v1 at `8c34dc1` was invalidated pre-scoring after the live
dev shakeout — disclosed in the worklog).  Corpus: 69 cases, 42 cohorts, gold
by construction, zero shared word-8-grams with every prior Guardian corpus.
Provider: bai/qwen3.8-flash, temperature 0, one pre-registered repair re-ask
per request slot, T2 OFF, escalation OFF.  1,134 live requests across 69
cases; all five arms composed deterministically from the sealed per-case
semantic outputs; per-arm predictions sealed (`gold_joined=false`) before
scoring.  Hard invariants: **PASS** (0 uncertified definitives, 0 crashes,
0 unsafe definitives, 0 role/actor/identity/causality violations, seals
verified).

## Primary metrics (per arm)

| Arm | Policy | Goal | CDC | resolved | def-acc | unsafe | err-recall | no-err-recall | unresolved |
|-----|--------|------|-----|----------|---------|--------|------------|---------------|------------|
| E0 | H0 | Conservative | **0.246** | 0.261 | 0.944 | 0.000 | 0.188 | 0.458 | 0.739 |
| E1 | GRS | Conservative | **0.246** | 0.261 | 0.944 | 0.000 | 0.219 | 0.417 | 0.739 |
| E2 | H0 | RuleFrames | **0.232** | 0.246 | 0.941 | 0.000 | 0.188 | 0.417 | 0.754 |
| E3 | GRS | RuleFrames | **0.246** | 0.261 | 0.944 | 0.000 | 0.219 | 0.417 | 0.739 |
| E4 | both retained | both retained | **0.174** | 0.188 | 0.923 | 0.000 | 0.188 | 0.250 | 0.812 |

CDC ceiling given the 18 gold-UNRESOLVED cases: 51/69 = 0.739.

## Paired comparisons (exact two-sided McNemar, Newcombe CI)

| Pair | corrections | regressions | p | CI |
|------|------------|-------------|-----|-----|
| E1 vs E0 (GRS effect) | 3 | 3 | 1.000 | [-0.082, +0.082] |
| E2 vs E0 (RuleFrames effect) | 0 | 1 | 1.000 | [-0.078, +0.040] |
| E3 vs E0 (strongest singleton) | 3 | 3 | 1.000 | [-0.082, +0.082] |
| E4 vs E3 (retention value) | 0 | 5 | 0.0625 | [-0.159, -0.006] |
| E4 vs E0 (full architecture) | 0 | 5 | 0.0625 | [-0.159, -0.006] |

**No frontend substitution reaches significance.  Retention (E4) is a net
REGRESSION** (5 regressions, 0 corrections, p=0.0625): the retained
interpretation axes multiply worlds (mean 1.0 → 2.59) and every additional
world is another chance for an unresolved marker, with zero measured
salvage benefit.

## Disagreement metrics (E4)

- Policy axis: 31 EQUIVALENT / 31 DIFFERENT / 7 ONE_INVALID.
- Goal axis: 15 EQUIVALENT / 54 DIFFERENT (the two goal frontends rarely
  produce structurally identical obligation surfaces).
- DECISIVE disagreements: 5 (all in the E4-vs-E3 regression direction —
  retention turns resolved cases into UNRESOLVED).
- ABSORBED disagreements: the majority — most DIFFERENT readings compose to
  the same verdict, but the extra worlds still admit unresolved markers.
- SEMANTIC_SALVAGE: 0 cases where retention rescued a wrong singleton
  verdict.  COMMON_MODE_WRONG_AGREEMENT: not isolable at this coverage
  (both frontends' errors are masked by claim/binding blockers before they
  reach the verdict).

## Oracle attribution (post-seal, E0 arm)

| Configuration | CDC | Delta |
|---------------|-----|-------|
| Actual E0 | 0.246 | — |
| Gold policy programs (H0 replaced by construction gold) | 0.261 | +0.014 |
| Perfect claims (all NON_VERIFIABLE) | 0.362 | +0.116 |
| Gold policy + perfect claims | 0.362 | +0.116 |

The POLICY frontends are NOT the E2E bottleneck (+1.4pp ceiling from perfect
policy semantics).  The CLAIM layer alone accounts for +11.6pp.  The
remaining gap (0.362 → 0.739 ceiling) is dominated by the BINDING layer
(unbound semantic atoms for conditions/targets the trajectory never
exercised) and the goal-outcome channel.

## Failure taxonomy (E0, 69 cases; dominant blockers)

- 17 correct definitive (24.6%).
- ~32 cases blocked primarily by CLAIM_UNTYPED_OR_VARIANCE: the baseline
  claim machinery turns any untyped/variance-typed response span into a
  global hard marker that masks even proven, certified policy violations
  (spec section 125 semantics working as designed — but the live claim
  passes type identical text differently across runs: ACTION_COMPLETED vs
  CAUSAL_ATTRIBUTION vs UNKNOWN_SEMANTICS).
- ~12 cases blocked by BINDING_UNBOUND_CONDITION: the shared binding pass
  did not bind semantic atoms the policy needed (verify_sender,
  exception_approved, hold/manifest atoms) — mostly atoms whose tools never
  appear in the trajectory, where the model abstains rather than binding to
  the catalog tool.
- 1 CLAIM_CAUSAL_ATTRIBUTION_VARIANCE; 5 other blocked-unresolved.

## World metrics

Mean required worlds: E0 1.0 / E4 2.59; max 4 (no WORLD_BUDGET_EXCEEDED
events; budget 4096 never approached).

## Certificate metrics

Every definitive verdict in every arm carries a valid E2E certificate
(uncertified_definitive = 0 across all arms); the re-derivation checker
accepted all 5×17 = 85 definitive certificates.
