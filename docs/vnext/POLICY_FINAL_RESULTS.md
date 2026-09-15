# POLICY FINAL CYCLE — Results (fresh final holdout)

**Experiment**: POLICY_FINAL_CYCLE — final standalone Policy frontend selection
(user 75-section protocol).
**Preregistration**: `docs/vnext/POLICY_FINAL_PREREG_V1.json` (frozen before any
holdout inference; commit `08142ac`).
**Holdout**: 100 fresh gold-by-construction cases, 8-gram-disjoint from
V4+V5+PHV1+PSB+GRS-A+GRS-B; realistic mixture; 35 non-H0-representable
capacity cases; gold = behavioral worlds over the shared v3 program space.
**Live arms** (bai/qwen3.8-flash, identity-verified byte-continuity with every
sealed predecessor): `h0` 98/100 ok, `psb` 87/100 ok, `ground` 99/100 ok,
`synth` 99/100 ok; 4 calls/case, 447 requests total, all arms sealed before
the gold join.

## Verdict (per the frozen gates)

**`KEEP_H0`** — no candidate passes all seven preregistered gates.

The strongest candidate, **C2 = refined GRS** (grounder + frozen B1 prompt +
deterministic canonicalizer), passes **6 of 7 gates** and fails only
**G7 (H0-correct regression rate 15% > 10%)**. It is statistically
significantly better than H0 on the primary metric:
30 corrections vs 9 regressions, exact McNemar **p = 0.0011**,
Newcombe 95% CI for the delta **[+10.1pp, +31.5pp]**.

## Primary table (correct-definitive coverage = definitive coverage ×
definitive accuracy; definitive = the candidate commits to one behavioral
meaning that agrees across the gold-free catalog world surface)

| Candidate | cdc | def.cov | def.acc | unsafe-def | validity | simple | NL | capacity | H0-regr | calls |
|---|---|---|---|---|---|---|---|---|---|---|
| **C0 H0** | 0.60 | 0.97 | 0.619 | **0.14** | 0.97 | 1.00 | 0.429 | 0.086 | — | 1 |
| C1a HP1 (fallback) | 0.26 | 1.00 | 0.26 | 0.01 | 1.00 | 0.059 | 0.286 | 0.257 | 0.717 | 2 |
| C1b HP3 (retain) | 0.17 | 0.24 | 0.708 | 0.01 | 1.00 | 0.059 | 0.143 | 0.000 | 0.717 | 2 |
| **C2 GRS-refined** | **0.81** | 0.99 | 0.818 | 0.02 | 0.99 | 1.00 | 0.714 | **0.657** | 0.15 | 2 |
| C3a H0+GRS retain | 0.54 | 0.59 | 0.915 | 0.01 | 1.00 | 1.00 | 0.429 | 0.000 | 0.15 | 3 |
| C3b three-way | 0.16 | 0.17 | 0.941 | 0.00 | 1.00 | 0.059 | 0.000 | 0.000 | 0.733 | 4 |

Gate detail for C2: G1 ✓ (0.81 ≥ 0.70 and ≥ 0.60+0.05), G2 ✓ (simple 1.00,
0 simple regressions), G3 ✓ (unsafe 0.02 ≤ 0.02; compiled-output hallucinated
leaves 0; raw attempts 0), G4 ✓ (0.99), G5 ✓ (0.99), G6 ✓ (0.714 ≥ 0.70),
**G7 ✗ (0.15 > 0.10)**.

## What the holdout established

1. **The GRS grounding/composition separation generalizes.** With the
   serialization failure removed by a ~90-line deterministic canonicalizer
   (the ONLY change vs the rejected Stage A arm; the B1 prompt is
   byte-identical), refined GRS is the best frontend on every primary
   dimension: +21pp over H0 (p=0.0011), capacity 8.6%→65.7%, NL 42.9%→71.4%,
   simple controls undamaged (100%), invented permission 14%→2%, hallucinated
   semantic content zero, at 2 calls/policy.

2. **PSB collapses on realistic active-voice policies.** The frozen PSB graph
   interface lets the model attach ACTOR nodes carrying invented
   non-catalog atoms ("Lock keepers may drain…" → actor:lock_keeper as a
   condition literal), and the frozen compiler accepts any typed atom — 54 of
   83 PSB errors are this single failure mode. The PSB dev corpus was
   passive-voice and never exposed the channel. All H0+PSB hybrids inherit
   the collapse (HP1 26%, router-caused regressions 43).

3. **Retention trades coverage for safety, as designed.** C3a (H0+GRS retain)
   reaches 91.5% definitive accuracy but only 59% definitive coverage; the
   three-way variant is unresolved on 83% of cases (PSB disagrees with
   everything). Retention is a downstream safety mechanism, not a frontend.

4. **H0's residual failure modes are confirmed and bounded.** MODALITY 27
   (per-clause modality globalization + invented permission; 14 unsafe
   cases), CONDITION 5, EXCEPTION 4 — consistent with PHV1.

5. **The C2 regressions are named and semantic, not format**: 4×
   negation-in-condition slips (WHEN(F1) instead of WHEN(NOT(F1)); both
   C2 unsafe cases are of this class), 3× REQUIRE separate-vs-together
   composition (SEPARATE(F1,F2) in one rule is satisfied by any clause;
   two rules or TOGETHER are not), 2× grounder atom misses. These are the
   residual GRS limits at 15% of H0-correct cases — the exact budget the
   frozen G7 gate set at 10%.

## Development phase (disclosed, pre-holdout)

- Stage A offline (zero new calls): HP1 81.8%/HP3 gold-in-set 88.6% on the
  sealed PSB corpus; H0+GRS oracle union 96.4%; witness gold cross-check
  44/44 (behavioral merge-equivalence witness, incl. the separate-REQUIREMENT
  capacity subtlety).
- Stage B dev (GRS Stage A corpus only): B3-replay canonicalizer recovered
  all 5 DSL-invalid sealed outputs (validity 100%, accuracy 96.4%, identity
  51/51 — format correction ≠ semantic correction); live B2/B3/e2e arms;
  final boundary = frozen B1 prompt + canonicalizer (simplest successful).
  One disclosed invalidation: the first e2e-canon run was corrupted by a
  runner closure bug (spurious repairs; untainted primaries compiled 53/56);
  re-run fresh as e2ecanon2 under devfreeze2b.

## Pairwise complementarity (same 100 cases)

| Pair | both | A-only | B-only | both-wrong | oracle union | agree (catalog) | wrong-agree |
|---|---|---|---|---|---|---|---|
| H0/PSB | 8 | 52 | 9 | 31 | 69 | 8/84 | 0 |
| H0/GRS | 51 | 9 | 30 | 10 | **90** | 55/96 | 4 |
| PSB/GRS | 16 | 1 | 65 | 18 | 82 | 18/86 | 2 |

Oracle unions are diagnostics only. H0+GRS complementarity (90/100) is the
strongest pairing signal; GRS dominates PSB (65 GRS-only vs 1 PSB-only).

## Terminal decision

Per the preregistered hard stop: **standalone Policy research ends here.**
The frozen verdict is `KEEP_H0` — H0 remains the promotion-grade frontend
under the frozen gates — while the measured Pareto frontier records that
GRS-refined is significantly more accurate and safer but exceeds the frozen
regression budget (15% vs 10%) with named residual semantic failure modes
(negation-in-condition, REQUIRE conjunction shape, grounding misses). Any
adoption of GRS-refined within Guardian composition (never as a standalone
research line) should carry these three named limits and the 2-calls/policy
cost. PSB is not promotable in its frozen form on active-voice policies.

Next stage per the user's protocol: Guardian Composition / E2E
(Policy + Goal + Binder + Identity + Evidence + Temporal/Effects + Claims +
Core + Certificates).

## Artifacts

`outputs/vnext/policy_final_holdout_v1_*` (freeze, benchmark, 4 sealed
prediction arms, seals, results, per-case, failure audit, smoke),
`outputs/vnext/policy_final_v1_offline_audit.json`,
`outputs/vnext/policy_final_v1_grs_dev.json` (+ dev freezes/canon audit),
bundle `download/policy_final_cycle_results{,.tar.gz}`.
