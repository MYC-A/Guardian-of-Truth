# Research worklog — 2026-09-19

## 07:43–07:50 UTC: preserve and inventory

- Original worktree: `semantic-pipeline-v1` `0d8d804`, no tracked edits; pre-existing untracked manual and agent config preserved. `git ls-remote --heads origin` confirmed nine branches. `core-engine-bakeoff-v1` is a commit lineage under FullArch, not an advertised remote branch.
- Fetched FullArch without checking out the original worktree. Created isolated local `A:\GIS_Загрузки\Guardian Offline Research 20260919` branch `research/offline-20260919` at `923bb445`. Verified 191 GB free on A: before creation. No reset/clean/pull.
- Researcher fully read the three original `manual/` files and the external v2 handoff, created `MANUAL_INDEX.md`. The documents were copied into the isolated worktree after a presence-only secret scan (no private key/token value matches).
- Tester established SSH access and found prepared model environments/caches but no existing Guardian repository or experiment outputs at the documented paths. Created isolated remote clone `/mnt/data/guardian/Guardian-of-Truth-Offline-20260919` at `923bb445`; no existing env/cache/process was altered.
- Official 2026 PDF fetched and parsed; SHA-256 `9462490004b977e6d99a157c02effdb577b767dcf90a69e7765b78b8e8b5e3df`; task-one CLI, H100, 30 min, <40 GB confirmed. Task page returned HTTP 403. Internet blocked statement is task-two-specific.

## 07:50 UTC: executable offline baseline

Hypothesis: current `scripts/predict.py` already accepts unseen CSV offline and offers a measurable exact-check baseline. Stop rule: stop after one full viewed-dev pass and one fresh three-row smoke; do not tune on those labels.

- Command: `PYTHONPATH=src python scripts/predict.py --input valid.parquet --output outputs/research_offline_20260919/baseline_dev46.csv --audit outputs/research_offline_20260919/baseline_dev46_audit.jsonl --run-report outputs/research_offline_20260919/baseline_dev46_runtime.json --backend none`.
- Commit `923bb445`; data SHA-256 `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`; model none; result TP12 FP0 FN11 TN23, F1=.685714, 34 fallbacks, 0.395 s for 46 on local Ryzen 7 5825U. Viewed-dev diagnostic only.
- Fresh unseen, unlabeled three-row CSV passed the official entrypoint and produced columns `id,label`, 0/0/0. No gold was present in this inference input. `tests/test_cli.py tests/test_runtime.py`: 17 passed in 1.08 s.
- Server fresh three-row `--backend none` smoke passed with `PYTHONPATH=src` in 0.00976 s and no GPU allocation. Bare source checkout without install initially raised `ModuleNotFoundError`; packaging in Docker uses `pip install .[data]`, which still requires a separate cold verification.

## Next bounded actions

1. Reproduce the same 46-row offline baseline on the isolated server, compare hashes and counts; do not infer hidden F1.
2. Build a standalone local Granite Guardian probe for `function_call` and `groundedness` with explicit context budget and raw score trace. No production routing until 3 fresh smoke and independent balanced data demonstrate TP gain without unacceptable FP.
3. Recover FullArch N5's two false-positive source-to-verdict traces from tracked frozen Phi if Clingo is already available; stop if dependencies would require broad environment changes.
4. Perform isolated `pip install .` and Docker cold-start when tooling permits. Do not touch frozen branches or existing outputs.


## 07:52 UTC: remote baseline replication

Tester reran the same `--backend none` viewed-dev baseline in the isolated remote clone at `923bb445`, `PYTHONPATH=src`, no API/GPU/install. Input SHA-256 matched local: `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`. Predictions SHA-256: `07dff1f61d1cde4ae2aa93d7bf51f42b92e792fedcaf62b12bef9f1e5cb8d790`. Exact ID join produced TP12 FP0 FN11 TN23, F1=.685714; pipeline 0.650 s, shell wall 1.153 s, GPU 0 MiB. Artifacts: `/mnt/data/guardian/Guardian-of-Truth-Offline-20260919/outputs/research_offline_20260919/`. Docker CLI is absent on the server. The initial bare checkout command failed on missing import; setting PYTHONPATH succeeded. A project install remains untested.

## 07:55 UTC: bounded historical FullArch N5 replay started

Hypothesis: the tracked frozen Phi plus Clingo 5.8.2 can recover the two N5 false-positive case traces missing from ignored outputs, exposing the first source-to-verdict loss. This is a historical replication only, not a new offline model. Stop rule: one smoke case then one 46-row pass; stop on solver failure or >10 minutes. Clingo was installed only into a temporary local target, not the project or server venv. One-case smoke succeeded; full output namespace is `outputs/research_fullarch_replay_20260919/full/`, with stdout/stderr redirected. Command: `PYTHONPATH=<temp-clingo>;src python experiments/full_architecture_v1/benchmarks/real46.py --arms N5 --output-dir outputs/research_fullarch_replay_20260919/full`. Dataset SHA is the public46 SHA above; Phi is the tracked frozen Mistral artifact.

## 07:59 UTC: FullArch N5 historical replay and root cause

The bounded 46-row replay completed once on local CPU with Clingo 5.8.2. TP4 FP2 FN19 TN21, F1=.2759, matching `0c2bda7`. Predictions SHA-256 `3f63cc791c4bbc236e2aab2b0df2e05a43935cba382b3cb9b5a2c20286769fea`; sum per-case runtime 102.77 s, mean 2.23 s. The two FP are `banking_knowledge__task_063::t8` and `banking_knowledge__task_081::t35`. Reconstructed certificates show `unit:0002:mistral:2` is the sole false obligation in all 64 interpretations for each case. RuleIR had a request-count condition and KB-guidance exception, but compiler emitted unconditional `FORBID transfer_to_human_agents` after both failed lowering. Source-to-verdict details in `FAILURE_ANALYSIS.md`. This is a formal-lowering soundness bug; code correction is underway, and this replay remains a historical frozen-Phi result.

## 08:00 UTC: preregistered local model probes

Granite Guardian 3.3 8B official card confirms Apache-2.0 and separate `function_call` and `groundedness` criteria. Hugging Face revision `b3421eda4ba6fc9f9a71121d7e62de08827469a4` has 16,341,771,384 bytes of safetensors, so one model fits the server's free disk; 15.22 GiB weights leave limited A10 VRAM for context. Existing venv already has torch 2.9.1+cu128, transformers 5.16.1, vLLM 0.15.1. A single durable CPU/network download is running in its own namespace, PID 26862; no GPU work during transfer. Stop on auth/network/disk failure or OOM at first one-case model load; no repeated large download. The experimental runner is isolated from `scripts/predict.py` and stores only probabilistic scores.

Before model inference, 32 newly authored synthetic pairs were frozen under `benchmarks/offline_guardian_v1/`: 16 function-call and 16 groundedness rows, 16 positive/16 negative total. Inference inputs contain no labels; `gold.csv` is separate. SHA-256: tool input `cb567c6a14d2265d7f93155cb1c60beed332679ffa43f73d8e47ae5815e91305`, claim input `835d5ac9fe3beabb86991af250ddda26a8afb880c0cc688a7886a9d56b26efa5`, gold `0ec45efee2b9764f7d21eab3029eb76c2f36f9959040ae90c3c4d6babfe2383b`. This is an independent-of-public46 *synthetic* diagnostic set, not hidden contest validation. Stop model integration if the relevant criterion cannot distinguish valid/invalid pairs or adds substantial FP; public46 is for later viewed-dev error audit only.

While Granite transfers, a separate cached NLI DeBERTa-base claim probe will run only on the 16 claim rows, after 1–3 smoke. It is a low-cost entailment/contradiction channel, not a policy/tool detector or proof. No calibration threshold will be fit on public46.

## 08:05 UTC: sound lowering fix and repeat replay

Commit `36d4b58` changes only the RuleIR→Neutral compiler and adds six focused regressions. An obligation is no longer emitted if any condition or exception leaf cannot be represented; explicit unresolved content and unsupported temporal rules also abstain; supported BEFORE/UNTIL/AFTER fields are preserved; capped world enumeration cannot certify an incomplete product. Targeted compiler tests: 6 passed. CLI/runtime tests: 17 passed.

The same N5 replay over the same tracked Phi completed once: TP3 FP0 FN20 TN23, F1=.2308, unresolved rate .6522. Prediction SHA-256 `5f3e6f9c940b6614211efe7475b920017e81f90a4712ae2c839c3996ff4b958b`; sum per-case time 13.18 s, mean .287 s. Both former FP and one former TP (`airline__23::t10`) became `UNRESOLVED`; no new positive prediction appeared. This preserves proof soundness at a measured recall cost and does not make frozen Phi an offline final frontend.

Full repository tests after the fix: 1626 passed, 9 failed in 12.86 s. The nine failures are the same historical artifact/seal hash failures documented before this work; the new compiler regressions and CLI tests pass. No failure references the changed compiler.

## 08:06 UTC: cached NLI inference

The prepared server's cached `cross-encoder/nli-deberta-v3-base` snapshot `6c749ce3425cd33b46d187e45b92bbf96ee12ec7` passed import smoke, a two-pair smoke, then all 16 frozen claim rows offline. Model safetensors SHA-256 `d8148c6d49e0a7925134294c56326c71fe0ab1dc390e37355e00c7efbb488afa`; label map is 0 contradiction, 1 entailment, 2 neutral. It produced 8 entailment and 8 contradiction labels; summed model latency 945.739 ms, mean 59.109 ms, max 303.404 ms. Gold was not present on the server. Exact post-inference scoring is pending retrieval of `records.jsonl`; the SSH endpoint began refusing connections immediately after the run, so no accuracy claim is made yet.

## 08:09 UTC: package install smoke

Created an isolated local venv under an ignored research output, installed `guardian-truth` 0.2.0 with `pip install ".[data]"`, imported pandas 3.0.2 and pyarrow 25.0.1, and ran the official `scripts/predict.py` entrypoint over the fresh three-row CSV. Output was valid `id,label` and the run completed with three explicit fallback decisions. This verifies package metadata and the Python entrypoint. It does not verify the Dockerfile, base-image availability, container size, GPU model packaging or cold-start budget because neither local nor server environment exposes a Docker CLI.
