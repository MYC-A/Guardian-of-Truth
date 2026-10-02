# Raw journals (assignment 2026-10-02 §3.4 publication)

Verifiable raw answer journals of the measured role/deferred comparisons,
copied byte-identically from the live results directory:

- `role_predictions.jsonl` — §8 role matrix, 174 rows / 201 model calls
  (D_V1 arms, EJ pipelines, G3 counterevidence, Gk3 seeds, B_without_A),
  every call with content/usage/cached/elapsed/seed/request_sha256.
  Source of truth: /workspace/guardian/results/modular_steps_20261002/role_pilot/role_predictions.jsonl
  sha256 becea65f56de8ec4c438fd87b2ab58b7f3e3248eaa1d8af5a220fd407ed05158
- `deferred_predictions.jsonl` — §9.6 deferred comparison, 54 rows / 78
  calls (18 complete triples of 24 at the reviewer_repair ceiling; the 6
  unmeasured goals are completed in cycle modular_all_noft_20261002 by
  deferred_completion_pilot.py, whose journal lives in
  /workspace/guardian/results/modular_steps_20261002/deferred_completion/).
  Source of truth: /workspace/guardian/results/modular_steps_20261002/deferred_pilot/predictions.jsonl
  sha256 4eb67839764e577962ff1011fcee406d934cdaa24569546b60249e849d377ebc

Receipts and summary tables do NOT replace these answers: audit of
explanations requires the raw model outputs above. Historical answers are
never regenerated; if a source file is lost it is marked irrecoverable, not
rewritten.
