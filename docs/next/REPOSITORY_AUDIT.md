# Guardian Next repository audit

## Scope and frozen reference

This audit describes the tracked repository tree at commit
`afb7906c3a3244fbc4196fe5cb2ea18ee86e0d96` (`V5.3`). The working branch is
`experiment/guardian-next-from-v5_3` in the separate worktree
`C:\Users\Igor\Desktop\Guardian of Truth Next`.

The commit name is not a reliable architecture boundary. The tree at this SHA
also contains V6/V7/V8/V9 research artifacts. In particular, commit `afb7906`
itself adds the V8/V9 typed and underspecified-semantics prototypes, while its
parent already contains V6/V7 work. A module is classified below by whether the
production entrypoint calls it and by the recorded experimental outcome, not by
the version number in its filename or documentation.

Untracked `src/guardian_truth/next/`, `tests/test_next_soundness.py`, and other
Guardian Next work created after branching are outside this frozen audit.

The supplied `valid.parquet` is an inspected development sample, not an
independent test. It contains 46 rows, 45 trajectory groups inferred from IDs,
23 positive and 23 negative labels, and the columns `id`, `prompt`, `response`,
`label`, `explanation`. Results on it are evidence about this sample only.

## Entrypoints

| Entrypoint | Path | Purpose | Status |
|---|---|---|---|
| `guardian-predict` | `pyproject.toml` -> `guardian_truth.cli:main` | Installed prediction CLI | `PRODUCTION_BASE` |
| `python scripts/predict.py` | `scripts/predict.py` | Thin wrapper around the same CLI | `PRODUCTION_BASE` |
| `guardian_truth.Detector` | `src/guardian_truth/__init__.py` | Programmatic two-string review API | `PRODUCTION_BASE` |
| Docker entrypoint | `Dockerfile` -> `python scripts/predict.py` | Containerized prediction | `PRODUCTION_BASE`, with Parquet caveat |
| `scripts/evaluate.py` | `scripts/evaluate.py` | Development-only exact-family report | `USEFUL_REFERENCE` |
| `scripts/benchmark.py` | `scripts/benchmark.py` | Offline split-aware paired benchmark | `USEFUL_REFERENCE` |
| Model/architecture scripts | `scripts/benchmark_models.py`, `scripts/benchmark_architecture.py` | Model and semantic-arm experiments | `EXPERIMENTAL_CANDIDATE` |
| Research scripts | Remaining `benchmark_*`, `ablate_*`, `freeze_*`, `evaluate_*` scripts | Frozen shadow experiments and diagnostics | Mixed; classified below |

There is no package `__main__` and no unified experiment interface in the
frozen tree. The required `python -m guardian_truth.next.evaluate ...` does not
exist at this SHA.

## Production data flow

```text
CSV / JSONL / Parquet
  -> cli.read_rows + validate_rows
  -> settings.load_env_file
  -> runtime.detector_from_args
  -> Detector.review(prompt, response)
       -> parsing.parse_events(prompt/response)
       -> parsing.parse_catalog(authoritative SYSTEM catalog)
       -> checks.check_calls
       -> checks.check_turn_structure
       -> checks.check_date_gated_actions
       -> provenance.build_graph
       -> rules.check_rules([GUARDIAN_RULES])
       -> planning.analyze_plan([GUARDIAN_PLANNING])
       -> evidence.retrieve + event-level obligations
       -> optional semantic.run_semantic
       -> Review(status = violation | unknown)
  -> decision.decide
       -> exact violation => label 1
       -> else explicitly enabled semantic score >= threshold => label 0/1
       -> else fixed unknown fallback, default label 0
  -> CSV id,label + optional JSONL audit and run report
```

`Detector.review` accepts only `prompt` and `response`. Dataset IDs, labels and
explanations do not cross the inference boundary. `pipeline.py` preserves exact
violations if an optional semantic backend fails. Model findings are rewritten
to `hypothesis`; they cannot manufacture a mechanical proof. The binary adapter
nevertheless thresholds the raw model `risk` when a model backend is explicitly
enabled, and the code correctly labels that score as uncalibrated.

The normalizer recognizes the repository's bracketed role/call/result markers
and arrow-style `TOOL_CALL`/`TOOL_RESPONSE` records. It retains half-open
character spans into the original prompt or response. It does not assign stable
event IDs or request IDs.

## Module classification

Statuses have the following meaning:

- `PRODUCTION_BASE`: executed by the installed/default product path or required
  to configure it.
- `USEFUL_REFERENCE`: reusable implementation or evaluation machinery, but not
  itself an approved new decision path.
- `REGRESSION_TEST_ONLY`: useful primarily for falsification and preserving a
  previously learned failure boundary.
- `EXPERIMENTAL_CANDIDATE`: plausible component that still requires the frozen
  ablations and transfer evidence specified for Guardian Next.
- `KNOWN_BAD`: a tested configuration or translator that failed its recorded
  gate and must not be silently promoted.
- `UNKNOWN`: historical artifact whose current provenance or applicability is
  not strong enough to classify more positively.

### Runtime source modules

| Module | Status | Audit conclusion |
|---|---|---|
| `src/guardian_truth/__init__.py` | `PRODUCTION_BASE` | Public `Detector` export. |
| `types.py` | `PRODUCTION_BASE` | Core Event, Finding, FactNode, ArgumentTrace, Review and source-span records. Does not model effect lifecycle. |
| `parsing.py` | `PRODUCTION_BASE` | Role/event and tool-schema parsing with duplicate-key and non-finite JSON rejection. |
| `checks.py` | `PRODUCTION_BASE` | Availability, schema, explicit turn-structure and one narrow date-gated-action proof. |
| `provenance.py` | `PRODUCTION_BASE` | Entity-scoped observations, version links and candidate-argument traces. Structural equality is deliberately not authorization or world truth. |
| `rules.py` | `PRODUCTION_BASE` | Bounded three-valued interpreter for already compiled `[GUARDIAN_RULES]` JSON. Not a natural-language policy compiler. |
| `planning.py` | `PRODUCTION_BASE` | Bounded search over an explicit `[GUARDIAN_PLANNING]` model. A declared plan is not real-world execution or guaranteed feasibility. |
| `evidence.py` | `PRODUCTION_BASE` | Exact observations and simple lexical evidence retrieval. |
| `semantic.py` | `PRODUCTION_BASE` | Replaceable semantic boundary and fail-safe validation. LLM findings remain hypotheses. |
| `reader.py` | `PRODUCTION_BASE` | Bounded local read/search/graph/entity environment used by model modes. It ranks evidence but proves nothing. |
| `language.py` | `PRODUCTION_BASE` | Current optional holistic `direct`, `graph`, and RLM-inspired inference. Quality is experimental although the runtime path is supported. |
| `uncertainty.py` | `EXPERIMENTAL_CANDIDATE` | Diagnostic memory and bounded recovery. Recovery defaults off and did not establish quality gain. Some diagnostic helpers are used by `language.py`. |
| `llm_client.py` | `PRODUCTION_BASE` | Bounded OpenAI-compatible JSON transport, strict schema option, retries, budgets and safe error taxonomy. |
| `settings.py` | `PRODUCTION_BASE` | Allowlisted dotenv loader; does not override process environment. |
| `runtime.py` | `PRODUCTION_BASE` | Explicit provider/backend selection. Network is disabled by default. |
| `pipeline.py` | `PRODUCTION_BASE` | Current orchestrator. |
| `decision.py` | `PRODUCTION_BASE` | Exact override, raw semantic threshold, explicit unknown fallback. |
| `cli.py` | `PRODUCTION_BASE` | Dataset I/O and streaming prediction/audit output. |
| `benchmarking.py` | `USEFUL_REFERENCE` | Provenance components, leakage checks, calibration/test separation, frozen manifests and paired cluster bootstrap. |
| `reason_metrics.py` | `USEFUL_REFERENCE` | Bounded human/reference reason audit with honest partial-audit bounds. |
| `external_data.py` | `USEFUL_REFERENCE` | Pinned RAGTruth adapter. It covers factual grounding, not general tool-policy verification. |

### Claim, decomposition and formal research

| Module | Status | Audit conclusion |
|---|---|---|
| `claim_verifier.py` | `USEFUL_REFERENCE` | Strong strict JSON/citation contract for one frozen claim/evidence pair. The tested row-level accusation gate is `KNOWN_BAD`, but the relation verifier is reusable. |
| `deterministic_claims.py` | `USEFUL_REFERENCE` | Conservative bound entity/value/argument/arithmetic checks. It deliberately abstains and is not integrated into the row decision. |
| `decomposition.py` | `KNOWN_BAD` | Recorded decision is `KEEP_ONE_SHOT`; the material extractor failed its stop gate. Its final judge also maps no contradiction to `ok` even when ledger entries are insufficient, so it is not a proof of completeness. |
| `decomposition_exact.py` | `EXPERIMENTAL_CANDIDATE` | Proof-safe but very narrow self-contained arithmetic route; dates, IDs, percentages, units and ambiguous text abstain. |
| `formal_reasoning.py` | `USEFUL_REFERENCE` | Bounded forward solver with explicit negation, scope checks and proof certificates. The downstream solver is not the observed bottleneck. |
| `formal_translation.py` | `KNOWN_BAD` | Current FaiRR-style translation/application protocol failed validity and faithfulness gates; shadow only. |
| `typed_catalog.py` | `USEFUL_REFERENCE` | Exact provenance and conservative typed candidate inventory suitable for a future binder/compiler. |
| `typed_formalization.py` | `EXPERIMENTAL_CANDIDATE` | Typed validation, canonicalization and distinguishing witnesses are valuable; accepted translations have not proved faithful. |
| `typed_translation.py` | `KNOWN_BAD` | V8 free/typed LLM translations were unstable; an accepted typed output was false-verified. |
| `underspecified_semantics.py` | `EXPERIMENTAL_CANDIDATE` | Keep the outer-space, holes, revision and two-query invariant kernel. Its current lexical construction layer is `KNOWN_BAD`: 45/84 feature coverage and 0/16 frozen policy audit passes. |
| `semantic_metamorphic.py` | `USEFUL_REFERENCE` | Strong behavioral and outer-coverage falsification utilities; should become regression gates. |
| `semantic_feature_adapter.py` | `REGRESSION_TEST_ONLY` | Adapter for measuring the current lexical prototype, not an approved production translator. |
| `outer_benchmarking.py` | `REGRESSION_TEST_ONLY` | Offline V9 falsification and exact-control preservation. |

### Tests and frozen research artifacts

The frozen tree collects 391 pytest cases. Production-oriented tests in
`test_core.py`, `test_cli.py`, `test_date_gate.py`, `test_provenance.py`,
`test_rules.py`, `test_planning.py`, `test_semantic.py`, `test_reader.py`,
`test_language.py`, `test_llm_client.py`, `test_runtime.py`, and
`test_benchmarking.py` are the main regression foundation.

Tests for claims, decomposition, formalization, typed translation and outer
semantics remain valuable even where the corresponding end-to-end approach was
rejected: they encode fail-closed behavior and known counterexamples. Their
passing status proves implementation consistency, not natural-language accuracy.

| Artifact family | Status | Reason |
|---|---|---|
| `experiments/decomposition_*` and decomposition reports | `REGRESSION_TEST_ONLY` | Preserve the failed extractor/architecture decision. |
| `experiments/v6_*` and V6 reports | `REGRESSION_TEST_ONLY` | Preserve compact/turn-structure/accusation-gate evidence; only the exact turn rule entered production. |
| `experiments/v7_*` and V7 reports | `REGRESSION_TEST_ONLY` | Preserve formal-method failure cases and date-gate control. |
| `experiments/v8_*` | `REGRESSION_TEST_ONLY` | Preserve typed-translation sentinels, including false verification. |
| `experiments/v9_*` and V9 reports | `REGRESSION_TEST_ONLY` | Preserve policy coverage and outer-semantics stop gate. |
| `docs/01_*` through `docs/03_*` | `UNKNOWN` | Early concept diagrams; not current implementation truth. |
| `docs/04_*` through `docs/09_*` | `USEFUL_REFERENCE` | Historical architecture and ablation rationale; versioned numbers may be stale. |
| `docs/10_*`, `docs/11_*`, `docs/12_*` | `REGRESSION_TEST_ONLY` | Research-cycle designs and outcomes, not one production architecture. |

Historical documentation mentions several old test counts such as 56 or 175.
Those values are snapshots, not the frozen tree's current collected count.

## Exact mechanisms

The following mechanisms can create a hard `violation`:

1. An assistant calls a tool absent from a complete authoritative system
   catalog.
2. Tool arguments are not an object or violate understood required fields,
   primitive/nested types, or enumerations.
3. More than one assistant tool call is made when a narrowly recognized SYSTEM
   rule explicitly permits only one.
4. Assistant text and a tool call are combined when a narrowly recognized
   SYSTEM rule explicitly forbids both.
5. `resume_line` is called for the same `line_id` after the latest observed
   `contract_end_date`, when both the exact policy sentence and one authoritative
   current date are present.
6. A precondition of an explicit, valid `[GUARDIAN_RULES]` rule evaluates to
   false under the bounded interpreter.

The exact core has sound design choices worth preserving:

- user text cannot install tools or hard policy;
- user actions are not assistant actions;
- assistant calls are intentions, not completed effects;
- candidate tool results are not independent history evidence;
- missing facts and unknown applicability remain unknown;
- bool, number and string identities are not coerced;
- same value in another field/entity/tool/role/time does not establish support;
- incomplete, ambiguous or newer unparsed state prevents stale proof;
- every hard finding cites inspectable original spans.

The main limitation is coverage. Natural-language policy is not compiled. Two
turn rules and the date gate are English regex/domain-specific exact checks. The
general rule engine only consumes a policy that is already represented as
`[GUARDIAN_RULES]`; the repository has no trusted process that creates that block
from arbitrary policy text.

## LLM mechanisms

`runtime.py` supports Groq, OpenRouter, Gemini's OpenAI-compatible endpoint and
a local OpenAI-compatible loopback endpoint. Remote provider hosts and credential
variables are bound separately. The local backend refuses non-loopback hosts.

`llm_client.py` provides:

- `temperature=0`, non-streaming requests;
- JSON-object or JSON-schema response format;
- configurable strict schema;
- bounded output bytes, output tokens, timeouts and retries;
- retry accounting against a shared request/input/time budget;
- no redirect following;
- fixed safe error categories without response bodies or secrets;
- optional `low`, `medium`, or `high` reasoning effort;
- reported token usage retention.

The current semantic arms are:

- `direct`: full prompt plus candidate response in one model call;
- `graph`: one selected evidence packet plus structural metadata;
- `rlm`: bounded local read/search/graph/entity requests over multiple rounds;
- `baseline`, `strict`, and `compact` output protocols;
- optional `observe`, `directed`, or `repeat` uncertainty recovery;
- experimental `decomposed` extraction, verification ledger and final judge.

The incumbent model path is holistic: the model sees trace evidence and the
candidate while creating the claims it later judges. It is not a blind Claims
stage. Output validation checks JSON shape, citations and internal verdict/claim
consistency, but does not independently prove semantic entailment. The RLM path
is a bounded read-only retrieval loop, not a general REPL and not a formal proof
graph. Existing experiments did not establish that it outperforms the graph arm.

## Benchmark and evaluation inventory

### Reusable mechanisms

- `benchmarking.prepare_examples` unions all shared provenance keys and exact or
  whitespace-normalized duplicates, including transitive links.
- Explicit split conflicts are rejected.
- Threshold selection accepts calibration rows only.
- `run_benchmark` freezes configuration after optional calibration and before
  any test inference.
- Test labels remain outside detector calls.
- Paired percentile bootstrap resamples whole provenance components and uses the
  same sampled rows for both systems.
- Architecture runners record configuration/source hashes, logical LLM calls,
  HTTP attempts, reported tokens, elapsed time, structured validity and audit
  traces.

### Important baseline mismatch

`scripts/evaluate.py` does not evaluate the default `Detector()` path. Its
largest arm enables only `availability`, `schema`, and `provenance`, so it omits
`rules` and the production date gate. On the frozen development file this arm
reports 11 true positives and F1 0.6471, while a direct default-backend replay
produces 12 true positives, zero false positives, 11 false negatives, 23 true
negatives, and F1 0.6857. The official Guardian Next baseline must therefore be
derived from the actual prediction entrypoint/default Detector and recorded in
one manifest; the legacy component report is not sufficient.

The historical V7 LLM development replay reports TP=17, FP=5, FN=6, TN=18 and
F1=0.7556. It is an inspected, provider-dependent development result, not a
guaranteed reproducible baseline or hidden-test estimate.

### Missing benchmark requirements

- `benchmarking.load_examples` supports CSV/JSONL but not Parquet.
- `valid.parquet` has no explicit split or provenance columns required by the
  split-aware harness.
- There is no McNemar test or hierarchical bootstrap.
- There are no AUROC/AUPRC, Brier/ECE, selective-risk/coverage, invariant-error,
  per-contract, or confidence-bucket metrics.
- Scripts record some latency and token totals, but there is no common p50/p95,
  provider error/rate-limit, or monetary-cost report.
- Budget fairness is not enforced across every architecture arm by one runner.
- No unified blind-freeze lifecycle covers adapter, dataset, model, prompt,
  threshold and first external run.

### External data

`external_data.py` and `scripts/prepare_ragtruth.py` provide a pinned RAGTruth
adapter with source-group separation and preservation of the original test split.
RAGTruth is a factual-grounding transfer set, not a general agent tool-policy
benchmark, and no live external result is frozen in the repository.

ATFD, tau-bench, AgentDojo, ToolSandbox and an additional independent source are
absent. There is no external manifest covering those required adapters.

## Soundness-invariant coverage

| Invariant | Frozen coverage | Gap |
|---|---|---|
| USER_ACTION != ASSISTANT_ACTION | Strong parser/provenance tests | Carry into the new normalized record schema. |
| INTENT != COMPLETED | Partly documented and enforced for candidate calls | No explicit typed lifecycle. |
| CLAIM != OBSERVED | Candidate text/results do not become history facts | Claims are not first-class records in production. |
| CALL_ATTEMPTED != EFFECT_CONFIRMED | Calls do not refresh rule facts | No effect-confirmation contract. |
| FAILED != COMPLETED/NO_EFFECT | Not represented generally | Failure semantics and no-effect certainty are missing. |
| not found != absent | Conservative components exist | No completeness certificate or common end-to-end invariant. |
| UNKNOWN != FALSE | Strong in `rules.py` and formal tests | Binary fallback still maps unknown to contest label 0. |
| proposal/promise != execution | Planning is explicitly non-executing | No typed assistant-claim distinction. |
| request != confirmation | Only indirect prompt guidance | No explicit record/test pair. |
| same type != entity | Strong provenance/typed tests | Binder is heuristic and field-name based. |
| old != current | Versioned provenance and stale-state tests | No general effect-state ledger. |
| tool name != effect | Planner requires explicit declared effects | No independent Tool Effect Registry. |
| LLM interpretation != fact | Semantic findings are hypotheses | Raw score can still drive a binary label when enabled. |

The existing 15 semantic metamorphic pairs cover useful policy-language
transformations such as arrival/departure, temporal direction, strict/inclusive
boundaries, may/must, all/some, only-if, exceptions, voice, reference, stale
state and distractors. They do not replace end-to-end pairs for call failure,
effect confirmation, absence, request/confirmation and completed-action claims.

## Dependencies and packaging

`pyproject.toml` declares Python `>=3.10`, no mandatory runtime dependencies,
and an optional `data` extra containing `pandas>=2` and `pyarrow>=15`. HTTP and
JSON transport use the standard library. This keeps the exact CSV/JSONL runtime
small and makes tests easy to fake without network access.

Reproducibility gaps:

- dependency upper bounds and exact versions are not frozen;
- no lockfile exists;
- pytest and other development tooling are not declared;
- no CI, formatter, linter or static-type configuration is tracked;
- pytest reports an unset `asyncio_default_fixture_loop_scope` warning from the
  installed environment;
- the Docker image runs `pip install .`, not `pip install ".[data]"`, so the
  advertised Parquet input path is unavailable inside the image without an
  additional package layer.

Secrets are excluded by `.gitignore` (`.env`, `.env.*`, including the user's
temporary `.env.example`); `.env.template` is the only tracked template. Reports
must record environment-variable names and capability outcomes, never values.

## Technical debt relative to Guardian Next

### Missing core architecture

- No trace-independent `PolicyBundle` or compile-once policy cache.
- No exhaustive structural policy segmentation or source coverage ledger.
- No P0-P6 policy arms, candidate pool, oracle@k, pairwise judge, mutant suite,
  or distinguishing-world evaluation around policy candidates.
- No Tool Effect Registry or T0-T3 contract arms.
- No representation for guaranteed versus possible effects, failed-call
  no-effect certainty, reads/writes, freshness, idempotence or contract
  provenance.
- No append-only typed Evidence Ledger with attempted, failed, returned,
  observed and effect-confirmed states.
- No completeness certificate for negative/absence conclusions.
- No blind general Claims IR and no completeness certificate for claim coverage.
- No binder that deliberately preserves multiple entity/time candidates.
- No shared four-valued solver and binary adapter over its statuses.
- No strict false-refusal proof object.
- No evidence-gaining fast/slow router with measured conditional gain and
  incumbent protection.
- No L0/L1/L2 full/top-k/compile-once long-context experiment.

### Current implementation risks

- Tool call/result pairing is based on `(role, tool name)` and order, not stable
  request IDs; parallel same-tool activity becomes ambiguous.
- Entity detection depends on field names ending in `_id` or `_number`, plus a
  small temporal-field allowlist.
- Catalog parsing supports a constrained textual grammar and cannot establish a
  complete arbitrary tool schema.
- Event-level obligations are not atomic material claims.
- Lexical retrieval can omit a necessary condition or exception.
- `run_semantic` intentionally collapses unexpected backend exceptions to a safe
  generic issue, which protects data but limits root-cause observability.
- Provider discovery is fragmented: `/models` listing exists for OpenRouter and
  Gemini, while Groq uses a separate connection smoke path. There is no common
  capability probe suite.
- A provider switch can inherit a default model unsuitable for the selected
  provider if no provider-specific model is configured.
- The prediction CLI opens and writes outputs incrementally and has no atomic
  completion marker or resume contract; a crash can leave partial artifacts.
- Baseline definitions differ among scripts, making accidental comparator drift
  likely.

## Reproduction commands available at the frozen SHA

Install and test:

```powershell
python -m pip install -e ".[data]"
python -m pytest -q
python -m unittest discover -s tests -v
```

Run the actual autonomous default baseline:

```powershell
python scripts/predict.py `
  --input valid.parquet `
  --output outputs/v5_3/predictions.csv `
  --audit outputs/v5_3/audit.jsonl `
  --run-report outputs/v5_3/run.json `
  --backend none
```

Run the legacy component report, retaining the date-gate caveat above:

```powershell
python scripts/evaluate.py `
  --input valid.parquet `
  --output outputs/v5_3/component_metrics.json
```

Run the leakage-aware synthetic mechanism benchmark:

```powershell
python scripts/generate_scenarios.py --output outputs/scenarios.jsonl
python scripts/benchmark.py `
  --input outputs/scenarios.jsonl `
  --output outputs/benchmark.json `
  --scores outputs/scores.jsonl `
  --assign-splits `
  --bootstrap-samples 1000
```

Inspect existing provider connectivity without exposing credentials:

```powershell
python scripts/check_connection.py --env-file .env
python scripts/check_connection.py --live --env-file .env --model <model>
python scripts/probe_provider_models.py --provider openrouter --env-file .env
python scripts/probe_provider_models.py --provider gemini --env-file .env
```

Run an existing semantic architecture arm:

```powershell
python scripts/benchmark_architecture.py `
  --variant baseline `
  --provider groq `
  --input valid.parquet `
  --output-dir outputs/architecture_baseline `
  --env-file .env `
  --model <model>
```

Prepare the only existing external reserve:

```powershell
python scripts/prepare_ragtruth.py `
  --download `
  --raw-dir outputs/ragtruth_raw `
  --output outputs/ragtruth_reserved.jsonl `
  --manifest outputs/ragtruth_manifest.json
```

Reproduce the offline V9 falsification:

```powershell
python scripts/benchmark_outer_semantics.py
```

## Decision for Guardian Next

The dependable base is the parser, conservative exact checks, source spans,
entity/version-aware provenance, semantic isolation, safe transport, and
leakage-aware benchmark machinery. Reusable research components are strict
claim/citation contracts, typed records, proof certificates, explicit holes,
outer-space invariant evaluation and metamorphic falsification.

The current decomposition final decision, free/typed policy translators,
lexical construction translator and row-level accusation hard gate must not be
promoted. Guardian Next needs to connect the reusable kernels through new,
explicit PolicyBundle, Tool Effect Contract, Evidence Ledger, blind Claims,
Binder and four-valued solver interfaces, then compare those components under a
single frozen evaluation protocol.
