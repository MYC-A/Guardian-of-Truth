# Runbook: integrated v1

## Install (fresh, no PYTHONPATH)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install .                    # installs guardian_truth (+pydantic) and the guardian-review entry point
guardian-review input.jsonl --no-model                         # code-only: guard + packet + relations, 0 HTTP
export MISTRAL_API_KEY=...                                      # keys only from the environment
guardian-review input.jsonl --profile integrated --provider mistral --cache-dir .guardian_cache --max-calls 100
guardian-review input.jsonl --profile baseline --provider ollama --model gemma4:31b   # needs OLLAMA_API_KEY
guardian-review input.jsonl --offline --cache-dir .guardian_cache                    # zero-HTTP replay; a cache miss fails loudly
```
- Input: JSON or JSONL objects with `prompt` and `response`. Other keys are ignored.
- Output: one JSON line per input, or `--full` for the whole trace (steps, gaps, relations, guard).
- `--output` never overwrites an existing file.
- Verified on Linux with Python 3.13 in a fresh venv. Windows is not tested here, but the CRLF input test passes.

## Reproduce this phase
```bash
pip install pyarrow pandas "pytest<9"
export PYTHONPATH=$PWD:$PWD/src             # only needed for experiments/ and scripts/
python scripts/integrated_cache46.py --output outputs/integrated_v1/phase0_cache46/<new>.json   # 0 HTTP
python -m experiments.integrated_v1.run --plan
python -m experiments.integrated_v1.run --phase valid46 --provider mistral --profile baseline --rep 1 --workers 4
python -m experiments.integrated_v1.run --phase valid46 --provider mistral --profile integrated --rep 1 --workers 4
python -m experiments.integrated_v1.score judge
python -m experiments.integrated_v1.score report --tag <new-tag>
```
- **Resume:** re-run the same command. Completed rows are skipped, cached replies are reused, and budget counters are rebuilt from `outputs/integrated_v1/cache/<provider>/attempts.jsonl`.
- A transport failure is re-sent at most once (`retry_failed=1`).
- **Gemma completion after quota renewal:**
  1. Delete the 30 limited lines from `phase_valid46/ollama/integrated/rep1.jsonl`. Delete lines only; the cache and ledger stay.
  2. Re-run `--provider ollama --profile integrated --rep 1`.
  3. Rename `limited_rep2.jsonl` away and run rep 2.

## Tests
```bash
python -m pytest -q tests/integrated_v1            # 44 tests: repairs + public API contracts
python -m pytest -q tests                          # full suite (see breakdown below)
```

## Full-suite breakdown
The table compares the base checkout `5c31da6e` with this branch.

| Checkout | total (passed+failed+errors) | passed | failed | collection errors |
|---|---|---|---|---|
| base `5c31da6e` | 2731 | 2716 | 11 | 4 |
| this branch | 2773 | 2750 | 19 | 4 |

- **Collection errors (pre-existing, identical on both checkouts):** `test_fast_followup`, `test_followup_witnesses`, `test_hybrid_provider_routing`, `test_service_dispatch`. These are optional/historical service imports.
- **The 11 base failures** are unchanged.
- **The 8 new failures** are all expected contract changes from D1: error receipts are now separate events, which shifts historical event inventories.
  - `telecom_causal_recovery/test_recovery` ×4
  - `test_hybrid_packets::test_conflicts_use_prediction_refs_not_fixed_business_ids` (hard-coded `h30`)
  - `test_policy_table_v11_consent_pair_probe::test_cohort…` (preparation witness order)
  - `test_policy_table_v11_measure` (mutant rematerialization hash)
  - `test_real_bound_contract_audit` (41→40 action results)

  Historical replays must use their original commits.
- **New tests:** 44 in `tests/integrated_v1`, all passing.

## Cost profile (this phase)
Per-call latency, tokens and controller share are in RESULTS.md. Memory is that of the CPU-only Python process, with no local model. Model calls are remote.
