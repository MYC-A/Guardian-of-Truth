# Controlled Architecture B boundary

This package compares independent theory candidates without changing the
existing RuleIR, binder, compiler, or Clingo implementation.

Model execution remains in the verified adapters under
`src/guardian_truth/semantic_pipeline_v1/models/`. Their saved
`RuleCandidate` wire objects are wrapped as theory elements:

```json
{"candidate_id":"theory-m0","provider":"mistral","elements":[{"wire_candidate":{"candidate_id":"...","rule":{},"source_spans":[]}}]}
```

`adapters.py` also provides injectable protocols for live providers, an
optional LangExtract source grounder (including an OpenAI-compatible model
instance), and targeted reviewers. Tests use fakes and make no model calls.

Real donor extraction uses one append-only batch runner. NuExtract is loaded
once for all cases; GLiNER runs once in its isolated sidecar and its outputs
are marked evidence-only:

```text
python -m experiments.architectures_v2.b_theory.provider_runner \
  --input cases.jsonl --output provider_outputs.jsonl \
  --provider mistral --provider nuextract --provider gliner
```

The Mistral API key is read only from `MISTRAL_API_KEY`; the runner enforces
`ministral-14b-latest` and never serializes the key. The optional
`MistralLangExtractGrounder` explicitly constructs LangExtract 1.7's
`OpenAILanguageModel` with the Mistral OpenAI-compatible base URL. Its spans
still pass the same exact quote/offset validator.

```text
python -m experiments.architectures_v2.b_theory.run_langextract_grounding \
  --input cases.jsonl --provider-output provider_outputs.jsonl \
  --output grounded_provider_outputs.jsonl
```

The input case JSONL supplies exact source documents and a clause registry.
Clause boundaries must come from document structure or a separately recorded
segmenter; this package deliberately contains no semantic regex segmenter.
For segment-local donor offsets, set `document_start` (or donor
`start_char`) on the source record; the FullArch handoff is rebased to the
whole prompt/response coordinates.

Variants:

* `b0_independent_theories` retains every provider theory independently.
* `b1_source_grounded` requires exact quote and offset checks.
* `b2_clause_coverage` adds the closed ledger states `accounted_for`,
  `non_policy_with_reason`, and `unresolved`.
* `b3_mutual_repair` accepts separately generated repair candidates, requires
  an independent provider and a parent reference, then retains both readings.

Example:

```text
python -m experiments.architectures_v2.b_theory.run_b_theory \
  --input cases.jsonl \
  --variant b2_clause_coverage \
  --provider-output mistral=mistral_candidates.jsonl \
  --provider-output nuextract=nuextract_candidates.jsonl \
  --output-dir outputs/b2_run
```

`BINDING_REQUIRED` is the strongest boundary status. It means a hypothesis is
structurally valid and exactly attributed. The existing binder must still
produce binding resolutions before the existing Full Architecture
`compile_rule_set` and Clingo stages can run. `UNREPRESENTABLE` and `REJECTED`
are explicit and are never silently dropped.

After a B variant has produced `records.jsonl`, run every whole theory as a
separate N5 alternative over the original label-free input:

```text
python -m experiments.architectures_v2.b_theory.formal_handoff \
  --input input.csv --b-records outputs/b2_run/records.jsonl \
  --output outputs/b2_run/n5_alternatives.jsonl
```

The handoff constructs only exact catalog identity bindings and calls the
existing Full Architecture `run_arm(..., "N5")`. It logs representability,
exact binding count, compiler markers, Clingo status, and certificate checker
results. Alternatives are never unioned.
