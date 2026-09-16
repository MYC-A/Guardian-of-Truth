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
- No branch switch, reset, or new branch was needed for the frozen-state audit. The user later explicitly allowed branch switching; the work remains on `E2E-agent-2` because switching has no current evidentiary value.

# Existing Guardian architecture

## 2026-09-16T20:03:10+03:00 — legacy/E2E separation

- `scripts/predict.py` is only a thin import of `guardian_truth.cli.main`. That CLI constructs `runtime.detector_from_args(...)`, which returns the legacy `pipeline.Detector`; it never imports `GuardianE2EV1` and is not B4h-sound-v2.
- The legacy CLI successfully read all 46 parquet rows with `--backend none`, proving the generic file/marker transport works, but these predictions are **not** a B4h baseline and are retained only as an integration diagnostic in the OS temp directory.
- B4h-sound-v2 is the vnext E2E proof system frozen at `315bee3`: historical H0 policy frontend plus Conservative Goal, B3 semantic flags, claim adapter, exact world composition, solver, certificate creation, and independent certificate checking.
- B4h historical runner: `scripts/evaluate_vnext_e2e_cycle3.py`, arm map `"B4h": (("h0_hist",), "B3")`, instantiated as `E2EArmConfig("B4h", ("h0_hist",), ("conservative",))` with `SEMANTICS_ARMS["B3"]`.
- B4h-sound-v1 is B4h plus SND-01..SND-10 changes frozen through `5e4bc39`/`8c91701`; B4h-sound-v2 adds SND-11 root-scope flat-row abstention in `world_integration_v1.py`, with the final manifest at `315bee3`. There is no separate arm name: both soundness revisions run the B4h configuration against the revised proof semantics.

# Actual execution path

`scripts/evaluate_vnext_e2e_cycle3.py:run_arm` → `GuardianE2EV1.analyze_e2e_v1` in `core_v1.py`:

1. `source_adapter_v1.build_source` composes and normalizes an `E2ECaseInput` into ledger events and separate TEXT/ACTION projections.
2. `tools.evaluate_t1` consumes version/hash-bound trusted contracts; absent T1 may invoke untrusted `tools.propose_t2` for observed call/result pairs.
3. `claim_adapter_v1.build_claims` performs LLM-backed claim extraction/typing from target response text.
4. `policy_historical_v1.historical_readings` runs byte-frozen historical H0 and maps it into the shared compiled-rule space.
5. `goal_conservative_v1.parse_conservative` extracts source-quoted goal frames from only `case.user_request`.
6. `policy_lowering_v1.lower_reading`, `goal_lowering_v1.lower_goal_contract`, and `grounding.bind_evaluation_hypothesis` bind rules/goals to ledger actions.
7. `world_integration_v1.build_worlds` builds the exact Cartesian material world set; `solve_e2e` produces `CoreStatus` under B3/B4h-sound-v2 semantics.
8. `certificate_context_v1.make_e2e_certificate` and `check_e2e_certificate` produce/check certificates for definitive results.
9. `adapters.adapt` preserves the core status. In `COMPETITION` mode, PROVED_ERROR→1, PROVED_NO_ERROR→0, INCONSISTENT→1 fallback, UNRESOLVED→0 fallback; audit artifacts retain the four-way status and fallback flag.

LLM/cache trace: historical H0, Conservative Goal, Claims, T2 proposals, and operational binding all call the injected semantic backend. The old runner replays persisted dev/holdout caches and uses live B.AI only on misses; unseen raw public cases have no corresponding frozen cache entries.

# Competition-input compatibility

## 2026-09-16T20:03:10+03:00 — public data and dependency audit

- `valid.parquet` is byte-identical to the blob at frozen commit `315bee3`.
- Rows: 46. Columns: `id:str`, `prompt:str`, `response:str`, `label:int64`, `explanation:str`. Labels are balanced: 23 zero / 23 one.
- Prompt characters: min 13,634; median 30,498.5; mean 42,614.26; p95 121,157.75; max 233,104. Response characters: min 51; median 427.5; mean 518.52; p95 1,223.25; max 2,339.
- All 46 prompts parse to exactly one SYSTEM block and a complete `[AVAILABLE TOOLS]` catalog. Per-domain catalogs contain 13–17 tools; all argument specs are understood by the existing deterministic parser. Tool descriptions and typed/required/enum/nested argument declarations are present; these are textual schema specifications rather than native JSON Schema objects.
- Parsed prompt totals: 46 SYSTEM texts, 263 USER texts, 230 prior ASSISTANT texts, 393 calls (343 assistant + 50 user), and 372 results. Six prompts have no prior call; eight have no prior result. Target responses contain 24 assistant text events and 37 tool calls across 23 rows.
- Inference view is constructed before analysis as exactly `{id, prompt, response}`. `id` is logging/joining only. Domain prefix, label, explanation, and derived family are unavailable to the semantic decision.

| Dependency | Required by frozen E2E path? | Comes from competition prompt? | Research-only? |
|---|---|---|---|
| prompt / response | Yes after adaptation | Yes | No |
| separated system policy / current user request / history | Yes (`E2ECaseInput`) | Derivable from marked prompt, but no adapter existed | Adapter artifact |
| tool catalog and argument schema | Yes for catalog/binding | Yes, as textual typed specifications | No |
| tool provider/version/schema hash metadata | Needed for trusted T1 identity | No | Yes unless source explicitly supplies it |
| T1 reads/writes/effect/failure/freshness contracts | Needed only for definitive effect/state premises | Usually not explicit; subset may be source-derived | Manually authored full contracts are research-only |
| state contract | Used for preservation/current-state proofs | No separate trusted object; observations exist in trajectory | Research-only unless directly source-derived |
| history completeness/basis | Used for absence/completeness proofs | Official contract says prompt is full context, but no row-level closure object | Research metadata; conservative adapter does not invent closure |
| authoritative policy/goal readings or behaviors | Used only for oracle/closure modes | No | Yes |
| precomputed LLM cache | Required for offline replay, not logically required for live inference | No | Yes |
| case family / gold status / gold binary / notes | Present in research corpus type | No and forbidden at inference | Yes |

Conclusion before fixes: B4h-sound-v2 cannot be called directly as `analyze(prompt, response)`. It requires an `E2ECaseInput`, an injected semantic backend, and explicit choices for unavailable trust metadata. A minimal, lossless raw-prompt adapter is required; missing trust premises must remain absent/unknown.

# Baseline run

## 2026-09-16T20:03:10+03:00 — frozen no-fix attempt on all 46 rows

- Command concept: construct frozen `GuardianE2EV1` with `E2EArmConfig("B4h", ("h0_hist",), ("conservative",))`, B3 semantics and Audit adapter, then pass each gold-free `{id,prompt,response}` record directly to `analyze_e2e_v1`.
- Expected: determine whether frozen B4h accepts competition input without implementation changes.
- Result: 0/46 completed; all 46 raised `AttributeError: 'dict' object has no attribute 'state_contract'` at `source_adapter_v1.build_source` because the public record is not research `E2ECaseInput`.
- Primary blocker: `MISSING_COMPETITION_ADAPTER` / `INPUT_FORMAT_MISMATCH`. Downstream latent blockers are missing trusted T1, state contract, completeness/closure metadata, and unseen frontend cache entries; they cannot be quantified until raw input reaches the core.
- Separate command: legacy `scripts/predict.py --backend none` completed 46/46, confirming that `valid.parquet` and marker parsing are readable. It does not exercise B4h and is not scored as its baseline.
- Decision: the mandatory first baseline attempt is complete with a precise blocker. It is now permissible to add only the minimal competition adapter/runner needed to expose the existing frozen core; no proof semantics are changed.

## 2026-09-16T21:18:00+03:00 — minimal adapter milestone

- HEAD before implementation: `0d5f933` (worklog milestone), with frozen semantic reference `315bee3` retained in history.
- Added a strict `CompetitionInputAdapter` which accepts exactly `id,prompt,response`, preserves the complete marked prompt byte-for-byte, extracts only source-delimited policy/current-user text, and translates the declared argument grammar into JSON-schema-shaped data with exact source spans.
- The adapter leaves T1, state, closure, authoritative readings, and oracle behaviors absent. Source hashes identify prompt declarations but do not assert provider identity, business effects, freshness, completion, reads, or writes.
- Added a gold-firewalled runner for R0/R1/R2. It reads only the three inference fields, writes and hashes every requested prediction file, and only then reopens `id,label` for scoring.
- On this public input, R0 has no manually supplied research T1 to consume, so its available evidence currently equals R1 plus the same untrusted T2 proposal path. This equivalence is reported rather than disguised. R2 disables T2/effect proposals and retains structural/schema/trajectory evidence.
- Validation: all 46 public rows adapted successfully and reconstructed an exactly equal raw prompt. New adapter/firewall tests passed (5/5); existing E2E and soundness tests passed (101/101). A later combined run reported 105 passed plus one environment-only pytest temporary-directory setup error; a retry with an explicit workspace temp directory hit the same Windows ACL issue before provider tests could execute. No semantic regression was observed in the completed suites.
- Next: make the first full semantic run, seal predictions, then perform failure decomposition before considering any semantic fix.

## 2026-09-16T21:24:00+03:00 — live-model preflight blocker

- Required backend configuration is explicit in the runner: B.AI Chat Completions, model `qwen3.8-flash`, credential environment name `b_ai_api_key`. Secret values and request text are never written to artifacts.
- A real-row smoke request was not sent because external transmission of the dataset requires explicit user approval. A separate synthetic-only diagnostic request contained no competition prompt/response.
- Synthetic preflight result: HTTP 400, provider code `insufficient_user_quota`, type `api_error`; the redacted message flags indicate insufficient balance/credit. Only hashes, lengths, codes, and boolean flags were retained.
- Classification: `MISSING_LLM_RESULT` + `CACHE_DEPENDENCY` + external runtime/quota blocker. The existing frozen caches do not contain unseen public-case frontend inputs, so they cannot complete the required 46-case run.
- Interpretation: the adapter/inference path is locally ready, but no honest R0/R1/R2 development metrics or failure decomposition can be produced until B.AI quota is restored. Repeating the same API request cannot add evidence and is intentionally avoided.

# T1 / tool-semantics audit

## 2026-09-16T21:18:00+03:00 — available source-grounded subset

- `EXPLICIT_SCHEMA`: tool existence, argument existence/type/requiredness/enums/nesting, with prompt spans. These are trusted as declaration facts, not effects.
- `EXPLICIT_TOOL_DESCRIPTION`: text and span are preserved for audit, but no business-effect atom is currently promoted to trusted T1.
- `EXPLICIT_SYSTEM_POLICY`: exact policy text/span is available to H0; its semantic reading remains an LLM proposal checked by the existing lowering/grounding machinery.
- `OBSERVED_TRAJECTORY`: prior calls, arguments, results, ordering, requestor, and exact values are present in the normalized ledger.
- `NOT_AVAILABLE` or `MANUAL_ORACLE_ONLY`: authoritative freshness, reads/writes, result ownership beyond explicit fields, effect guarantee, completion/failure semantics beyond literal observations, state persistence, closure, and possible side effects.
- No inference from a tool name or a bare `SUCCESS` value is promoted to a trusted business effect. The weakest structural/schema/policy proof remains usable without rich T1; missing effect premises remain unknown.

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
