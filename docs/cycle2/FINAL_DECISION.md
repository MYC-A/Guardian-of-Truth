# Cycle 2 final decision

```text
PRODUCTION:
  KEEP X0 V5.3 unchanged. No candidate earned promotion.

BEST RESEARCH ARCHITECTURE:
  X5_CORE as an auditable decomposition scaffold, not as a winning verifier.
  Its present end-to-end effectiveness is rejected; external coverage is 0%.

BEST SEMANTIC FRONTEND:
  P1 direct final-rule generation for this admitted model and frozen compiler.

BEST CLAIM EXTRACTOR:
  C2 deterministic response spans + LLM typed map.

BEST EXTERNAL RESULT:
  No reliable winner. Two valid X1 calls were correct, but 98/100 failed.
  All deterministic candidates have F1=0 on the independent holdout.

SUPPORTED:
  P1 > P2 on paired policy semantics; C2 strongly improves claim-span recall;
  X5 is genuinely isolated and exposes UNKNOWN; exact G1 adds 0 TP and 0 FP;
  L2 exhaustive compile-once remains the long-context default; 12 invariants pass.

NOT ESTABLISHED:
  X1 external quality; P3; a sufficient T1 effect ceiling; provider cost;
  any useful fast/slow X6 routing rule; absolute benchmark quality without
  independent reviewer metadata.

REJECTED:
  Current P2 typed IR as an improvement over P1; current X5 as a production
  replacement; G1 on this holdout; L1 top-k as default; T2/T3 before T1 coverage.

NEXT BOTTLENECK:
  Open-vocabulary policy/goal-plan semantics plus normalized claim typing and
  reliable inference transport—not more retrieval and not a larger effect miner.
```

## Answers required by the protocol

1. **Was P2 worse than P1 without transport contamination?** Yes. On 90 jointly
   valid cases P1=0.7778, P2=0.6556, delta=-0.1222, bootstrap 95% CI
   `[-0.2222,-0.0222]`, McNemar p=0.0433.
2. **Did typed PolicyMeaning help?** Not overall. It helped some necessary
   conditions, exceptions, negation and cross-reference cases, but lost more on
   permission, actor, effect/action identity, temporal and provenance semantics.
3. **Real claim coverage?** C0 recall 0.1020; C1 0.0068; C2 0.8163 with precision
   0.9449 and operational reliability 0.9651.
4. **How many cases does the new solver resolve?** Internal: 28/46. External:
   0/100.
5. **How many X5 zeros are proved safe versus unresolved?** Internal CORE has 21
   `PROVED_NO_ERROR` and 18 `UNRESOLVED`; external has 0 proved safe and 100
   unresolved.
6. **Does X5_CORE add a true positive?** No. Internal it finds seven positives
   already covered by X0; external it finds none.
7. **Does X5_PROTECTED improve X0?** No; changed predictions, added TP, and added
   FP are all zero internally and externally.
8. **Does exact G1 work on the new holdout?** No. X4 gates every case off, so G1
   is identical to X0 and adds no TP.
9. **Does G1 preserve precision?** It emits no positive, so precision is
   undefined—not evidence of high precision.
10. **Holistic X1 versus formal architecture?** The two valid X1 calls detect
    two true errors that all formal arms miss, suggesting useful semantic signal,
    but 2% reliability makes comparative quality `NOT ESTABLISHED`.
11. **What happens on genuinely external step-localized data?** All frozen
    deterministic arms collapse to zero recall. This falsifies transfer of the
    current rule vocabulary to open goal/plan drift.
12. **Where do errors remain?** Primarily policy meaning/compilation, claims and
    missing trusted effects; the unresolved-to-zero binary adapter exposes the
    consequence. Binding/solver cannot be isolated until upstream coverage rises.
13. **What is cheaper at equal quality?** Not established end-to-end. Within the
    claim task, C2 is both much better and lighter than C1 (106,779 versus 120,605
    tokens; p50 13.75 versus 15.75 seconds). Provider billing was not audited.
14. **Should production V5.3 change?** No. X0 itself transfers poorly to this
    different external task, but no alternative met reliability, coverage, and
    statistical promotion gates.

The distinction is deliberate: the X1 *experiment* was transport-limited; this
does not prove the holistic architecture failed. X5 and G1, however, executed
validly and did fail their current end-to-end promotion hypotheses.
