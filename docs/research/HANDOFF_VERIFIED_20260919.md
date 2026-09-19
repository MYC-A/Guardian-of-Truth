# Verified handoff — 2026-09-19

## Repository and server snapshot

Inventory at 2026-09-19 07:43–07:50 UTC. The user's original worktree is `semantic-pipeline-v1` at `0d8d804d3f78a008fdfa1cc9e8db5dd1ee3ebdca`, with pre-existing untracked `.codex/`, `AGENTS.md`, and `manual/`. No tracked edits were present there. This research worktree is `research/offline-20260919` at `923bb445ab29399cd5e58a19a55941c1fdb9f6af`, based on the published FullArch tip. `git ls-remote --heads origin` showed the following nine branches; `core-engine-bakeoff-v1` was not a remote branch. The listed merge base is with FullArch.

| Remote branch | Tip SHA | Merge base with FullArch | Code / committed artifacts | Tests in this audit |
|---|---|---|---|---|
| `main` | `afb7906c3a32` | `afb7906c3a32` | Legacy detector, no tracked outputs | Not run on that tip |
| `experiment/guardian-vnext-from-0199bf9` | `8b0d13c11475` | `8b0d13c11475` | vNext code and outputs | Not run on that tip |
| `E2E-agent-1` | `d790a23bc741` | `8b0d13c11475` | E2E code and outputs | Not run on that tip |
| `E2E-agent-2` | `315bee335a46` | `315bee335a46` | Frozen B4h code and outputs | Not run on that tip |
| `competition-real-input-audit` | `67e81c7488d1` | `315bee335a46` | Competition input adapter and outputs | Not run on that tip |
| `competition-real-valid-codex` | `300dc2edd20e` | `315bee335a46` | FN audit and completion witness fix | Not run on that tip |
| `codex-update-run` | `869a93a9417c` | `869a93a9417c` | Real-valid run and closure fix ancestors | Not run on that tip |
| `semantic-pipeline-v1` | `0d8d804d3f78` | `869a93a9417c` | BGE/NuExtract/NLI, Mistral backend; separate line | Not run on that tip |
| `full-architecture-v1` | `923bb445ab29` | `923bb445ab29` | Clingo, formal compiler, certificates, benchmark adapters; no tracked FullArch run outputs | CLI tests: 17 PASS; FullArch tests not yet run |

FullArch contains `bf972b0` (neutral-input bake-off) and `4e6d200` (a *different* semantic pipeline experiment). The local `semantic-pipeline-v1` is not an ancestor of FullArch. No local or remote `outputs/full_architecture_v1/` files were found in this audit; Phase F/G/H numbers from the handoff remain LOG_ONLY until source artifacts are recovered. The Git-tracked neutral bake-off JSON exists in `outputs/core_engine_bakeoff_v1/`.

SSH alias `guardian-modelscope` works. The prepared server has one A10 with 22.7 GiB available VRAM, about 27 GiB available RAM and about 300 GB free root disk. No user GPU job was present. The formerly documented repository path was absent, while prepared venvs and cached BGE-M3, BGE reranker, NLI DeBERTa, GLiNER2.5 and NuExtract3 weights were present. A new isolated clone now exists at `/mnt/data/guardian/Guardian-of-Truth-Offline-20260919`, HEAD `923bb445`, preserving those environments and caches. Server project outputs were initially absent. Fresh three-row `--backend none` smoke succeeded in its own output directory.

## Metric provenance and limits

The tracked `valid.parquet` SHA-256 is `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba` (46 viewed-development rows; 23 positive, 23 negative). None of these scores estimates hidden performance.

| Result | Commit / model / config | Data and primary artifact | Reproduction status |
|---|---|---|---|
| Offline legacy CLI: TP12 FP0 FN11 TN23 F1=.685714 | `923bb445`; no model; `--backend none`, default checks, unknown→0 | Viewed `valid.parquet`; `outputs/research_offline_20260919/baseline_dev46.csv` and runtime JSON | **Reproduced locally** on 2026-09-19; 0.395 s for 46 rows (warm Python process), 34 fallbacks |
| Corrected closure-off C3: TP3 FP0 FN20 TN23 F1=.230769 | `4639b46`; B4h core, historical LLM witnesses; catalog/object closure OFF | Same public46; `outputs/vnext/hidden_assumptions_audit/closure_ablation.json` and commit message | Witness-level reconstruction, **not fresh live LLM replay** |
| Pre-correction fix2: TP10 FP0 F1=.606 | Prior `codex-update-run` fix2; historical LLM witnesses; unsupported closure assumptions | Same public46; `outputs/vnext/real_valid/metrics__fix2_final.json` | Rejected as formal-soundness evidence |
| FullArch N0/N5: TP3 FP0 / TP4 FP2 | `0c2bda7`; frozen Mistral-derived `phi.jsonl`; N5 Clingo + certificates | Same public46; `0c2bda7` commit message, tracked Phi | Per-case historical replay reproduced TP4 FP2 at `923bb445`; see `outputs/research_fullarch_replay_20260919/full/` and `FAILURE_ANALYSIS.md` |
| FullArch N5 after sound lowering | `36d4b58`; same frozen Phi and Clingo 5.8.2 | Same public46; corrected compiler and `outputs/research_fullarch_replay_20260919/soundness_fix/` | **Reproduced**: TP3 FP0 FN20 TN23 F1=.230769; both former FP abstain, one former TP also abstains |
| Neutral core bake-off: incumbent 27/43; Clingo/s(CASP)/Drools 43/43 | `bf972b0`; already formalized neutral inputs | `outputs/core_engine_bakeoff_v1/synthetic_results.json` | Tracked JSON present; **not NL contest F1** |
| Semantic experiment A8: TP1 FP0 FN22 TN23 F1=.0833 | `4e6d200`; frozen Mistral cache + local frontend | Same public46; `outputs/vnext/semantic_pipeline_v1/final_summary.json` | Historical cached E2E; not a standalone offline pipeline |
| SafePyramid 466 TP5 FP43; FOLIO 27%/45%; ProofWriter 61%/66% | FullArch Phase F/G/H; adapter-specific data/model/config not recovered | User-provided session log; no `outputs/full_architecture_v1/` here | **LOG_ONLY / NOT REPRODUCED**, incomparable to contest F1 |
| E2E 144 F1=.834; main V7 F1=.7556 | Distinct datasets/configurations in older reports | Historical reports; hashes/configs not yet independently checked in this audit | Historical only; never merge into one ranking |

`scripts/predict.py` currently dispatches to `guardian_truth.cli` and the legacy `Detector`, including on FullArch. It does not call the FullArch `pipeline.py` or the newer semantic pipeline. The default `--backend none` is a genuine offline, unseen-input-capable baseline, but it has no semantic model and made 11 false negatives on the viewed 46.

The [official 2026 rules PDF](https://gitverse.ru/api/repos/gitverse/AIJ/raw/branch/master/AIJourney2026-rules-ru.pdf) was fetched 2026-09-19 (SHA-256 `9462490004b977e6d99a157c02effdb577b767dcf90a69e7765b78b8e8b5e3df`). For task one it specifies `id,prompt,response` → `id,label`, `pip install .`, `python scripts/predict.py --input ... --output ...`, 30 minutes, strictly below 40 GB, and **H100**. The task page could not be fetched (HTTP 403 locally); the earlier page report says A100, so resource planning stays conservative. The PDF explicitly blocks internet during scoring for task two; it does not state that task one has internet. Offline packaging remains the safe requirement.

## Resume

Local:
```powershell
cd 'A:\GIS_Загрузки\Guardian Offline Research 20260919'
$env:PYTHONPATH='src'
python scripts/predict.py --input valid.parquet --output outputs/research_offline_20260919/baseline_dev46.csv --backend none
```

Server checkout: `/mnt/data/guardian/Guardian-of-Truth-Offline-20260919`; use existing venv from `manual/connect_server.md`, with `PYTHONPATH=src` until the project is installed in an isolated environment. Do not overwrite historical outputs or run Mistral to recreate frozen Phi.
