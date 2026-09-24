# Fast follow-up: frozen service-desk run

This branch prepares one new, authored domain to test whether the existing
v3.1/v4/TQ false-positive clearances transfer. It also tests the frozen Granite
12k/24k/60k context settings and the official `function_call` criterion on
balanced tool-call cases. Separate arms test extractive feasibility proposals,
completed-action claims, and the pinned historical E2E implementation on the
same inputs. This is a mechanism test, **not** a hidden-test score.
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

`service_desk_v1_renamed` is a second, label-preserving input frozen before the
first server readout. It changes all case/device IDs and all tool names while
keeping policy meaning, trajectories, response shape, and labels paired 1:1.
Run it in a fresh directory using the same stages and its own `expected.json`
and `rubric.json`. Compare per-case flips under renaming before interpreting
any apparent gain. This checks lexical stability, not transfer to a new domain.

## Server commands

From the repository root, use the existing Python environment with the local
Granite checkpoint and set `MISTRAL_API_KEY` in the environment. The existing
TQ/pgjudge loaders can also read `GUARDIAN_MISTRAL_ENV_FILE`; the historical
E2E wrapper requires the key in the environment. Mistral is called through its
API; Granite and the structural engine run locally. No secrets are written into
the run manifest.

```bash
git fetch origin
git fetch origin competition-real-valid-codex
git switch codex/fast-followup-20260924
git pull --ff-only
python experiments/searh_23/fast_followup_run.py prepare \
  --cases experiments/searh_23/service_desk_v1/cases.csv \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1
python experiments/searh_23/fast_followup_run.py witness \
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
python experiments/searh_23/fast_followup_run.py feasibility \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1
python experiments/searh_23/fast_followup_run.py completion \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1
python experiments/searh_23/fast_followup_e2e.py \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1 --mode both
python experiments/searh_23/fast_followup_run.py score \
  --run-dir outputs/searh_23/fast_followup/service_desk_v1_run1 \
  --gold experiments/searh_23/service_desk_v1/expected.json \
  --rubric experiments/searh_23/service_desk_v1/rubric.json
```

`local`, `pgjudge`, `feasibility`, `completion`, and E2E append per-case records
and skip completed cases on rerun. Use a fresh directory for a fresh comparison.
`witness`, `refute`, `tq`, and `score` are one-time stages. `score` seals all
present prediction file hashes before opening labels and requires complete
coverage by default. If an optional stage is omitted, its arm is absent; if
its output file exists but is incomplete, scoring stops. Do not score before
all selected stages finish.

The E2E script reads only the exact source files at commit `300dc2e` from Git
and checks their digest on resume. It runs R1 and R2 against the *same* CSV;
its Mistral cache is separate from pgjudge/TQ. A runtime error remains an
error and cannot silently become a negative prediction. This historical E2E
arm was previously evaluated on public46, not on this suite.

`witnesses.json` inventories exact argument sources and prior results. It does
not issue policy verdicts. `feasibility.jsonl` is an extractive Mistral proposal
for refusals/handoffs; `completion.jsonl` checks an atomic past-action claim
against matching successful tool results. Their ORs with C1 are experimental
positive-only arms. Exact citations and entity joins are checked in code, but
the model's semantic mapping and completeness of policy prerequisites remain
open error sources. Inspect `UNKNOWN`, `issues`, and the cited premises before
trusting a gain.

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
5. Compare `c1_12000` with `c1_12000_and_pgjudge`,
   `c1_12000_and_v4_safe`, and `c1_12000_and_tq`. This tests the refutation
   stack as a veto on C1 alarms. Count removed FP and lost TP separately;
   public46's apparent 2-FP win is in-sample. This arm requires the Mistral
   API upstream.
6. For C1 misses on unsupported refusals or handoffs, inspect whether a
   feasible alternative has an exact policy clause, declared tool, matching
   case/amount, satisfied prerequisites and no unknown premise. Only then
   consider the `feasibility_proposal` arm. It is already implemented for this
   run and must earn its marginal TP without adding FP. Compare the
   `completion_proposal` arm separately on false completion versus future-offer
   cases; a source quote alone does not validate tense or action mapping.
7. Compare E2E R1/R2 to C1 on the same cases. Inspect any marginal TP and the
   corresponding `core_status`, fallback and missing-evidence fields. An OR
   gain that is reproduced by response-call shape is not a useful new signal.

No arm is promoted from this authored suite alone. A gain with zero TP loss
qualifies for one untouched contest-like validation. A zero gain with actual
base-positive opportunities argues for freezing the simpler local path.

## Local checks already run

- Generator produced all 32 cases; call parser found 16 target calls; the
  Granite tool-call adapter marked all 16 `ready`.
- `prepare` and structural-only `local --skip-model` processed 32/32 locally.
- Unit checks cover label isolation, frozen-input hash, balanced shapes,
  source-safe guard, and rejection of incomplete scoring.
- The first server execution started after this freeze; its quote-anchoring
  repair and lack of a scored result are recorded in `RESULTS.md` section 13.
