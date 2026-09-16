# Real Competition Valid — Codex Worklog

Development-data experiment only. `valid.parquet` is viewed public development data; no result in this log is a hidden-test or generalization claim.

# Official competition contract

## 2026-09-16T19:59:25+03:00 — primary-source review

- HEAD: `315bee335a467476732b47e1e7f412097222cd3b`
- Sources checked: [Guardian task page](https://dsworks.ru/champ/aij26-guardian), [competition page](https://dsworks.ru/group/aij2026), and [official 2026 rules PDF](https://gitverse.ru/api/repos/gitverse/AIJ/raw/branch/master/AIJourney2026-rules-ru.pdf).
- The task is response-level binary classification: `1` means at least one contradiction or unsupported statement/action in `response`; `0` means no contextual hallucination.
- Submission input fields are `id`, `prompt`, and `response`; public development data additionally contains `label` and `explanation`, neither of which is inference input.
- `prompt` is a marked transcript containing SYSTEM policy/instructions, user and prior assistant turns, available-tool descriptions and typed argument specifications, tool calls, and tool results. `response` contains the target assistant text and/or target tool calls.
- Official output is CSV with columns `id,label`. The rules specify `python scripts/predict.py --input <path_to_test.csv> --output <path_to_predictions.csv>` and a Docker image under 40 GB. The primary metric is response F1, with precision and recall also reported. Runtime is 30 minutes on one NVIDIA H100. At most 10 successful submissions are allowed, with three final candidates selected.
- SOURCE A (rules PDF) says hidden/test is passed as CSV to `scripts/predict.py`. SOURCE B (task data page and repository) exposes public development data as `valid.parquet`. Experiment assumption: read the repository parquet for development analysis while keeping the prediction interface representable as `id,prompt,response`; do not treat parquet-only fields as inference inputs.
- The rules do not state a RAM limit for Guardian of Truth and do not explicitly state the network policy for the first task. They explicitly block external internet for another task, not Guardian. Conservative competition assumption: external API availability at final scoring is **not established**. Live B.AI calls in this cycle are a local-development dependency, not a claim that the final Docker may call an external API. Local LLM use is not prohibited by the cited Guardian section, subject to the 30-minute/H100/<40-GB constraints and licensing rules.
- Next: inspect actual frozen execution path and public input envelope before any semantic change.

# Current repository state

## 2026-09-16T19:59:25+03:00 — frozen starting point

- Command: `git status --short --branch; git branch --show-current; git rev-parse HEAD; git log --oneline -15; git remote -v`.
- Result: branch `E2E-agent-2`, tracking `origin/E2E-agent-2`, HEAD `315bee335a467476732b47e1e7f412097222cd3b` (`FINAL FREEZE B4h-sound-v2`). Remote reference was independently verified at the same SHA.
- Worktree had one pre-existing untracked directory, `NVIDIA_API/`; it is user-owned and will not be modified or committed.
- The local `.env` is Git-ignored. Live semantic calls for this cycle are constrained to B.AI model `qwen3.8-flash` and the local `.env` key named `b_ai_api_key`; secret values are never logged or committed.
- No branch switch, reset, or new branch is required or permitted by the current task.

# Existing Guardian architecture

Pending exact trace. Initial inspection distinguishes the legacy `pipeline.Detector`/`scripts/predict.py` path from the frozen vnext E2E proof system; equivalence has not been assumed.

# Actual execution path

Pending exact file/function/config trace for historical B4h, B4h-sound-v1, and B4h-sound-v2.

# Competition-input compatibility

Pending dependency table and raw `valid.parquet` envelope audit.

# Baseline run

Pending. Production semantics will remain unchanged until all 46 rows have either completed or produced an explicitly classified blocker.

# T1 / tool-semantics audit

Pending.

# Failure decomposition

Pending.

# Fix iterations

Pending; maximum three substantial general fixes, one root cause per iteration.

# Remaining failures

Pending.

# Next architecture hypotheses

Pending until baseline, decomposition, and permitted fixes are complete.

# Final state

Pending.
