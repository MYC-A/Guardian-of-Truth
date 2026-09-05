# Offline evaluation and controlled generalization checks

`scripts/benchmark.py` compares an offline structural detector with a zero-score or structural baseline. It does not load credentials or call a model service. `scripts/generate_scenarios.py` creates fresh controlled synthetic mechanism cases. These cases are **not an independent natural competition test**, and their scores must not be reported as an estimate of competition performance.

```powershell
python -m pip install -e .
python scripts/generate_scenarios.py --output artifacts/scenarios.jsonl --families 15
python scripts/benchmark.py --input artifacts/scenarios.jsonl --output artifacts/benchmark.json --scores artifacts/scores.jsonl --bootstrap-samples 1000
```

Use `--calibrate` only when threshold selection is intended. It selects each system's F1 threshold exclusively on rows explicitly assigned to `calibration`; ties prefer precision, then the higher threshold. Candidates include 0, 0.5, 1, observed scores, and adjacent-score midpoints, all within [0, 1]. The selected configuration is frozen and hashed before test scoring. Without this option, both thresholds are fixed at 0.5. Unknown structural reviews receive a fixed fallback label zero, not a proof of correctness. Scores are operational values; they are not necessarily probabilities. Established hard violations always predict 1 regardless of threshold. A threshold cannot suppress a score of exactly 1; disabling semantics is a separate configuration choice. Calibrating the numeric constant-zero baseline on data with positives can select threshold zero, making it predict all positives: it is a zero-score baseline, not a fixed all-negative decision rule.

## Input contract and leakage controls

For model comparisons use `scripts/benchmark_models.py`. It writes `frozen_manifest.json`
after calibration and before the first test inference; failed persistence prevents test execution.
Each detector has a separate request/character budget and active review-time clock, shared by its
calibration and test calls. Time spent running the other detector or bootstrapping is excluded;
network waiting and retries are included. Production `predict.py` uses wall-clock time instead.
The resource report includes unresolved-category counts and semantic-score coverage: successful
transport alone does not establish a usable or correct semantic assessment.

CSV and JSONL require `id`, `prompt`, `response`, and integer `label` (0 or 1). Each row must have at least one nonempty `group_id`, `source_id`, `dialogue_id`, `template_id`, or `pair_id`. The `split` value must be `train`, `calibration`, or `test`. Optional `family` and `synthetic` fields describe the evaluation population. Example:

```json
{"id":"case-1","prompt":"...","response":"...","label":0,"source_id":"corpus-a/document-7","dialogue_id":"corpus-a/dialogue-3","template_id":"template-2","pair_id":"pair-1","split":"test","synthetic":true}
```

Group keys are global within each named field; namespace unrelated corpora. All rows sharing any provenance key join one connected component. This union is transitive: A sharing a source with B and B sharing a template with C puts A, B, and C together. Exact and whitespace-normalized prompt/response duplicates also join components. Conflicting duplicate labels and components spanning explicit splits are rejected. Duplicate rows remain in metrics, so the audit reports them and their multiplicity may affect row-weighted results. Whitespace normalization is conservative and may also merge text where internal whitespace is meaningful; inspect flagged cases. Semantic near-duplicates require an additional human or corpus-specific audit.

For unassigned data, `--assign-splits` hashes whole components into train/calibration/test with fractions 0.6/0.2/0.2 and the specified seed. Assignment ignores labels and row ordering. Explicit splits are preserved and propagated within a component. It does not rebalance by label or guarantee nonempty splits; small datasets may require a separately declared grouping/split design. IDs identify component membership, so renaming IDs changes automatic assignments. Once frozen, preserve IDs and the manifest. Do not select the seed or grouping after inspecting test performance.

The detector receives only `prompt` and `response`. IDs, labels, groups, split tags, and family tags are held outside its review API. The harness cannot remove leakage already embedded in supplied text, or prevent a caller from changing prompts or tuning externally after seeing results.

## Comparison, uncertainty, and frozen artifacts

The JSON report contains paired precision, recall, F1, confusion counts, metric differences, changed predictions (0→1 and 1→0), corrections, and regressions. Undefined precision/recall/F1 denominators use the explicit convention zero. Per-example JSONL contains both scores, both predictions, labels, statuses, split, and component IDs for audit.

Uncertainty is a paired provenance-group percentile bootstrap. Each replicate samples the same number of components with replacement, includes all rows of each drawn component, and uses exactly those rows for both systems. Intervals are the 2.5th and 97.5th percentiles of paired metric differences. This is a cluster bootstrap with row-weighted metrics, not an individual-row or unpaired bootstrap. Few independent groups, one-class samples, and deterministic predictions may yield unstable or degenerate intervals. Increasing bootstrap replicates cannot compensate for missing independent groups.

The manifest includes the detached configuration, configuration hash, full dataset-content hash, component/split membership, and manifest hash. The CLI includes hashes of the package's Python source files. Hashes detect later changes; they do not prove when an artifact was frozen, prevent deliberate tuning, or establish the authenticity or independence of the dataset. Keep the report and score file together. For a model runner, record model/version, exact prompt revision, decoding settings, implementation revision, and any retrieval configuration; never put credentials in this configuration.

## Reusable API

All APIs are in `guardian_truth.benchmarking`:

- `Example(...)` stores text, reference label, explicit provenance, split, and computed component. `Score(id, score, status='', fixed_label=None)` holds a finite score in [0, 1]; a fixed label records hard violations or unknown fallbacks that bypass thresholding.
- `load_examples(path)` reads and validates CSV/JSONL. `prepare_examples(examples)` returns `(prepared_examples, duplicate_audit)`.
- `split_examples(examples, seed=0, fractions=(.6,.2,.2))` returns rows with deterministic group assignments.
- `score_examples(examples, detector, use_semantic=False)` calls only `detector.review(prompt, response)` or a two-string callable returning a numeric score. Hard violations fix label 1; when explicitly requested, `Review.semantic_score` supplies a raw model risk score; otherwise unknown fixes label 0. Raw semantic scores are not described as calibrated probabilities. This matches `decision.decide` for finite valid model scores and the default unknown fallback; malformed scores are rejected by evaluation.
- `select_threshold(calibration_examples, calibration_scores)` rejects every non-calibration row, including any mixed test row.
- `paired_comparison(examples, baseline_scores, candidate_scores, baseline_threshold=.5, candidate_threshold=.5, bootstrap_samples=1000, seed=0)` returns metrics, change counts, paired intervals, and limitations. Score IDs must exactly match examples. Feed one declared evaluation split at a time.
- `frozen_manifest(examples, configuration)` returns a detached, content-hashed manifest; `verify_manifest(manifest)` detects edits to its covered contents.
- `run_benchmark(examples, baseline, candidate, configuration=..., calibrate=False, baseline_threshold=.5, candidate_threshold=.5, baseline_use_semantic=False, candidate_use_semantic=False, bootstrap_samples=1000, seed=0)` scores only calibration when requested, freezes the configuration, and then scores test. It returns `manifest`, `report`, `per_example`, `dataset_audit`, and `test_kind`. Train is never scored. Calibration must have been designated explicitly; the function does not invent a calibration set from test rows.

## What the generated cases establish

The generator varies flat/nested schemas, field names, tool names, entity namespaces, and three policy wordings across template families. It pairs valid calls with missing tools (including the same tool newly declared), missing required arguments, invalid field types, invalid enums, role distractors, and wrong-entity provenance. Consistent tool/field renames, open-schema extra keys, optional fields, and benign user distractors provide known-good transformations. All variants of a template remain in one split. Provenance counterfactuals use a clear policy requiring the observed status for the requested entity; a structural baseline can miss those violations, which is an intended coverage measurement.

The templates were authored with knowledge of the detector's input format and mechanism families. They test invariants and controlled coverage, not independent natural language generalization. They do not cover all ambiguous policies, dialogue forms, multilingual phrasing, contradictory observations, or adversarial inputs. A credible natural evaluation still requires newly acquired examples, trustworthy reference adjudication, provenance-disjoint held-out groups, a configuration frozen before inspection, sufficient independent groups, and reporting uncertainty and errors rather than just a single F1 value.
