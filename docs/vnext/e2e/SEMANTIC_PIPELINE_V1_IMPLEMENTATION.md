# Semantic Pipeline V1 implementation

## Boundary

Semantic Pipeline V1 is a feature-flagged frontend alongside Guardian's existing frontend. It does not change the evidence ledger, provenance records, world generation, solver, certificates, certificate checker, UNKNOWN semantics, or completion invariants. The thin adapter lowers only RuleIR constructs that the existing `PolicyReading` space can represent exactly. Anything richer remains explicitly unresolved.

## Data flow

`prompt + target response → lossless timeline → recall retrieval → independent Mistral/NuExtract candidates → RuleIR → deterministic rendering → NLI evidence → tool/field/entity binding → SemanticInterpretationSet (Φ) → conservative adapter → existing Guardian core`

The default is A5: Mistral + NuExtract3-W4A16 + BGE-M3 retrieval + NLI DeBERTa + BGE reranker. GLiNER and LangExtract are independent, disabled feature flags.

## Source and timeline

The timeline keeps byte-for-byte prompt and response roots plus structural child segments for roles, calls, results, tool declarations, and schemas. Chronology uses deterministic integer `event_index`; no absent timestamp is invented. Every segment carries document-relative coordinates and exact text. Retrieval coverage marks each structural segment as `ROUTED` or `PRESENT_NOT_ROUTED`, distinguishing absent information from present-but-unrouted information. Extractor unresolved fields distinguish routed-but-lost meaning.

## Recall retrieval

Retrieval is a union of source-class guarantees, exact lexical links, target tool/schema links, knowledge/document result guarantees, BGE-M3 top-k, and configurable timeline neighbors. Embeddings only add candidates. Configuration uses top-k and source-class guarantees rather than a threshold tuned to `valid.parquet`.

## Semantic extraction and RuleIR

Mistral receives exact fragments, minimal neighboring context, metadata, and the RuleIR schema. It is asked for interpretations, never a verdict or label. Credentials come from `MISTRAL_API_KEY`; the established lowercase `mistral_api_key` is accepted only when the standard variable is absent, so the standard variable has precedence. An explicit config/`--mistral-model` wins for the model, followed by `MISTRAL_MODEL`, lowercase `mistral_model`, then the default. The project's whitelist-only `.env` loader is reused. There is no remote fallback provider.

NuExtract uses `numind/NuExtract3-W4A16` locally and independently produces candidates in the same RuleIR space before seeing Mistral output. RuleIR is domain-neutral and compositional: modality, subject, ACTION/STATE/CLAIM/INFORMATION/EFFECT targets, boolean trees, IF/ONLY_IF/UNLESS, temporal relations, comparisons, cardinality, values, entity references, unresolved references, and exact source spans.

## NLI and Φ

The deterministic renderer turns the same RuleIR into the same natural-language hypothesis. `cross-encoder/nli-deberta-v3-base` compares the exact source premise with that rendering and stores logits, normalized scores, label, checkpoint, and rendering. NLI is evidence, not formal proof. A strong self-contradiction prevents a candidate from being the sole supported interpretation; NEUTRAL remains uncertain.

Canonical-equal candidates merge extractor provenance. Distinct plausible candidates remain separate members of Φ. There is no majority vote and no highest-score collapse. Each interpretation records RuleIR, source spans/IDs, extractors, NLI evidence, binding alternatives, unresolved components, and digest.

## Binding

Tools and fields use exact names first, then BGE-M3 retrieval and pairwise BGE reranking against names, descriptions, and schemas. Entity candidates come only from exact source literals. Multiple plausible bindings are preserved; embedding and reranker scores never become proof. No keyword-to-tool domain rules exist.

## Optional evidence layers

GLiNER uses the verified `gliner.GLiNER` path and extracts only ACTION/STATE/VALUE/ENTITY/CLAIM-like spans. V1 makes no relation-extraction claim. LangExtract is an optional source-alignment hook and cannot create, delete, or judge semantics. Both are disabled in A5 because measurable benefit has not yet been established.

## Model lifecycle and resume

Large local models are loaded sequentially: BGE retrieval, NuExtract, optional GLiNER, NLI, BGE binding, BGE reranker. After every stage the manager deletes the model, runs garbage collection, empties the CUDA cache, and records load/execution duration plus peak allocated/reserved VRAM. Mistral, embeddings, NuExtract, GLiNER, NLI, and reranking use content-addressed caches keyed by content, checkpoint, model configuration, and schema version—never by a gold label. Completed case markers make `--resume` safe after interruption.

## Gold firewall and artifacts

The loader splits optional labels into a separate map before constructing immutable inference records. Labels are used only to calculate metrics after predictions. Every run writes `run_manifest.json`, `environment.json`, `config.json`, `environment/config.json`, `predictions.csv`, `metrics.json`, and `timings.json`. Each case contains source, retrieval, both extractor outputs, optional GLiNER evidence, NLI, bindings, Φ, core result, and a readable summary. Single-case mode mirrors these under `traces/`.

## Ablations

- A0: current Guardian frontend.
- A1: new source/retrieval + Mistral.
- A2: new source/retrieval + NuExtract.
- A3: Mistral + NuExtract → Φ.
- A4: A3 + NLI.
- A5: A4 + BGE binding/reranking (default).
- A6: A5 + GLiNER.
- A7: A5 + LangExtract.
- A8: A5 + both optional layers.

## Known limitations

V1 deliberately does not solve all remaining false negatives. The thin core adapter currently lowers only exact action-level modalities with simple conjunctions. Comparisons, cardinality, richer temporal rules, claims, and state/effect targets remain unresolved until the proof-core representation can accept them without weakening meaning. Argument provenance remains a separate future subsystem. Actual T4 execution was not performed in the Windows development environment; the user's verified Colab compatibility is treated as authoritative.

## Running

```bash
python scripts/run_semantic_pipeline_v1.py \
  --input-dir /content/guardian_tests \
  --output-dir /content/guardian_outputs \
  --semantic-frontend v1 \
  --ablation A5 \
  --resume
```

The Python API calls the identical implementation:

```python
from guardian_truth.semantic_pipeline_v1 import run_experiment
run_experiment(input_dir="/content/guardian_tests", output_dir="/content/guardian_outputs", resume=True)
```
