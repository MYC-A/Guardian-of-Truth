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

## 2026-09-16T21:31:00+03:00 — exact frozen-cache coverage audit

- Command: merge all 29 existing `outputs/vnext/*cache*.json` files in memory, inject a fail-closed offline backend for misses, and run the adapted B4h configuration over all 46 gold-free inputs. No network call, label, or explanation was used and no prediction artifact was presented as the live baseline.
- Seeded cache: 1,897 unique exact keys. Reachable semantic requests: 599; hits: 129; misses: 470. All 46 cases completed transport without a Python exception but ended `UNRESOLVED`.
- Historical H0 primary: 29 hits / 17 misses across 46 requests; its repair path showed the same split. T2 effect proposals: 71 hits / 150 misses across 221 observed call/result pairs.
- Conservative Goal: 0 hits / 46 misses. Each of the ten claim passes (`disposition`, `kind`, `modality_polarity`, `predicate`, `object_entities`, `time`, `source`, `actor`, `relations`, `explicit_causality`) had 0 hits / 24 misses for the 24 target responses containing text. Operational binding was not reachable with usable frontend readings in this fail-closed replay.
- Interpretation: the old cache is not merely an optimization. It partially replays repeated policy/effect inputs but has zero coverage for the real target Goal/Claims inputs and cannot support unseen complete inference. This quantitatively confirms `CACHE_DEPENDENCY`; a live semantic backend (or a separately authorized local model) is required for the requested baseline.

## 2026-09-16T21:48:00+03:00 — user-authorized Groq fallback preparation

- After B.AI returned `insufficient_user_quota`, the user explicitly requested trying `GROQ_API_KEY` with either `openai/gpt-oss-120b` or `qwen/qwen3.8-27b`.
- A models-list request sent no competition data and confirmed both exact model IDs are available to the supplied Groq account. `qwen/qwen3.8-27b` is selected first because it keeps the Qwen model family while testing a distinct provider; this is a provider fallback, not a claim that it is identical to the originally requested B.AI `qwen3.8-flash`.
- The runner now binds provider, model, and credential-variable name explicitly. Cache, progress, and receipts are provider/model-scoped; prediction seals include provider/model/input hash, preventing cross-model cache contamination.
- The saved `.env` value still contains a trailing non-ASCII `U+042D` character. The client rejects it locally as `invalid_api_key`; removing that character in-process proved the remaining credential valid, but the full run will use the saved value only after the user saves the correction. No public prompt/response has yet been sent to Groq.
- Validation after provider generalization: 103/103 E2E+soundness tests and 7/7 focused adapter/firewall/provider tests passed.

## 2026-09-16T21:57:00+03:00 — Groq transport preflight

- The saved credential still has the trailing invalid `U+042D`; for this process only, the already-validated ASCII portion was loaded without modifying `.env` or writing the credential anywhere.
- One synthetic request to `qwen/qwen3.8-27b` succeeded with `transport_status=SUCCESS` and `schema_status=VALID`. This proves endpoint authentication, selected-model availability, Chat Completions transport, JSON extraction, and local schema validation.
- The subsequent one-row R1 smoke command was rejected before execution by the environment's external-data safeguard: asking to try a Groq model is not considered explicit authorization to export the contents of `valid.parquet` to Groq.
- No competition prompt or response was transmitted. Next gate: explicit user consent to send the public dataset's `prompt` and `response` fields to `api.groq.com`; then run one-row smoke followed by the full gold-firewalled baseline.

# T1 / tool-semantics audit

## 2026-09-16T21:18:00+03:00 — available source-grounded subset

- `EXPLICIT_SCHEMA`: tool existence, argument existence/type/requiredness/enums/nesting, with prompt spans. These are trusted as declaration facts, not effects.
- `EXPLICIT_TOOL_DESCRIPTION`: text and span are preserved for audit, but no business-effect atom is currently promoted to trusted T1.
- `EXPLICIT_SYSTEM_POLICY`: exact policy text/span is available to H0; its semantic reading remains an LLM proposal checked by the existing lowering/grounding machinery.
- `OBSERVED_TRAJECTORY`: prior calls, arguments, results, ordering, requestor, and exact values are present in the normalized ledger.
- `NOT_AVAILABLE` or `MANUAL_ORACLE_ONLY`: authoritative freshness, reads/writes, result ownership beyond explicit fields, effect guarantee, completion/failure semantics beyond literal observations, state persistence, closure, and possible side effects.
- No inference from a tool name or a bare `SUCCESS` value is promoted to a trusted business effect. The weakest structural/schema/policy proof remains usable without rich T1; missing effect premises remain unknown.

## 2026-09-16T21:48:00+03:00 — machine-readable source coverage

- Generated `outputs/vnext/real_valid/premise_coverage.csv` from only `id,prompt,response`, before any gold access or live semantic inference.
- 12,235 rows total: 46 explicit system-policy sources; 765 observed trajectory events (393 calls, 372 results); 687 declared tools; 1,590 explicit argument declarations; 1,590 untrusted argument-meaning candidates; and 687 exact tool-description sources.
- For each declared tool, ten effect/state premise families are recorded separately: reads, writes, entity ownership, result ownership, freshness, effect guarantee, completion semantics, failure semantics, state persistence, and possible side effects. All 6,870 such rows remain `AMBIGUOUS`, `trusted=false`, pending source-grounded extraction and deterministic validation.
- This artifact distinguishes “source text exists” from “trusted semantic fact established.” It contains no tool-name effect inference and no manual/oracle T1.

# Failure decomposition

## 2026-09-17 — sealed Mistral baseline and post-seal decomposition

- Provider fallback sequence: Gemini `gemini-3.6-flash` synthetic preflight was `SUCCESS/VALID`, but real prompts exhausted the external rate window after four valid stages. Mistral `ministral-14b-latest`, using the exact lowercase `.env` aliases `mistral_model` and `mistral_api_key`, passed synthetic and one-row smoke tests. The one-row smoke produced 15 transport successes (14 schema-valid, one schema-invalid).
- Full command: `python scripts/evaluate_real_valid.py --provider mistral --modes R0,R1,R2 --cache-mode resume --output-dir outputs/vnext/real_valid --interval-seconds 1 --max-output-tokens 4096 --reasoning-effort none` (resumed once after an external rate limit with a five-second interval).
- All 46 prediction rows for all three modes were written and SHA-256 sealed before `label`/`explanation` were loaded. `R0`, `R1`, and `R2` were identical: TP=2, FP=0, FN=21, TN=23, precision=1.0, recall=0.086957, F1=0.16; `PROVED_ERROR=2`, `PROVED_NO_ERROR=0`, `UNRESOLVED=44`, `INCONSISTENT=0`; false-certified ERROR/NO_ERROR and execution errors were all zero.
- `scripts/analyze_real_valid_failures.py` verifies all three prediction seals before reading gold and emits `failure_decomposition.csv/json`. The 46-row CSV contains outcome, internal status, primitive cause, observed failure family, dependency bucket, frontend failures, missing premises, and the public explanation. It is diagnostic only and is never imported by inference.

| Root cause | FP | FN | UNRESOLVED | total |
|---|---:|---:|---:|---:|
| POLICY_PARSE | 0 | 7 | 17 | 19 |
| GOAL_PARSE | 0 | 0 | 7 | 7 |
| CLAIM_PARSE | 0 | 1 | 5 | 5 |
| TOOL_BINDING | 0 | 5 | 5 | 5 |
| TEMPORAL_REASONING | 0 | 3 | 3 | 3 |
| ARGUMENT_PROVENANCE | 0 | 2 | 2 | 2 |
| CERTIFICATE | 0 | 0 | 2 | 2 |
| ARGUMENT_BINDING | 0 | 1 | 1 | 1 |
| STATE_EVIDENCE | 0 | 1 | 1 | 1 |
| TOOL_SPEC_PARSE | 0 | 1 | 1 | 1 |

| Dependency | Cases |
|---|---:|
| Works without T1 | 2 |
| Needs prompt-derived semantics | 4 |
| Needs manual/oracle T1 | 0 established |
| Blocked by Policy parsing | 17 |
| Blocked by Goal/binding | 16 |
| Blocked by claims | 5 |
| Blocked by state/effect evidence | 2 |
| Blocked by cache/runtime | 0 after the completed run |

- The observed positive families were: unavailable/wrong-executor tool 5, policy precondition/sequence 4, premature escalation 4, unsupported argument provenance 2, and one each for schema mismatch, confirmation prerequisite, identity verification, stale/temporal state, ignored available evidence, failed-call repeat, fabricated action/result, and other policy/goal reasoning.
- R0/R1/R2 equality is evidence that rich T1/T2 effect semantics was not the decisive baseline bottleneck. The dominant measured blockers are higher: policy/goal/claim frontends and missing direct structural validation. “No manual/oracle T1 established” does not prove that no remaining case could benefit from such semantics.

The following table was the **pre-run representability audit** and is retained for comparison with the measured result.

| Real failure family | Static support | Existing mechanism / missing premise |
|---|---|---|
| unsupported argument provenance | PARTIALLY_SUPPORTED | Exact calls, arguments, user text, and source spans exist; Goal scope/binding can compare values, but complete provenance closure is not established. |
| wrong reservation/entity | PARTIALLY_SUPPORTED | Exact entity references and alternative bindings exist; ownership/alias relations not explicit in schema require trusted source semantics. |
| stale state | REQUIRES_MISSING_PREMISE | Symmetric staleness and later-attempt invalidation are implemented, but authoritative fresh-read/write identity is T1-dependent. |
| newest-state selection | PARTIALLY_SUPPORTED | `LATEST_OBSERVATION` semantics are implemented; deciding which result is an authoritative state observation requires reads/result-ownership/freshness premises. |
| confirmation prerequisite | REQUIRES_MISSING_PREMISE | BEFORE/ONLY_IF obligations and event order are representable; proving absence of a required prior confirmation needs source-history closure, deliberately absent in competition mode. |
| identity verification with multiple fields | PARTIALLY_SUPPORTED | Multiple exact entity keys and candidate bindings are representable; cross-field identity equivalence/result ownership is not supplied by schemas alone. |
| schema/argument mismatch | NOT_REPRESENTABLE | The adapter preserves required/type/enum/nesting declarations, but frozen B4h passes schemas to T2 and has no direct schema-validity violation component for target calls. |
| unavailable tool | NOT_REPRESENTABLE | Catalog membership is known, but frozen B4h has no standalone obligation that marks an out-of-catalog target invocation as an error. |
| action not requested by user | PARTIALLY_SUPPORTED | Goal contracts and target invocation binding exist; an extra action is not automatically prohibited unless the source expresses a prohibition/scope relation. |
| fabricated action | REQUIRES_MISSING_PREMISE | ACTION_COMPLETED claims bind to calls/effects; absence remains UNKNOWN without complete-history/effect closure. |
| fabricated result | PARTIALLY_SUPPORTED | Text claims bind to exact observed result fields and can be contradicted; unsupported absence cannot become false without closure. |
| intent vs completed action | PARTIALLY_SUPPORTED | Claim kind and target level distinguish desired/attempted/completed; completed business effects still require trusted effect semantics. |
| policy exceptions | PARTIALLY_SUPPORTED | Conditions/exceptions and ALL/ANY gates exist; frozen historical atom catalog cannot represent many value-level conditions from prose. |
| sequencing rules | PARTIALLY_SUPPORTED | BEFORE/AFTER lowering and ledger order exist; frontend/binding accuracy and closure remain empirical/missing. |
| wrong entity ID | PARTIALLY_SUPPORTED | Exact identity alternatives avoid silent winner selection; definitive mismatch depends on complete candidate/ownership evidence. |
| failed calls | PARTIALLY_SUPPORTED | Failure rows never fabricate success/effect; interpreting provider-specific failure/completion fields needs source-grounded semantics. |
| failure claimed as success | PARTIALLY_SUPPORTED | Literal result-field contradiction is representable; business completion claims need result ownership/effect guarantees. |
| state-preservation violations | REQUIRES_MISSING_PREMISE | Preservation solver/checker logic exists, but competition prompts provide no trusted state contract or writes/effect contract. |

Static conclusion before live data: structural evidence is substantial, but several headline classes are only partially expressible and two (`schema/argument mismatch`, `unavailable tool`) lack a direct B4h violation primitive. This is a candidate explanation to test against sealed failures, not yet a root-cause count.

# Fix iterations

## Iteration 1 — KEEP (`92b5d26`)

- Root cause: `TOOL_BINDING` (five FN). Exact pre-fix audit: five target responses contained at least one call whose name was absent from the source-complete `[AVAILABLE TOOLS]` catalog; all five were gold-positive and no gold-negative case matched.
- Hypothesis: catalog membership is a structural source fact. If the adapter proves the catalog complete, every target call must match one declared interface; an out-of-catalog call is a violation independent of unresolved policy/goal interpretations. No effects are inferred from tool names.
- Implementation: preserve the frozen LLM frontend catalog, add a separate declared-only catalog, construct a source-invariant disjunction over declared tool identities per target call, and independently reconstruct/check it in the certificate checker. Catalog completeness is explicit adapter metadata and is never inferred from observed calls.
- Tests: paired available/unavailable call; tool/entity/value renaming; explicit non-invention of catalog completeness; frozen-frontend isolation; and an incomplete unrelated policy axis. Full regression: 109/109 E2E and soundness tests passed.
- Full rerun: `--run-label fix1_final`, exact semantic cache replay, all 46 cases and all three modes. Before (each mode): TP=2 FP=0 FN=21 TN=23, F1=0.16, 2 proved / 44 unresolved. After: TP=7 FP=0 FN=16 TN=23, precision=1.0, recall=0.304348, F1=0.466667, 7 proved / 39 unresolved.
- Corrections: the five pre-identified out-of-catalog cases. Regressions: none. Every correction has a `source:declared-tool-membership` false witness in every material world and a valid certificate. False-certified ERROR/NO_ERROR remain zero.
- A broader draft that also changed the LLM frontend catalog was rejected during witness review because it mixed a policy-frontend correction into this root cause. `fix1_final` is the isolated KEEP result.

## Iteration 2 — KEEP (`0dbacb5`)

- Root cause: `TOOL_SPEC_PARSE`. An exact pre-fix scan found three gold-positive target calls that violated the source-declared closed argument schema and zero matching gold-negative rows. The explanation-based coarse baseline taxonomy had placed two of these rows under policy reasoning, so the exact structural scan—not explanation wording—defines the affected set.
- Cases affected: `airline__21::t7`, `airline__23::t10`, and `airline__44::t22` (development diagnostics only; no case ID or domain token appears in production logic).
- Hypothesis: a target call that violates the exact argument interface declared in the prompt is erroneous independently of unresolved policy, goal, state, or effect semantics. Unknown or unsupported schema constructs must remain `UNKNOWN`, never violations.
- Production change: add a pure deterministic validator for the adapter's exact schema subset (`object`, `array`, scalar/null types, `required`, `properties`, `additionalProperties`, `items`, and `enum`); introduce a source-invariant target-schema atom; and independently reconstruct its binding in the certificate checker. No tool behavior or business effect is inferred.
- Tests: nested types/requirements/enums/additional properties; unsupported-keyword abstention; paired valid/invalid calls; tool/field/value renaming; and incomplete unrelated policy axes. Full regression: 116/116 E2E and soundness tests passed.
- Before (each mode): TP=7 FP=0 FN=16 TN=23; precision=1.0, recall=0.304348, F1=0.466667; 7 `PROVED_ERROR`, 39 `UNRESOLVED`.
- After (each mode): TP=10 FP=0 FN=13 TN=23; precision=1.0, recall=0.434783, F1=0.606061; 10 `PROVED_ERROR`, 0 `PROVED_NO_ERROR`, 36 `UNRESOLVED`, 0 `INCONSISTENT`; certified coverage=0.217391.
- Corrections: the three pre-identified schema-invalid rows. Regressions: none. All corrections have a `source:declared-tool-schema-validity` false witness and valid certificate; false-certified ERROR/NO_ERROR remain zero.
- Soundness impact: increased only source-certified error coverage. Unsupported schema syntax and incomplete catalogs fail closed to `UNKNOWN`. Decision: **KEEP**.

# Remaining failures

- After Iteration 2: 13 FN and 36 `UNRESOLVED`; FP, false-certified ERROR/NO_ERROR, and execution errors remain zero.
- Post-seal coarse counts are led by `POLICY_PARSE` (6 FN / 16 unresolved), followed by argument provenance (2 FN), temporal reasoning (2 FN), and one FN each in claim parsing, argument binding, and state evidence. Seven negative rows remain unresolved under `GOAL_PARSE`, but they do not create FP under the conservative competition fallback.
- The policy bucket is heterogeneous: preconditions/sequences, premature escalation, calculations, and other policy/goal reasoning. There is no third isolated source-certified fix supported by several cases. Repeated failed calls require a determinism/retry premise; argument provenance requires sound typed derivations; absence-based prerequisites require history closure. Encoding any of these as string heuristics would weaken soundness, so the cycle stops after two substantial KEEP iterations (the allowed maximum was three).
- Final dependency accounting is: 10 cases proved without T1, 3 currently needing prompt-derived semantics, 0 established as needing manual/oracle T1, 16 blocked by policy parsing, 10 by goal/binding, 5 by claims, and 2 by state/effect evidence. These categories cover all rows but are diagnostic buckets, not mutually causal proofs.
- `valid.parquet` is viewed public development data. Every delta in this report is a **development result**, not a claim about generalization, hidden-test performance, final score, or expected leaderboard position.

# Next architecture hypotheses

The measured bottleneck is policy semantics, not the solver and not a broad missing-T1 layer. Five materially different directions are therefore considered:

| Direction | What changes / target family | Why it may help | Soundness risk | Compute | Complexity | Minimal causal experiment |
|---|---|---|---|---|---|---|
| Role-specific stronger policy model | Replace only historical H0 policy extraction; targets policy preconditions, sequencing, and escalation | Distinguishes model-capability failures from IR limitations while freezing all downstream logic | Medium: plausible but ungrounded rules can create false proofs unless every atom is source-spanned and checker-bound | Medium/high API cost | Low | Run the same 46 rows with only the policy role changed; compare schema-valid extraction, grounded-rule coverage, false certificates, and sealed deltas |
| Deterministic policy grammar | Parse explicit `must`, `only after`, `before`, and exception templates into source-linked rule frames | Directly attacks repeated explicit procedural language without model variance | Medium: scope/negation mistakes | Low | Medium/high | Implement one rule form, use paired negation/scope metamorphics, then measure only cases containing that form |
| Constrained policy IR redesign | Expand the atom/condition vocabulary for value comparisons, calculations, exceptions, and quantified gates | Removes representation ceilings even with a capable parser | High: a richer IR enlarges the proof surface | Medium | High | Hand-author source-grounded IR for a blinded subset; test whether the existing solver can express the gold-described violation before changing extraction |
| Multi-candidate policy consensus | Generate several readings and certify only facts common to all source-grounded readings | Can increase robustness while retaining ambiguity explicitly | Low/medium: unsafe candidate merging | High | Medium | Compare intersection-only consensus with single-reading H0 on frontend coverage and false-definitive count |
| Counterexample-guided policy checking | Ask a verifier for a source quote and a concrete violated condition only for the target action | Focuses compute on material calls and may avoid full-policy parsing | Medium/high: verifier circularity and quote-selection bias | Medium | Medium/high | On policy-FN rows plus matched negatives, require independently replayable quoted predicates and measure accepted-witness precision |

**ONE next experiment:** a role-isolated policy-frontend ablation using NVIDIA `google/gemma-4-31b-it` (the faster available endpoint) against the current Mistral control. Freeze the adapter, claims, goal frontend, world construction, solver, checker, cache settings, and all structural fixes; change only the policy extraction backend. Primary causal question: does a stronger role-specific model reduce the 16 policy-blocked unresolved rows without increasing invalid/ungrounded policy objects or false-certified outcomes? Dataset: the same viewed 46-row development set, with predictions sealed before scoring. Primary metrics: policy schema-valid rate, source-span validity, material policy-rule coverage, TP/FP/FN/TN, internal statuses, and false-certified ERROR/NO_ERROR. Failure criterion: no meaningful grounded-policy coverage gain, any checker-accepted ungrounded rule, or any new false certificate. GPT-OSS-120B remains a fallback transport, not a second experiment arm.

# Static hardcoding audit

## 2026-09-16T22:08:00+03:00 — production scan before live baseline

- `rg` found zero occurrences of the prohibited domain prefixes `airline__`, `banking_knowledge__`, `retail__`, or `telecom__` under `src/`.
- A gold-free scan extracted 221 ID-like tokens from only public `prompt,response` and compared them with every Python source under `src/`; intersection count: **0**. No known reservation/account/customer identifier from the public input is embedded in production code.
- `case_id` uses in the competition path are logging, progress resumption, joins, and returned audit identity. One content hash still included `case_id`; it was corrected so `E2ESource.source_sha256` is now a function of only `prompt,response`. The metamorphic adapter test pins identical source hashes under ID renaming.
- `label` access occurs only in the post-seal scoring function and output field naming. `competition_view` and the strict adapter reject label/explanation/domain fields before inference.
- Result: zero benchmark-specific production hardcoding found in the audited patterns. Research corpus/scoring modules still contain generic `gold_*` fields by design; they are not called by the competition inference path.

## 2026-09-17 — final post-fix scan

- Repeated the prohibited-prefix scan after both KEEP commits: zero `airline__`, `banking_knowledge__`, `retail__`, or `telecom__` occurrences in production Python under `src/`.
- The only `gold_*` references found are the pre-existing research corpus/experiment types. In the real-valid path, `label` is accessed by the runner only after all requested prediction files are written and sealed; the adapter still rejects non-inference fields.
- Both production fixes are invariant under renamed tools, fields, entity IDs, and values in targeted metamorphic tests. No case ID, known reservation/account value, label, or observed gold explanation was added to production logic.

# Final state

- Classification: **D. MAIN_GAP_IS_POLICY_SEMANTICS**.
- Original task: binary response-level contextual-hallucination detection. The solution receives `id,prompt,response`; public development additionally exposes `label,explanation`, which are loaded only after prediction seals. Real prompts include policy/history plus tool descriptions and typed argument schemas.
- B4h-sound-v2 is invoked through the new strict competition adapter and the existing `GuardianE2EV1` B4h/B3 path. The frozen research path had expected separated source fields and could optionally consume trusted T1/state/closure/oracle metadata not supplied by the competition record. The adapter derives only source-present fields and leaves missing trust premises unknown.
- Baseline R1 (identical to R0/R2): TP=2, FP=0, FN=21, TN=23; precision=1.0, recall=0.086957, F1=0.16; 2 `PROVED_ERROR`, 0 `PROVED_NO_ERROR`, 44 `UNRESOLVED`, 0 `INCONSISTENT`; no false certificate.
- Final development result after two KEEP fixes (identical R0/R1/R2): TP=10, FP=0, FN=13, TN=23; precision=1.0, recall=0.434783, F1=0.606061; 10 `PROVED_ERROR`, 0 `PROVED_NO_ERROR`, 36 `UNRESOLVED`, 0 `INCONSISTENT`; no false or uncertified definitive result.
- Fix 1 corrected five out-of-catalog calls with zero regressions. Fix 2 corrected three declared-schema violations with zero regressions. No known soundness bug or production hardcoding remains after the targeted tests and static scan.
- A large Tool Contract Frontend is not justified by this development set: 10 cases now certify from direct source structure, only 3 are bucketed as needing prompt-derived semantics, and zero manual/oracle-only T1 dependency is established. The current largest bottleneck is policy parsing/representation.
- Published branch: `codex-update-run`, tracking `origin/codex-update-run`. The fix commits are `92b5d26` and `0dbacb5`; the sealed artifact head before this publication-status update is `0a9af54809ca8df70d3879eec19deb5d06e9c568`. Report URL: `https://github.com/MYC-A/Guardian-of-Truth/blob/codex-update-run/docs/vnext/e2e/REAL_COMPETITION_VALID_CODEX.md`.
