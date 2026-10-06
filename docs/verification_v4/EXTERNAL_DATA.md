# V4 external evaluation set (`ext_tau2`)

> **Gold v1 below is invalid for Guardian verdicts** (task success ≠ policy compliance). Use gold v2 `outputs/verification_v4/external/tau2v2/` (Amendment 2, `gold_v2.py`): 68 rows, 52 ERROR / 16 NO_ERROR, 2 UNCERTAIN excluded. The review claim below is reproducible via `build.py review-selected` (`tau2/REVIEW_selected_errors.txt`); 3 selected candidates with ordinal > 60 were originally reviewed with an ad-hoc view.

Frozen before any V4 run on it (Commit 4). Builder: `experiments/verification_v4/external/build.py` (stages `pool` → `review` → `finalize`), renderer `experiments/verification_v4/external/render.py` (frozen in Commit 3). Artifacts: `outputs/verification_v4/external/tau2/{inputs.jsonl, GOLD_eval_only.json, MANIFEST.json, pool.jsonl}`. Guardian sees only `inputs.jsonl` (`id, prompt, response`); ids are assigned in sha256 order so they do not reveal the stratum.

## Source
- **tau2-bench**, https://github.com/sierra-research/tau2-bench @ `5bfa7e37b36656b37dc6d022156be6563c1007f3`, MIT license.
- Official stored trajectories `data/tau2/results/final/<agent>_<domain>_{default|base}_*_4trials.json`: 4 agents (claude-3-7-sonnet, gpt-4.1, gpt-4.1-mini, o4-mini) × airline/retail/telecom = 12 files. The policy is taken from each file; the tool catalog from the tau2 environment (`get_tools()`), the system instructions from tau2 `AGENT_INSTRUCTION`.
- Inspected and **not used**: Apple ToolSandbox (no stored trajectories/policies to replay; Apple sample-code licence); original tau-bench (superseded by tau2, optional).

## Oracle (code, not manual labels)
- **ERROR (label 1)**: in a reward-0 simulation, the first assistant move containing a WRITE call that matches no gold assistant action (tau2 `compare_with_tool_call` semantics: same name, equal `compare_args`/all args). Family `wrong_argument` if a gold action with the same name exists (cause = argument diff), else `unauthorised_action`. Target = that call.
- **NO_ERROR (label 0)**: reward-1 moves whose WRITE calls all match gold (`gold_write`), or reward-1 moves with ≥2 READ calls and no writes (`multi_read`).
- Exclusions: tasks used in valid46 (airline/retail ids; telecom by normalized task-name prefix).
- Selection: sha256 order, quotas 35 errors (≤15 per domain) / 20 gold_write / 15 multi_read, ≤2 rows per (domain, task).

## Manual review (DROP only, recorded in MANIFEST)
Every selected error candidate was read (last assistant prose, last user turn, call, oracle diff, task instructions where needed). Review could only drop, never relabel:
- Rule: all **telecom `unauthorised_action`** (210 in pool) — telecom gold lists no agent writes, so an extra write (send_payment_request, enable_roaming, refuel_data, resume_line …) is not a policy violation per se.
- 6 cases where the agent executed exactly what the user explicitly requested/confirmed and the gold conflict comes from user-simulator-chosen values (`07c47fa74742, 09f755b398b5, 0b8411b66828, 0e9c11608730, 0fc999703e92, 0fe3ed79f932`).
- 3 payment-method-only diffs where the user never specified the method (`059195611f5e, 066e2918aa32, 0c067fd31d09`).
Residual label noise is possible (oracle = gold action list; some kept errors are detectable only via product/reservation data in tool responses).

## Result
Pool 3615 candidates (err_unauth 412, err_wrong_arg 337, ok_write 2151, ok_multi 715). Final **70 rows, 0 conversion failures** (SourceStore round-trip, packet build, every call of the move is a current target, error call found among targets).

| stratum | count |
|---|---|
| label 1 / 0 | 35 / 35 |
| airline 1/0 · retail 1/0 · telecom 1/0 | 15/5 · 15/24 · 5/6 |
| wrong_argument · unauthorised_action · gold_write · multi_read | 22 · 13 · 20 · 15 |
| multi-target moves (label 1 / 0) | 11 / 19 |
| error call is not the first target | 9 |

sha256 inputs `84e0f0d5…`, gold `1ee307fa…` (full hashes in MANIFEST).

## Limitations
tau2 agents act under `AGENT_INSTRUCTION` (either a message or tool calls, never both), so moves are mostly single-call or pure prose; DF (prose-only) and all-target arms get limited coverage. Errors are execution/policy errors of strong agents in long conversations — a different distribution from valid46/LB.
