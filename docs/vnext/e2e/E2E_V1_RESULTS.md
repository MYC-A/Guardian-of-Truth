# E2E V1 — Results (fresh holdout, 112 cases, sealed before gold)

Model: qwen3.8-flash (BAI, temperature 0, one attempt per input).
Arms E0-E4; oracle substitutions post-seal. Gold joined only after sealing
(seal verification: OK).

## 1. Primary metrics

| Arm | certified coverage | certified accuracy | correct-def. coverage | ERROR recall | NO_ERROR recall | UNRESOLVED | false NO_ERROR | false ERROR | uncertified |
|-----|--------------------|--------------------|-----------------------|--------------|-----------------|------------|----------------|-------------|-------------|
| E0 (H0+Cons) | **0.554** | 0.855 | 0.473 | **0.759** | **0.375** | 0.446 | **0** | 9 | 0 |
| E1 (GRS+Cons) | 0.509 | 0.842 | 0.429 | 0.741 | 0.250 | 0.491 | **0** | 9 | 0 |
| E2 (H0+RF)   | 0.268 | 0.800 | 0.214 | 0.389 | 0.094 | 0.732 | **0** | 6 | 0 |
| E3 (GRS+RF)  | 0.259 | 0.793 | 0.205 | 0.389 | 0.063 | 0.741 | **0** | 6 | 0 |
| E4 (retention) | 0.116 | 0.615 | 0.071 | 0.148 | 0.000 | 0.884 | **0** | 5 | 0 |

Status counts (E0): PROVED_ERROR 50, PROVED_NO_ERROR 12, UNRESOLVED 50.
World metrics: E0 mean 1.23 worlds/case, p95 3, max 4 (no budget overflow on
any case); E4 mean 2.21, max 8 (retention doubles the world space and still
never overflows the 4096 budget at this corpus scale).

## 2. Paired comparisons (exact two-sided McNemar)

| Pair | corrections | regressions | p |
|------|-------------|-------------|---|
| E1 vs E0 (GRS effect) | 2 | 7 | 0.180 |
| E2 vs E0 (RuleFrames effect) | 1 | 30 | <1e-6 |
| E3 vs E0 (strongest singleton) | 4 | 34 | 1e-6 |
| E4 vs E3 (retention value) | 0 | 15 | 6.1e-5 |
| E4 vs E0 (full architecture) | 0 | 45 | <1e-6 |

* GRS is statistically indistinguishable from H0 at this scale (slightly
  worse coverage; its multi-clause advantage did not materialize as net
  E2E gain).
* RuleFrames+E5 significantly REDUCES definitive coverage: the RF frames'
  semantic content keys bind to tools less reliably than the Conservative
  frames, leaving unresolved markers (absorbed by nothing).
* Retention (E4) mostly converts would-be definitives into UNRESOLVED
  (disagreement worlds) with zero corrections anywhere — at V1 frontend
  quality, retention buys safety-conservative abstention, not accuracy.

## 3. Safety

* **false certified NO_ERROR = 0 in every arm** (the critical direction).
* false certified ERROR (E0: 9/112 = 8%): stale_state_claim x4 (the
  BOTH/freshness semantics resolves some stale contradictions as ERROR where
  the designed gold is UNRESOLVED), closed_safe_alternative_actions x2
  (alternative-authorization mismatch), inconsistent_trusted_evidence x1
  (INCONSISTENT resolves to ERROR when a read call separates contradictory
  evidence — documented V1 limitation), closed_safe_completed_action x1,
  failed_call_state_unknown x1.
* uncertified_definitive = 0 in every arm (hard gate satisfied).

## 4. Oracle attribution (error budget)

Definitive-correct counts (of 112): actual E0 = 53; Gold Policy = 53; Gold
Goal = 53; Gold Both = 53. Gold semantic substitutions do NOT improve the
outcome, and ORACLE_GOLD_BOTH reproduces E0's status on 107/112 cases. The
measured bottleneck is therefore NOT policy/goal frontend semantics: it is
the LOWER layers — operational binding success (semantic action keys ->
tool mappings), claim typing/binding, and closure mechanics. Improving H0 or
GRS alone cannot move E2E accuracy; the leverage is in the binding and claim
layers (and in corpus-side phrasing conventions).

## 5. Failure taxonomy (E0, wrong-or-abstaining cases)

CLAIM_SUPPORT 7, SEMANTIC_BEHAVIOR 11, POLICY_H0 10, GOAL_CONSERVATIVE 3,
FALSE_CERTIFIED_ERROR 3 (plus family-level counts in
`e2e_v1_failure_audit.json`).

## 6. Answers to the fifteen questions (spec 193)

1. GRS: no measurable E2E improvement (parity, p=0.18). 2. Rule Frames:
   significant coverage regression. 3. H0 remains necessary (GRS alone is not
   better). 4. Conservative remains necessary after RuleFrames (RF strictly
   worse). 5. Decisive disagreements: retention converts 45 would-be
   definitive-correct outcomes into UNRESOLVED with 0 corrections. 6.
   Absorbed disagreements: 0 measured. 7. One frontend saving the other: no
   case where retention corrected the singleton's wrong verdict. 8.
   Common-mode errors remain (oracle shows semantics substitution changes
   nothing; binding/claim layers are common-mode). 9. Lowering/binding IS a
   main bottleneck (oracle attribution). 10. Binding: yes (operational
   binding failures dominate UNRESOLVED markers). 11. Claim evidence: second
   main bottleneck (CLAIM_SUPPORT failures + stale-state semantics). 12.
   Certificates rejected: 0 on this holdout (the checker rejected nothing —
   downgrades happened at premise level, recorded as UNRESOLVED). 13.
   Certificate-gated safety retained: all definitives certified. 14. World
   explosion from multi-frontend: bounded (E4 max 8 worlds; no budget
   overflow) but coverage-halving. 15. Guardian as a useful proof-based
   evaluator: yes in the conservative configuration — 55% certified coverage
   at 85% accuracy with zero false-acquittals is usable for audit-mode
   deployment; multi-frontend retention is not justified at V1 frontend
   quality.
