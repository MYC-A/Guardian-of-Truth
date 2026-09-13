# Paired outcome statistics v1

Status: IMPLEMENTED_SYNTHETIC_TESTS_ONLY. No blind labels have been opened and
no final X0/vNext outcome rows have been joined. This module is not a model
predictor, certificate checker or evidence of improved quality.

The downstream report accepts only already joined, case-unique, status-consistent
0/1 paired records after an external runner verifies the full prediction seal.
It reports each confusion matrix, F1/recall/FPR, balanced error, genuine Core
resolution, fallback rate, coverage, unresolved reasons, per-verdict certificate
counts/rates (null if no such verdict), category confusion, confidently wrong
definitive cases and exact
two-sided McNemar. The competition binary mapping is validated: ERROR=1,
NO_ERROR=0, UNRESOLVED=0, INCONSISTENT=1. A fallback is never a safety proof.
Claimed definitive status and independently certified resolution are counted
separately. Missing/invalid certificate cases are listed, and the headline Core
resolution rate includes only `certificate_valid=true` rows. The external runner
must actually invoke an independent checker; this statistics module never
validates a proof by trusting the status field.

The paired hierarchical bootstrap defaults to 5000 draws and seed 260913:
resample trajectory groups, then cases inside every selected group. Each sampled
pair stays paired. An undefined denominator yields null. A CI is emitted only
when every prespecified draw defines both compared metrics; no silent deletion
of degenerate draws. This strict rule can yield null CIs even with useful data,
which must be reported as an adequacy limitation, not a negative or positive gain.

Source-declared blind labels, category provenance, X0 predictions and native
Core outputs must be validated by a separate blind runner after its candidate
freeze and prediction seal. Transport/schema/latency/tokens remain explicit
NOT_IN_THIS_POST_SEAL_INPUT; the whole-Core runner must add their real telemetry,
not infer them from binary scores. Pricing is NOT_AUDITED without billing basis.
