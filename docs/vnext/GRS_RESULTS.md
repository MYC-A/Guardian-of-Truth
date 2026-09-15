# GRS — Grounded Rule Synthesis: Results (GRS_V1)

Status: RUN_COMPLETED_SEALED_VERDICT_REJECTED — machine-verified.
Preregistration: `docs/vnext/GRS_PREREG_GATES_V1.json` (committed before any
inference request of the cycle; freeze machine-verified prereg/runner gate
identity, H0 identity continuity vs the sealed PSB freeze, and corpus
composition). Runner: `scripts/evaluate_vnext_policy_grs.py`. Sealed
artifacts: `outputs/vnext/policy_grs_stage_a_v1_*`.

## 1. What was tested

GRS was the single authorized reopening of standalone Policy research after
the PSB stop rule, testing a PRINCIPALLY different decomposition rather than
an optimization of viewed holdout performance:

```
NL POLICY -> grounded semantic inventory -> LLM synthesizes rules ONLY from
inventory IDs -> small typed DSL -> deterministic validator -> compiler ->
behavioral program (same frozen v3 program space as H0/PSB)
```

Main hypothesis (preregistered, falsifiable): the dominant error mode of
current Policy frontends arises because one LLM call is simultaneously
responsible for semantic grounding and structural composition; if factual
leaves are grounded in advance and closed while the LLM only composes
structure over them in a small typed DSL, compositional Policy parsing
becomes substantially more accurate and less hallucination-prone.

Two stages were preregistered. Stage A (composition ceiling) gives the model
a CORRECT grounded inventory (oracle: facts with exact spans + modality and
relation surface markers, neutral F#/M#/R# IDs, no attachment information)
and measures whether it can compose the correct ruleset. Stage B
(end-to-end: grounder -> inventory -> same frozen synthesizer) runs only if
Stage A passes. Arms: A0 = frozen H0 flat single-parse (byte-identical
chain C-ALR -> PHV1 -> PSB, machine-verified), A1 = oracle-inventory GRS.

Benchmark: 56 NEW gold-by-construction cases, 15 cohorts, zero shared word
8-grams with V4+V5+PHV1+PSB, zero internal duplicates, 11
H0-unrepresentable capacity cases (merge-equivalence), oracle evidence
sufficiency machine-checked, one empty-gold control whose world surface
exposes over-regulation. Model: bai / qwen3.8-flash (same as H0/PHV1/PSB —
no capacity confound). One frozen syntactic repair re-ask per case.
Predictions sealed before gold join; scoring, gates and audit fully
deterministic; no LLM judge anywhere.

## 2. Machine-verified Stage A result

| metric | A0 (frozen H0) | A1 (oracle GRS) |
|---|---|---|
| behavioral case correctness | 39/56 = **69.64%** | 49/56 = **87.50%** |
| Wilson 95% CI | see results JSON | [76.4%, 94.5%] |
| AST / schema validity | 56/56 = 100% | 51/56 = **91.07%** |
| capacity subset (H0-unrepresentable, n=11) | 3/11 = 27.27% | **9/11 = 81.82%** |
| NL prose stress (n=3) | 1/3 = 33.33% | 2/3 = **66.67%** |
| binding attachment micro-F1 | 0.848 | **0.942** |
| invented (unsafe) permission cases | 12/56 = 21.43% | **0/56 = 0%** |
| unsupported semantic leaves in compiled programs | n/a | **0 by construction** |
| hallucination attempts (all persisted outputs) | n/a | **0** |
| resolved coverage | n/a | 91.07% |

Paired A1 vs A0: corrections 15, regressions 5, delta +17.86pp, Newcombe
paired CI [+3.6pp, +31.6pp], exact McNemar p = 0.0414, correction precision
0.75. Regression gate: 5 of 39 H0-correct cases regressed = **12.82%**.
Structural-subset delta +19.6pp. Efficiency: A1 costs 1.09 requests/case
(same as H0: 8.9% repair rate), 1878 tokens/case vs 1697 (H0), median
latency 5.2s vs 8.4s (the DSL answer is much shorter than the flat JSON).

Cohort detail (A0 -> A1): condition_plus_exception 0% -> 100%;
per_clause_actors 0% -> 100%; separate_clauses_modalities 0% -> 100%;
temporal 75% -> 100%; multi_axis 67% -> 83%; scope_togetherness 100% ->
100%; exception 100% -> 100%; provenance_identity 100% -> 100%;
simple_controls 100% -> 100%; condition 100% -> 75%; if_vs_only_if 100% ->
75%; negation 100% -> 75%; modality 100% -> 33%; nl_prose_stress 33% ->
67%; empty_gold_control 100% -> 100%.

## 3. Frozen gate evaluation -> verdict

| gate | required | measured | pass |
|---|---|---|---|
| A1 behavioral | >= 85% | 87.50% | PASS |
| A1 AST validity | >= 95% | 91.07% | **FAIL** |
| A1 capacity subset | >= 75% | 81.82% | PASS |
| A1 NL stress | >= 75% | 66.67% | **FAIL** |
| H0-correct regression rate | <= 10% | 12.82% | **FAIL** |
| A1 - A0 delta (overall or structural) | >= +10pp | +17.9pp / +19.6pp | PASS |

**Verdict: REJECT_GRS_COMPOSITION** (three of six preregistered gates
failed). Per the frozen decision table, Stage B was NOT run; the runner
machine-refuses `freeze-b` on this verdict (verified: exit with `Stage B
refused: Stage A verdict is REJECT_GRS_COMPOSITION`). Per the user's hard
stop (sections 60-61): STOP standalone Policy research permanently — no
GRS-v2, no grammar-repair cycle, no new graph format, no verifier.

## 4. Failure analysis (deterministic post-seal audit, no LLM judge)

A0's 17 errors: 10 CONDITION_EXCEPTION_ERROR + 7 MULTI_CLAUSE_ERROR — the
known flat-representation limits (relation binding and per-clause
divergence).

A1's 7 errors decompose into exactly two modes:

1. **DSL serialization slip (5 cases, 8.9%)**: every one of the five
   invalid outputs (and their repair re-asks) is the SAME malformation —
   the model omits the `RULE(...)` wrapper and emits
   `RULESET(PERMIT, F3, WHEN(F1), ACTOR(F2))` instead of
   `RULESET(RULE(PERMIT, F3, WHEN(F1), ACTOR(F2)))`. The machine error was
   fed back in the frozen repair re-ask and the model repeated the shape.
   Affected: condition::c03, if_vs_only_if::io04, modality::m01,
   modality::m03, negation::n01.
2. **Composition errors on the two hardest cases (2)**:
   multi_axis::x03 and nl_prose_stress::np02 — multi-clause cases where a
   gate was attached to the wrong rule / with the wrong role
   (CONDITION_EXCEPTION_ERROR class).

All five H0-correct regressions ARE the five serialization-slip cases —
i.e., the regression gate failure is entirely a format failure, not a
semantic misreading (the same shape PSB exhibited, at a lower rate: 12.8%
vs 29.2%). The NL-stress gate failed on 1 of 3 prose cases. No case
exhibited an invented fact, an out-of-grammar operator or a free-text leaf
in any persisted output; the closed leaf vocabulary held absolutely.

## 5. Interpretation (historical separation maintained)

- The GRS decomposition is directionally VALIDATED exactly where its
  theory predicted: with facts closed and grounded, per-clause divergence
  classes that H0 cannot express moved from 0% to 100%, attachment F1 rose
  to 0.942, hallucinated semantic content went to literal zero, and
  invented permission went from 21.4% (H0) to 0% — while costing the same
  requests/case and FEWER tokens and LESS latency than H0.
- But the preregistered RELIABILITY standard was not met on this frozen
  model: 91.07% AST validity (< 95%) with a single systematic, repair-
  resistant `RULE(...)`-wrapper omission; 66.7% NL prose (< 75%); 12.8%
  H0-correct regressions (> 10%). Under the frozen no-adaptive-repair rule
  (no prompt/grammar change after the first semantic request), these are
  terminal within this cycle.
- The composition ceiling with oracle facts is therefore 87.5% [76.4,
  94.5] on this benchmark — materially better than H0 (69.6%) and than
  PSB's graph arm (72.7% at 84.1% validity), but short of the 95%-validity
  / 85%-behavioral-with-95%-validity standard that integration would
  require of a frontend.
- Stage B (grounding bottleneck measurement) was never reached, so the
  A1-B1 decomposition question is NOT TESTED and remains open for any
  future separately-registered line.

## 6. Terminal decision

**REJECT_GRS_COMPOSITION -> STOP standalone Policy research permanently.**
This is the third and final architecture generation tested under the
stop-rule discipline (flat H0 -> structural graph PSB -> grounded rule
synthesis GRS). The standalone line ends with: H0 remains the only
promotion-grade frontend (95.77% controlled / 73.75% prospective PHV1),
now with two machine-verified diagnoses of why successors fail on this
model class — graph/DSL serialization burden (PSB 84.1%, GRS 91.1%
validity) and repair-resistant format assimilation — and one validated
invariant: closing the leaf vocabulary eliminates hallucinated semantic
content and invented permission entirely.

Next stage per the user's stop rule: integration / composition (Goal +
Policy + Binder + Evidence + Temporal/Effects + Core), with the H0
frontend, GRS's zero-hallucination/zero-unsafe-permission evidence carried
forward as design constraints (grounded inventories and closed leaf
vocabularies remain attractive for downstream stages), and the documented
limitations (relation binding, per-clause divergence, prose) to be absorbed
downstream by abstention / UNKNOWN / certificates / independent witnesses
and measured end-to-end.

## 7. Numbers are not comparable across lines

H0-V5 95.77% (controlled dev distribution), PHV1 73.75% (prospective
holdout), PSB 72.73% (binding-heavy causal corpus, H1), GRS A1 87.50%
(oracle-inventory diagnostic ceiling on the GRS Stage A corpus) are
separate implementations/distributions with different information
asymmetries (A1 sees a correct grounded inventory that H0 does not) —
never a unified learning curve.
