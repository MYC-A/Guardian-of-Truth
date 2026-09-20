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
  bidirectional cross-provider critiques and an own-author repair for each
  original, then retains all four readings. Every critique issue carries an
  exact original-policy quote/offset and a typed problem such as
  `missing_condition`, `wrong_modality`, or `invented_requirement`.

The dedicated pilot runner accepts exactly 3--5 cases. It checks that neither
repair deletes a parent element, changes an uncriticised element, or drops a
clause account. It stores originals, critiques, repairs, unresolved questions,
parent links, semantic diffs, and raw pre-normalization responses with hashes.
Raw output is redacted for key values; normalized RuleCandidate wire is never
labelled as raw.

Generate the real mutual critique and repair artifacts first. This runner
calls Mistral to critique the NuExtract original and NuExtract with a dedicated
JSON extraction template to critique the Mistral original. Each author then
receives the grounded cross-critique and emits a patch for its own parent.
The deterministic repair builder retains every parent element and ID, accepts
changes only for exactly grounded critique targets, and marks additions as
`MODEL_PROPOSED_ADDITION`.

```text
python -m experiments.architectures_v2.b_theory.mutual_model_runner \
  --input pilot_cases.jsonl \
  --original-output mistral=mistral.jsonl \
  --original-output nuextract=nuextract.jsonl \
  --output-dir outputs/b3_model
```

The output directory contains `critiques.jsonl`, provider-specific repair
JSONL files, and the append-only `model_cycle.jsonl`. Every model operation
stores the model and dependency IDs, latency, raw pre-normalization response,
hash, and error. If NuExtract cannot satisfy the critique or repair template,
the record says `CAPABILITY_FAILURE`; no substitute critique or repair is
created and the cycle remains one-sided.

```text
python -m experiments.architectures_v2.b_theory.run_b3_cycle \
  --input pilot_cases.jsonl \
  --original-output mistral=mistral.jsonl \
  --original-output nuextract=nuextract.jsonl \
  --critique-output critiques.jsonl \
  --repair-output mistral=mistral_repairs.jsonl \
  --repair-output nuextract=nuextract_repairs.jsonl \
  --gap-evidence langextract_gaps.jsonl --output-dir outputs/b3
```

LangExtract also has a direct-original mode. It does not see either theory and
does not repair them. Its output separates exact quote validity from unverified
interpretation, relation correctness, and completeness. Because this adapter
uses Mistral, every row carries
`LANGEXTRACT_DEPENDS_ON_MISTRAL_BACKEND` and is not counted as independent.

```text
python -m experiments.architectures_v2.b_theory.run_langextract_grounding \
  --mode direct-original --input pilot_cases.jsonl \
  --output langextract_gaps.jsonl
```

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
existing Full Architecture `run_arm(..., "N5")`. Every original and repair is
submitted as a separate alternative. The result retains concrete per-rule
binding reasons, boundary losses, lowering markers, and checker failures.
Alternatives are never unioned.
