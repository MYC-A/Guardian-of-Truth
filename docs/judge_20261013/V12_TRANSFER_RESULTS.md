# V12: full-profile transfer, frozen comparison

All 1893 rows completed the original full open/MAX control and exact final
scoring. Both verifier arms evaluated the same 757 actual positive candidates.
No input trimming, missing-final fallback, refill or threshold selection.

| Variant | TP | FP | FN | F1 | FP removed | TP lost |
|---|---:|---:|---:|---:|---:|---:|
| Frozen full open/MAX, quota .40 | 450 | 307 | 123 | .676692 | 0 | 0 |
| Base 35B candidate verifier | 450 | 277 | 123 | .692308 | 30 | 0 |
| Previous V7 LoRA candidate verifier | 447 | 280 | 126 | .687692 | 27 | 3 |

The base verifier improved the point estimate in each of the three domains.
The previous LoRA also improved the overall point estimate relative to control,
but lost three healthcare true positives and did not outperform the base
verifier. These results do not establish a benefit from V7 training.

The dataset was previously used with 4B adapters. Status remains
EXPLORATORY_PREVIOUSLY_USED_EVAL, not an untouched validation or private-test
gain. No production promotion. No bootstrap is claimed because the original
candidate-only reviews do not cover every possible quota-resampled candidate.

Archive: `A:/Guardian-submissions/guardian-v12-transfer-20261020/evaluation-v12-export.tar.gz`.
Results SHA256: `91e218519638a12cac1d459abba7d64e0a877b8dd291c575b4ae0e20e21c301f`.
Independent offbox reconstruction completed in `OFFBOX_TRANSFER_AUDIT.json`
in the same directory: exact label/ID binding, primary tokens, candidate prompt
tokens, source-quote admission, request receipts, adapter binding, MAX/quota
decisions and aggregate/domain metrics. Raw GPU logits are not archived, so
the audit checks the exact-score producer contract rather than recomputing
raw logits. This audit required no additional GPU inference.

The V15 native training recipe was fixed before these evaluation results.
The user's subsequent two-hour allocation changes only execution deadlines,
not training labels, pair selection rules, loss, layers, epochs or threshold.
