# Verification V4 — final decision

**Default stays `guard_adm2` (arm A).** No V4 component is adopted.

| component | dev (regression only) | external `ext_tau2` (3 reps) | decision |
|---|---|---|---|
| Combined V4 | +1…+4 cc, 0–1 FP per set | 0 cc each rep, +4–5 FP | REJECT |
| DF-only | +1…+3 cc on LB2/LB3, 0 FP | never triggered | INSUFFICIENT EVIDENCE → keep shadow |
| All-target (AT) | +1 cc on LB1/LB3, 1 FP each on LB2/LB3 | +2–4 binary TP (all cause≠), +4–5 FP; beats CTRL in 1/3 reps | no mechanism → REJECT as default |
| Structured multi-source proof (Ems) | +1 cc (LB1, LB3 r2) | no eligible compositional case; 1 cause≠ gain, FP in 2 reps | INSUFFICIENT EVIDENCE |
| V4_mechanical / V4_mech_strict | = V4 except H5n | identical to V4 | criterion §5 not met; verified stays |

## Audit (post-processing invariants §11, external runs)
* Inv. 1–4: no violations (no verified DF/Ems mismatch without a candidate; no complete-coverage AT ERROR without candidate;
  no STRUCTURED_PROOF VIOLATED removed by a single quote gate; no candidate from missing source/parse failure).
* Inv. 5 / downgrades listed for manual audit: Ems raw VIOLATED downgraded for EVIDENCE_NOT_VERIFIED / UNKNOWN_OPERATION
  (also NO_TARGET_OPERAND; ext_ret_022 r1, ext_ret_030 r3 — both NO_ERROR rows, downgrade correct); AT raw ERROR not admitted on
  ext_air_032 r1 (coverage complete, but no evidence quote verified → no candidate, as required by inv. 4; NO_ERROR row); CTRL/Ems verifier SUPPORTED downgraded on
  QUOTE_NOT_VERIFIED (ext_ret_029, ext_ret_038, ext_ret_034, ext_air_061, ext_ret_025, ext_ret_041); A reason mentions a violation
  but decision NO_ERROR/UNKNOWN (ext_ret_058/060/062, ext_air_064, ext_ret_022) — baseline behaviour, not V4.
* No post-hoc code change after commit 3. No bug requiring an amendment was found on the external set.

## Why it failed to transfer
1. Dev gains came from prose moves with stated quantities/dates (DF, Ems); tau2 agents never mix prose and calls and rarely state
   computable quantities → triggers do not fire.
2. AT accusations on correct gold writes are mostly generic policy boilerplate (confirmation/one-user rules) that the verifier
   accepts → FP cost exceeds the later-call gain.
3. Baseline variance is large (17/70 rows flip across reps), comparable to any V4 gain.

## Review process
No subagent tool was available: independent self-review passes were done instead (oracle/selection review, drop review,
metric/verdict re-check against the per-stratum reports).
