# Full-source diagnostic results

**No improvement is demonstrated.** Four successful HTTP calls used 72,543 known
tokens, with no retries/fallbacks. Both arms used `ministral-14b-2512`, the same
lossless source/address packet, temperature 0 and 2,500 output cap. Inputs were
not truncated. Two known development cases have executed pairs; the longer
banking task003 pair was BUDGET_STOP. This is not the historical Gemma A0 pilot,
not all valid46, and not a new holdout.

Frozen source commit: `b33c77137db56a4f9b874403a4a3ff385ad7bd11`.
Protocol SHA256: `eab5e5fd6f9fefd675a6341040fa00bf3cf6cef4d79733bf08cbfb34964711bc`.
The initial zero-inference preparation is preserved separately; its request order
was changed before any model output to make the source-clear role probe affordable.

## Same executed cases, including failures

| Current move | Official binary gold | Fresh D0 | Fresh P3 | Cause audit |
|---|---:|---|---|---|
| Expired telecom line | 1 | ERROR | UNKNOWN, invalid target ID | D0 charges old calls and says the current resume is correct. P3 misses the contract-expiry prohibition and selects incorrect roles. |
| Banking verification request | 0 | NO_ERROR | UNKNOWN, invalid target ID | D0 correctly assesses the request. P3 interprets the user source as a current account-opening action. |

On exactly these **two transport-executed pairs**, with UNKNOWN→0:

| Arm | TP | FP | FN | TN | Binary F1 | Decided moves |
|---|---:|---:|---:|---:|---:|---:|
| D0 direct | 1 | 0 | 0 | 1 | 1.0000 | 2/2 |
| P3 relationships + code | 0 | 0 | 1 | 1 | 0.0000 | 0/2 |

Admission failures are included as UNKNOWN, not dropped to inflate coverage.
There are **zero fully admitted pairs**; a fully admitted comparative F1 is
undefined. The frozen scorer's zero-row numeric defaults must not be read as a
measured F1; the post-hoc audit explicitly records null for that comparison.
The three-selected-row operational table additionally includes the budget-stop
positive as FN in both arms: D0 F1=0.6667, P3 F1=0. This happens to match a historic
aggregate numerically for D0 but is an entirely different population.

**D0's one binary TP has the wrong cause.** It accuses historical `make_payment`
at h27 and h30 (the latter is a USER call), then explicitly calls the current
`resume_line` correct. The actual new error is the current line's expired contract.
Do not count this as a correctly recovered process/state violation or report
two-case F1=1 as an improvement over the 46-row archival baseline.

## Representation versus semantics

P3 produces strict-schema-valid JSON in **2/2** executed replies, but source/candidate
admission succeeds in **0/2**. It emits business ID `L1002` instead of native target
`t0`; on the negative it emits user source `h2`, despite no current native target.
Removing recursive Formula and witness paths therefore does not remove source
role selection errors. The current schema uses validated string selectors rather
than wire-level per-packet enums; it does not make invalid target IDs impossible.
The validation rejects these replies without repairing them.

For the telecom native rule, P3 picks `suspension_start_date`, a historical
`phone_number` as the target identity, the current call's `line_id` as a result
identity, and an argument from the write declaration instead of the read.
It selects **PERMIT** and claims no date restriction, contrary to the explicit
contract-end prohibition. The wrong meaning remains visible independently of
the target-ID admission error. The one required native norm is recovered **0/1**.

For the negative, P3 invents field selectors and attaches account-opening
requirements to a request for identity. It partly recognizes that proposed
balance/age requirements are unsupported for personal accounts, but still emits
them in an applicable process. UNKNOWN→0 matches the negative gold through
abstention, not correct role grounding. No automatically correct, applicable
native rule is demonstrated by this pilot.

Detailed source/selector audit:
[posthoc_failure_audit.json](../../outputs/research_v5/paired_role_diagnostic/posthoc_failure_audit.json).
Raw replies and exact request bodies are retained beside
[predictions](../../outputs/research_v5/paired_role_diagnostic/predictions.json).
No cached prediction, relation or gold was altered to improve scores.

## Costs and reproduction

| Arm | HTTP | Known/charged tokens | Summed HTTP seconds |
|---|---:|---:|---:|
| D0 | 2 | 35,231 | 10.347 |
| P3 | 2 | 37,312 | 20.917 |
| Total | 4 | 72,543 | 31.264 |

P3 costs 2,081 extra tokens (+5.91%) and about twice the recorded HTTP time, with
one additional executed-case FN and no cause-valid positive recovery. Token totals
include provider-reported input/output usage, not estimates. Unknown usage is zero;
no price/invoice or GPU deployment cost is inferred. Budget reservations used the
declared conservative public-tokenizer rule. Two logical read-only operations
(provider metadata and public tokenizer download) are separate from inference.

Replay on the server **and Windows** is byte-identical, with unchanged ledger
and zero HTTP. The Windows wrapper relocates only the hash-verified public
tokenizer address; protocol, source, request and reservation hashes stay enforced.
Prediction SHA256: `4530c2d00cf5899abd8c8c2fdfb45e32ccd52cb5a04d3f84f8bf4ffd01b8bf07`.
Ledger SHA256: `73550ca7ea090176663e83c3b17f5db365e35e28abaa41667cddb065d29391a0`.
See [server replay](../../outputs/research_v5/paired_role_diagnostic/offline_replay.json)
and [Windows replay](../../outputs/research_v5/paired_role_diagnostic/portable_offline_replay.json).
