# E2E V1 — Terminal Decision

Per the frozen decision machine (docs/vnext/e2e/E2E_V1_EXPERIMENT_PROTOCOL.json):

```
E2E_LIMITATION_CONFIRMED
```

No arm achieves correct-definitive coverage >= 0.5 at unsafe-definitive
rate <= 0.05 (best: E0/E1/E3 at 0.246; ceiling given the corpus mixture:
0.739).  The promotion gates fail for every arm:

- E4_vs_E0 CDC gain >= 5pp: FAIL (-7.2pp, a REGRESSION; 0 corrections vs
  5 regressions, McNemar p=0.0625).
- Best-arm unsafe <= 0.05: PASS (0.000 everywhere) — safety holds; coverage
  does not.
- PROVED_ERROR recall >= 0.5: FAIL (best 0.219).
- McNemar p < 0.05 for any frontend substitution: FAIL (all p=1.000).

## What is CONFIRMED about the architecture

1. The composition is SOUND: 85/85 definitive verdicts across five arms
   carry valid re-derivable E2E certificates; zero unsafe definitives; zero
   uncertified definitives; zero crashes; hard invariants PASS.
2. The certificate-gated all-world Core is NOT the bottleneck: the solver,
   lowering and checker perform exactly as specified (verbatim v3
   equivalence, closure-gated NO_ERROR, decisive-unknown UNRESOLVED,
   independent violations surviving unrelated unknowns).
3. Frontend substitution (H0/GRS, Conservative/RuleFrames) is NOT the E2E
   bottleneck: the standalone-policy differences (+21pp GRS CDC) do not
   survive composition — they are masked by the layers below.
4. Retention (multi-frontend axes) is a NET REGRESSION at this bottleneck
   level: extra worlds carry extra unresolved-marker exposure with zero
   measured salvage.

## The actual residual bottleneck (ranked, machine-verified)

1. CLAIM layer: nondeterministic typing of response spans → global hard
   markers masking proven violations (~32/69 cases; +11.6pp oracle).
2. BINDING layer: abstention on unexercised semantic atoms (~12/69).
3. GOAL outcome channel: entity-check grounding rejections.

## Hard stop

Per the preregistered hard stop, standalone E2E V1 research ENDS here.  Any
follow-up must be a NEW separately-registered line.  The evidence points
the next line at the claim channel (a variance-resistant claim front end or
a claim-marker scoping change), not at more semantic frontends.
