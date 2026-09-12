# Cycle 2 trusted tool-effect ceiling

## Verdict

`T1_CEILING_NOT_ESTABLISHED_REGISTRY_INSUFFICIENT`.

The experiment runs the same frozen `X5_CORE` twice. `X5(T0)` receives only
schema/name contracts with unknown effects; `X5(T1)` additionally receives the
seven reviewed contracts in `contracts/tool_effects_v1.json`. No other policy,
claim, binding, solver, or binary-decision component changes. The evaluated X5
implementation was frozen in Guardian commit `b98414a` before external
predictions.

## Inputs and coverage

The internal file SHA-256 is
`8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`.
The external cases SHA-256 is
`d1863e7651c81afb73550b6ee2c984435aacda76d1a96e1b5c4dd5b380b0fedd`.
The T1 registry SHA-256 is
`a58aacb52ada327767fb524500e88ea846917c340a658e12d72366ba4485601a`.

| Scope | Called tools | Trusted T1 | Coverage |
|---|---:|---:|---:|
| Internal, all | 60 | 7 | 11.67% |
| Internal positives | 46 | 7 | 15.22% |
| Internal X0 false negatives | 23 | 5 | 21.74% |
| External, all | 259 | 0 | 0% |
| External positives | 218 | 0 | 0% |
| External X0 false negatives | 218 | 0 | 0% |

External source-derived signatures document names and arguments, not business
effects. They therefore cannot be promoted to T1 from naming alone.

## Measured result

On the 46 internal rows, both T0 and T1 have TP=7, FP=0, FN=16, TN=23,
overall recall 0.3043, precision 1.0, internal coverage 0.6087, and conditional
recall 0.5 over 14 internally resolved positives. T1 adds five confirmed-effect
evidence records but changes no internal or binary verdict.

On the 100 external target steps, both variants have TP=0, FP=0, FN=85,
TN=15 and 100/100 `UNRESOLVED`; conditional recall is undefined because there
are no internally resolved positives. T1 adds no evidence record there.

This is evidence that the *current seven-contract subset* does not improve X5.
It is not evidence that a sufficient trusted T1 has zero ceiling. T2/T3 remain
blocked until explicit docs, source, executable tests, or a trustworthy
benchmark specification cover the tools in positives and current false
negatives. The machine-readable result is
`outputs/cycle2/tool_effect_results.json`.

## Invariants

The run preserves: attempted call is not confirmed effect; failure is neither
completion nor no-effect; HTTP success is not business success; tool names do
not establish semantic effects; missing effects remain `UNKNOWN`.
