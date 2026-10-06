# RUNBOOK — universal repair (branch research/guardian-universal-repair-20261006)

## Fresh install
```bash
git clone https://github.com/MYC-A/Guardian-of-Truth.git && cd Guardian-of-Truth
git checkout research/guardian-universal-repair-20261006
python3.13 -m pip install pyarrow bm25s "pytest<9" pydantic fastapi loguru toml addict deepdiff websockets httpx tenacity litellm rich pandas
export PYTHONPATH=$PWD:$PWD/src
python -m pytest -q tests/test_universal_repair.py          # 19 defect+contrast tests
```
Line endings: `.gitattributes` pins LF for frozen trees; a CRLF checkout of other paths changes only `input_records_sha256`
(see REPOSITORY_AUDIT.md / phase0_raw_replay.json).

## Offline replay (no network, no key)
All model replies used by the reported runs are committed under `outputs/verification_v2/cache/mistral` (incl. 822 entries
exported from the former sibling worktree) and `outputs/universal_repair/cache/{mistral,judge}`. Requests whose exact key is
absent return `NOT_EXECUTED_OFFLINE` (never a verdict).
```bash
python -X utf8 -m experiments.universal_repair.run --set lb3_long --rep 1 --arm R_comb      # sets: valid46 lb_long lb2_long lb3_long ext_tau2 hold_tau2h
python -X utf8 -m experiments.universal_repair.report --mode offline --out /tmp/report.json
python -X utf8 -m experiments.universal_repair.funnel --arm R_comb --mode offline
```
To replay the live runs exactly, point `run.py` at the live cache (it is read through first) and use `--live` with
`MISTRAL_API_KEY` unset: any missing key then fails as a technical failure instead of a silent verdict.

## Live
```bash
export MISTRAL_API_KEY=...        # never commit; model ministral-14b-2512, 30 req/min → MIN_INTERVAL=2.1 s, one process at a time
python -X utf8 -m experiments.universal_repair.run --set valid46 --rep 2 --arm R_comb --live
python -X utf8 -m experiments.universal_repair.judge_causes --sets lb3_long:1 --arms V4r,R_comb
```
Budget: `MAX_CALLS=2500` new detector calls (per-process cap + ledger `outputs/universal_repair/cache/http_tries.jsonl`);
judge `--max-calls 600`. Holdout gold is frozen (`outputs/universal_repair/holdout/tau2h/`, `holdout.py freeze` refuses overwrite).

## Production use
Enable via `run_v5(row, client, flags=ARMS['R_comb'])` (`src/guardian_truth/repair/v5.py`); decision `decide(rec)`.
Default pipeline is unchanged — see FINAL_DECISION.md for which arm is recommended. Production merge is a separate review step.

## Full test suite
`python -m pytest -q tests/` → 2855 passed, 20 failed. The 20 failures are pre-existing legacy tests (vnext artifacts, telecom
recovery, service dispatch, runtime, hybrid packets, policy-table v11): the same tests fail identically on the V4 branch
(`research/guardian-proof-executor-v4-20261006` @32ede180, checked on 6 of the files: 11/11 same failures). Universal-repair tests: 21 pass.
