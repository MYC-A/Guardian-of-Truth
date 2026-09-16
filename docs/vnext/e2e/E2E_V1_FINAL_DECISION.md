# E2E V1 — Final Decision

## Decision machine (preregistered, spec 188)

Inputs (fresh holdout, 112 cases, sealed before gold):

* E0 (H0 + Conservative): certified coverage 0.554, accuracy 0.855,
  ERROR recall 0.759, NO_ERROR recall 0.375, false-certified-NO_ERROR 0.
* E1 (GRS): statistically indistinguishable from E0 (McNemar p = 0.180),
  slightly lower coverage.
* E2/E3 (RuleFrames + E5): significant coverage regression vs E0
  (p < 1e-6; the RF frontend's bindings fail more often).
* E4 (retention): coverage 0.116 vs E0's 0.554; 45 regressions, 0
  corrections (p < 1e-6). Retention at V1 frontend quality produces
  abstention, not accuracy.
* Oracle attribution: gold policy/goal substitutions do not improve any
  outcome (53/112 definitive-correct in all configurations); the residual
  bottleneck is the lowering/binding and claim layers.
* Hard gates: uncertified_definitive = 0 (all arms); false-certified
  NO_ERROR = 0 (all arms); predictions sealed before gold = 100%.

## TERMINAL DECISION: **KEEP_CONSERVATIVE_E2E**

The complex candidates do not provide a real E2E improvement at V1 frontend
quality under the frozen model (qwen3.8-flash, one attempt per input):

1. GRS does not beat H0 end-to-end (its multi-clause advantage exists
   architecturally but nets out to parity).
2. RuleFrames + E5 significantly reduces usable certified coverage through
   binding-convention mismatches.
3. Retained-interpretation multi-frontend composition (E4) converts
   disagreement into UNRESOLVED without a single correction — the
   multi-frontend architecture is implemented, world-safe and measurable,
   but not yet worth its coverage cost.

Promoted configuration: **E0-class guardian** — H0 policy frontend +
Conservative goal frontend, T1 trusted effects, ambiguity-preserving
identity, all-world proof core, certificate-gated verdicts, behavioral
closure for PROVED_NO_ERROR.

## Next steps (post-decision, out of scope for V1)

1. Attack the measured bottleneck: operational binding robustness (semantic
   action key -> tool conventions) and claim typing/binding — both are
   lower-layer, frontend-independent (the oracle proved this).
2. Revisit retention only after single frontends disagree *behaviorally*
   rather than representationally.
3. Scale the holdout (112 -> 500+) for tighter McNemar power on E1-vs-E0.
4. Improve stale-contradiction semantics (the largest false-ERROR source).

Per spec 196: the system already never converts its own uncertainty into
false certainty (zero false-certified NO_ERROR everywhere), and proved
violations survive unrelated unknowns. STOP — terminal decision issued.
