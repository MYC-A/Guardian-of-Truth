# C-ALR Reimplementation Study V1 — machine-verified result (REJECT_EARLY)

Status: **RUN_COMPLETED_SEALED_VERDICT_REJECT_EARLY** — 2026-09-14, experiment
`policy_c_alr_reimpl_v1`, branch `experiment/guardian-vnext-from-0199bf9`.

Preregistration: `docs/vnext/C_ALR_REIMPL_STUDY_V1.json` (frozen at commit
377a7856 BEFORE the first external call; freeze artifact
`outputs/vnext/policy_c_alr_reimpl_v1_freeze.json`, 142 cases, benchmark
`cases_sha256` sealed, prompts/schemas/gates digested into the freeze record).

## Result

| quantity | machine-verified value |
|---|---|
| Benchmark | recovered policy_v5, 142 cases (94 unambiguous / 48 ambiguous), gold by construction, sealed before predictions |
| H0 (conservative single-parse primary, bai/qwen3.8-flash) | **136/142 = 95.77%** behavioral accuracy |
| H0 parse validity | 142/142 compiled (141 primary + 1 via the registered one-shot repair re-ask) |
| Catalog-recoverable C-errors | **0** |
| Oracle gain from perfect local patching | **0.0 pp** |
| Stage A' STOP gate | `recoverable share 0.000 < 0.05` AND `oracle gain 0.000 < 0.04` → **STOP** |
| Verifier requests sent | **0** (per the frozen stop rule: no verifier request after REJECT_EARLY) |
| Verdict | **REJECT_EARLY** — the hybrid (C-ALR) architecture is not justified on this data |

Primary sealed artifacts: `outputs/vnext/policy_c_alr_reimpl_v1_{freeze,benchmark,
predictions,prediction_seal,stage_a,failure_audit}.json` (prediction seal
verified before gold join; `gold_joined: false` in the seal).

## What this means

1. **The premise of the hybrid architecture fails on this benchmark.** C-ALR's
   hypothesis is that the conservative primary's residual errors are LOCAL —
   reachable from φ_C by ≤2 typed catalog mutations that a span-grounded
   verifier can admit or reject. Machine verification on this study's sealed
   data: not a single one of the 6 residual H0 errors is reachable by the
   frozen mutation catalog. The local-refinement ceiling is exactly H0's
   accuracy (95.77%); a perfect verifier with infinite budget could not have
   done better with this catalog on these errors.
2. **H0 itself is strong.** 95.77% with a single parse per case (median 1
   request, 142 requests + 1 repair total) on a benchmark engineered around
   admission traps. This reimplementation is NOT numerically comparable to the
   historical user-reported V5 numbers (C 78.1% / B4 84.7%): different prompt,
   different engine reimplementation, atom-catalog-visible input contract, and
   those historical sealed artifacts are physically lost (absence-attested).
3. **The remaining 6 errors are structural, not local** (deterministic audit,
   see failure_audit.json):
   - `UNLESS_EXCEPTION_PLACED_AS_CONDITION` (2: pax3, ste4) — "unless A or B"
     misread with exceptions placed as conditions; the catalog has no
     exception↔condition relocation mutation.
   - `CONDITION_NEGATION_FLIP` (1: at1) — "before the survey begins" encoded as
     positive `event:nesting_survey_begun` instead of `!event:...`; the catalog
     has no literal-negation mutation.
   - `MODALITY_ONLY` (1: sto5) — "either … is enough to ground" read as
     PERMISSION instead of REQUIREMENT; modality flips are outside the catalog
     by design (both historical and fresh).
   - `MULTI_AXIS` (2: rp2, ts4) — provenance/kind misbinding and an
     AND_NOT_EACH + clause-shape combination; multi-axis diffs exceed the ≤2
     local-mutation rule.

## What was NOT done (and why)

- No H1/H2 verifier request was sent: the frozen stop rule
  (`C_ALR_REIMPL_STUDY_V1.json` §stage_a_prime_stop_gate.on_stop) forbids it
  after REJECT_EARLY. No McNemar / correction-precision comparison exists for
  this study because there is nothing to compare — the hybrid arm was never
  allowed to run. That is the registered outcome, not an omission.
- No manual rescoring, no post-hoc prompt or mutation-rule changes, no gold
  access by any model input. Predictions were sealed before gold join.

## Consequences (per the historical protocol's own stop semantics)

- Arm C-class conservative parsing remains the Policy frontend baseline.
- A future cycle that wants to move past 95.77% on this error profile must
  target the THREE structural error classes above (exception/condition
  binding, literal negation, permission/obligation modality) — these require
  representation-level changes (or catalog extensions registered in a NEW
  preregistration), not local mutation admission.
- Any claim that "the hybrid beats the conservative parser" is now
  CONTRADICTED for this benchmark/model combination until a new registered
  experiment with an extended catalog shows otherwise.

## Reproduction

```
git checkout <freeze commit 377a7856>
PYTHONPATH=src python3 scripts/evaluate_vnext_c_alr_reimpl.py freeze
PYTHONPATH=src python3 scripts/evaluate_vnext_c_alr_reimpl.py run-h0 --env-file .env
PYTHONPATH=src python3 scripts/evaluate_vnext_c_alr_reimpl.py stage-a
PYTHONPATH=src:scripts python3 scripts/audit_c_alr_reimpl_failures.py
```
Per-request telemetry (142 + 1 repair requests, latencies, tokens) is persisted
under `outputs/vnext/policy_c_alr_reimpl_v1_h0_*/` with pre-request payload
hashes; every request is byte-replayable.
