# Cycle 2 X5 execution audit

## Architecture under test

`X5_CORE` executes policy compilation, obligation construction, trusted tool
effects, evidence ledger construction, response-only claim extraction, binding,
and the four-valued solver. It never reads incumbent X0 findings.

`X5_PROTECTED` is the production-oriented composition `X0 OR safe X5_CORE`.
The implementations used for external predictions were frozen in commit
`b98414a`. Isolation is enforced by a test that replaces `Detector` with a
failure sentinel while `X5_CORE` runs.

## Internal execution

On all 46 internal examples:

| Arm | TP | FP | FN | TN | F1 | Internal coverage | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|
| X5_CORE | 7 | 0 | 16 | 23 | 0.4667 | 0.6087 | 0.3913 |
| X5_PROTECTED | 12 | 0 | 11 | 23 | 0.6857 | 0.6087 | 0.3913 |

Core solver states are 7 `PROVED_ERROR`, 21 `PROVED_NO_ERROR`, 18
`UNRESOLVED`, and 0 `INCONSISTENT`. Core and X0 actively agree in 25 cases and
actively disagree in three. Another 18 comparisons involve the binary fallback
rather than a resolved X5 result.

Protected decision sources are: `BOTH` 7, `X0` 5, `DEFAULT` 18, and `FALLBACK`
16. Despite genuine component execution, protected X5 changes zero X0 binary
predictions, adds zero true positives, and adds zero false positives.

## External execution

On 100 independently sourced target steps, both X5 variants have TP=0, FP=0,
FN=85, TN=15 and binary F1=0. Every core result is `UNRESOLVED`; internal
coverage is 0 and the binary fallback rate is 1.0. All apparent agreement with
X0 is therefore `CORE_UNRESOLVED_FALLBACK_MATCHES_X0`, not architectural
agreement based on proved results.

The main cause is representational mismatch: this benchmark describes
open-vocabulary goal/plan drift, while the frozen X5 compiler has executable
obligations only for a narrow policy subset and has no trusted effect contracts
for external tools. It would be unsound to turn those unknowns into violations
or safe results by guessing from tool names.

Per-case mandatory telemetry—including policy/claim/tool coverage, evidence and
binding counts, solver status, binary result, decision source, and fallback—is
stored in `outputs/cycle2/x5_execution.json`.
