# Fast follow-up: frozen service-desk run

This branch prepares one new, authored domain to test whether the existing
v3.1/v4/TQ false-positive clearances transfer. It also tests the frozen Granite
12k/24k/60k context settings and the official `function_call` criterion on
balanced tool-call cases. This is a mechanism test, **not** a hidden-test score.
No research arm is installed in `scripts/predict.py` by this run.

## Frozen inputs

- `experiments/searh_23/service_desk_v1/cases.csv`: 32 unlabeled cases, exactly
  8 in each `(gold 0/1) × (target has assistant tool call yes/no)` cell. Same
  policy across contrasts; service-desk cases, tools, IDs and actions are new.
- `expected.json` and `rubric.json`: authored labels and reasons. Keep these
  away from inference stages. Only `score` reads `expected.json`.
- `manifest.json`: input and label hashes. The runner rejects a changed CSV.

The four sets contain: future offer versus completed-action claim, prerequisite
present versus absent, correct versus wrong case/amount, early versus due audit,
justified versus unsupported refusal/transfer, and legal versus illegal tool
calls. Opportunity counts must be checked after pgjudge runs: a negative pair
that pgjudge labels 0 gives the refutation layer no chance to improve.

## Server commands

From the repository root, use the existing Python environment with the local
Granite checkpoint and set `MISTRAL_API_KEY` in the environment, or point
`GUARDIAN_MISTRAL_ENV_FILE` to the existing credentials file. Mistral is called
through its API; Granite and the structural engine run locally. No secrets are
written into the run manifest.

```bash
git fetch origin
git switch codex/fast-followup-20260924
git pull --ff-only
python experiments/searh_23/fast_followup_run.py prepare \
  --cases experiments/searh_23/service_desk_v1/cases.csv \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1
python experiments/searh_23/fast_followup_run.py local \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1 \
  --model-path /mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda
python experiments/searh_23/fast_followup_run.py pgjudge \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1
python experiments/searh_23/fast_followup_run.py refute \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1
python experiments/searh_23/fast_followup_run.py tq \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1
python experiments/searh_23/fast_followup_run.py score \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1 \
  --gold experiments/searh_23/service_desk_v1/expected.json
```

`local` and `pgjudge` append per-case records and skip completed cases on
rerun. Use a fresh directory for a fresh comparison. `refute`, `tq`, and
`score` are one-time stages. `score` seals all prediction file hashes before
opening labels and requires complete coverage by default.

## Readout and decisions

`score.json` contains per-case predictions, confusion counts split by response
shape, and paired TP gained/lost and FP removed/added. Check in this order:

1. Confirm 32/32 coverage, no `null` C1 scores, 16/16 call adapter readiness,
   and the prediction seal. Investigate any missing rows before comparing arms.
2. Compare `pgjudge -> v31/v4/v4_safe` and `v4_safe -> tq` on the same cases.
   `v4` preserves the historical catalog-closure guard; `v4_safe` removes only
   that unsupported closure inference and retains explicit required-field
   checks. Any newly lost TP blocks promotion.
3. Count pgjudge false alarms in future-offer and not-yet-due families. If there
   are none, zero TQ changes on those families is inconclusive. Inspect each
   clearance trace and entity/amount/time binding.
4. Compare `c1_12000` with 24k/60k, and with
   `c1_12000_plus_function_call`, separately on call and text cases. The
   `function_call` only covers eligible target calls; its standalone F1 is
   intentionally undefined on the full set.
5. For C1 misses on unsupported refusals or handoffs, inspect whether a
   feasible alternative has an exact policy clause, declared tool, matching
   case/amount, satisfied prerequisites and no unknown premise. Only then
   implement and test the separate action-feasibility witness. This gate avoids
   adding a generic opinion checker before evidence supports it.

No arm is promoted from this authored suite alone. A gain with zero TP loss
qualifies for one untouched contest-like validation. A zero gain with actual
base-positive opportunities argues for freezing the simpler local path.

## Local checks already run

- Generator produced all 32 cases; call parser found 16 target calls; the
  Granite tool-call adapter marked all 16 `ready`.
- `prepare` and structural-only `local --skip-model` processed 32/32 locally.
- Unit checks cover label isolation, frozen-input hash, balanced shapes,
  source-safe guard, and rejection of incomplete scoring.
- Actual Granite and Mistral inference have **not** been run on this branch yet.
