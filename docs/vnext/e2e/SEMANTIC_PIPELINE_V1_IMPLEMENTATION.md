# Semantic Pipeline V1

## Boundary and data flow

Semantic Pipeline V1 is a feature-flagged semantic frontend. It does not alter
Guardian's evidence ledger, world generation, solver, certificates, certificate
checker, UNKNOWN semantics, or completion invariants. The bridge lowers only
RuleIR constructs that the existing core can represent losslessly; richer or
ambiguous meanings remain explicitly unresolved.

`prompt + response -> lossless timeline -> recall retrieval -> independent
extractors -> RuleIR -> NLI evidence -> binding alternatives -> Phi ->
conservative bridge -> existing proof core`

Gold labels are split from immutable inference records before any stage runs.
They are used only for post-inference metrics.

## Real model contracts

NuExtract uses `numind/NuExtract3-W4A16` through `AutoProcessor` and
`AutoModelForImageTextToText`. The NuExtract-native template is serialized with
`json.dumps(...)` and passed as the `template` chat-template argument with
`enable_thinking=False`. It requests an exact `source_quote`. Python then finds
the quote in the fragment and creates half-open offsets. Zero matches and
multiple matches are unresolved; the pipeline never chooses an occurrence by
score or by accident.

The generic `actions[].object` field is not treated as `RuleTerm.value` and is
not assumed to be an entity reference. Its type is not known from that slot, so
V1 preserves it as `unbound-action-object:<text>` and leaves the candidate
unresolved. This prevents renderings such as `close equals "the account"` and
prevents an unjustified entity binding.

GLiNER2.5 is not imported by the Guardian process. A one-shot JSON subprocess
uses `/mnt/data/guardian/gliner2_env/bin/python`, imports
`gliner2.AutoExtractor`, loads `fastino/gliner2.5-multi-v1` with
`map_location="cuda", quantize=True`, and performs entity and relation
extraction. This keeps its Transformers 4.x environment isolated from the main
Transformers 5.16.1 environment. A6/A8 attempt this real sidecar and record
`EXECUTED`, `UNAVAILABLE`, or `FAILED` explicitly.

Sidecar JSON is normalized into independent `RuleCandidate` hypotheses before
NLI and binding. `requires`, `prohibits`, and `allows` preserve their literal
modalities, but their endpoint roles remain unresolved and therefore cannot be
losslessly lowered into a proof-core policy rule. Temporal and conditional
relations with no known modality remain UNKNOWN/unresolved. Entity-only
detections are also UNKNOWN. Confidence is retained in `gliner_evidence.json`
but never votes, ranks, or collapses Phi. Both raw evidence and normalized
candidates are persisted; the core sees unsupported candidates as bridge
unresolved rather than silently treating them as proof.

LangExtract 1.7 is an LLM extraction orchestrator, not a local checkpoint.
Installing the package alone is not execution. Because V1 has no configured
LangExtract model-provider plugin, A7/A8 record
`UNAVAILABLE: MODEL_PROVIDER_NOT_CONFIGURED`; they never report a successful
no-op. A7/A8 are therefore `diagnostic-only`, are excluded from post-inference
quality metrics, and do not participate in candidates or Phi. A future
provider-backed integration needs a separately tested grounding-only contract
before it can be enabled.

## Stage-major lifecycle

The runner prepares every active case, then processes the complete batch one
checkpoint at a time:

1. BGE-M3 retrieval (one load for all retrieval cache misses)
2. remote Mistral extraction, when selected
3. NuExtract (one load)
4. optional isolated GLiNER2 sidecar (one load in the worker)
5. NLI DeBERTa (one load)
6. BGE-M3 binding (one load)
7. BGE reranker (one load)
8. Phi and unchanged Guardian proof core

Each local model is unloaded before the next model is loaded. `timings.json`
contains per-stage timing, lifecycle records, `stage_load_counts`, and
`model_load_counts`. The same counts are copied into `run_manifest.json`, so a
limit-3/5 smoke run can mechanically demonstrate one load per stage regardless
of case count. BGE-M3 intentionally has two total loads because retrieval and
binding are separated by the larger NuExtract and NLI stages; each BGE stage
still loads it exactly once.

The Hugging Face cache and Guardian stage cache are separate:

- Hugging Face files: `/mnt/data/guardian/hf_cache` (hub subdirectory under it)
- Guardian content-addressed results: `--cache-dir` or
  `<output>/.guardian-cache/semantic-v1`

`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are supported and recorded in
`environment.json`.

## Independent ablations

- A0: current Guardian frontend; Mistral core backend.
- A1: Mistral RuleIR frontend only.
- A2: NuExtract RuleIR frontend only. No Mistral client is created. Since the
  existing core still needs a semantic backend for other frontend tasks, core
  status is honestly `UNRESOLVED` with `CORE_SEMANTIC_BACKEND_NOT_CONFIGURED`.
- A3: Mistral + NuExtract to Phi.
- A4: A3 + NLI.
- A5: A4 + BGE binding/reranking (default; no GLiNER/LangExtract).
- A6: A5 + real GLiNER2 candidate source. It is quality-eligible only when the
  sidecar actually reports `EXECUTED`.
- A7: diagnostic-only LangExtract availability request; no quality metrics.
- A8: diagnostic-only A6 + LangExtract availability request; use A6, not A8,
  for the GLiNER2 quality comparison.

Mistral frontend extraction and the core semantic backend are separate config
dimensions. There is no hidden fallback provider.

## ModelScope A10 setup and smoke sequence

Do not reinstall or modify torch, CUDA, or the preconfigured main environment.
From the repository root:

```bash
source /mnt/data/guardian/venv/bin/activate
export HF_HOME=/mnt/data/guardian/hf_cache
export HUGGINGFACE_HUB_CACHE=/mnt/data/guardian/hf_cache/hub
export GUARDIAN_GLINER2_PYTHON=/mnt/data/guardian/gliner2_env/bin/python
export GUARDIAN_SEMANTIC_CACHE=/mnt/data/guardian/cache/semantic-v1

# The target environment already contains the verified dependencies.
python -m pip install -e . --no-deps
python -c 'import torch,transformers,peft,sentence_transformers,compressed_tensors; print(torch.__version__, transformers.__version__, torch.cuda.get_device_name(0))'

pytest -q tests/semantic_pipeline_v1
python scripts/run_semantic_pipeline_v1.py \
  --input-file valid.parquet --output-dir outputs/semantic-v1-dry \
  --ablation A5 --limit 1 --dry-run --no-resume

# Real one-case A5.
python scripts/run_semantic_pipeline_v1.py \
  --input-file valid.parquet --output-dir outputs/semantic-v1-a5-one \
  --ablation A5 --limit 1 --cache-dir "$GUARDIAN_SEMANTIC_CACHE" --resume

# Multi-case lifecycle proof. Inspect model_load_counts in timings.json.
python scripts/run_semantic_pipeline_v1.py \
  --input-file valid.parquet --output-dir outputs/semantic-v1-a5-five \
  --ablation A5 --limit 5 --cache-dir "$GUARDIAN_SEMANTIC_CACHE" --resume
python -c 'import json; x=json.load(open("outputs/semantic-v1-a5-five/timings.json")); print(x["stage_load_counts"]); print(x["model_load_counts"])'

# Direct offline checkpoint smoke; this makes no Mistral call.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python scripts/preload_semantic_models_v1.py \
  --models embedding nuextract nli reranker --device cuda

# Pipeline smoke with HF offline. Mistral is still remote and is unrelated to HF.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python scripts/run_semantic_pipeline_v1.py \
  --input-file valid.parquet --output-dir outputs/semantic-v1-a5-offline \
  --ablation A5 --limit 1 --device cuda \
  --cache-dir "$GUARDIAN_SEMANTIC_CACHE" --resume

# GLiNER2 smoke in the isolated environment; does not import it in the main venv.
python scripts/preload_semantic_models_v1.py --models gliner --device cuda \
  --gliner-python /mnt/data/guardian/gliner2_env/bin/python

# A6 uses the same real sidecar in the pipeline.
python scripts/run_semantic_pipeline_v1.py \
  --input-file valid.parquet --output-dir outputs/semantic-v1-a6-one \
  --ablation A6 --limit 1 --device cuda \
  --gliner-python /mnt/data/guardian/gliner2_env/bin/python \
  --cache-dir "$GUARDIAN_SEMANTIC_CACHE" --resume
```

`MISTRAL_API_KEY` and `MISTRAL_MODEL` are read from `.env` or the environment.
No secret value is written to run artifacts.

## Artifacts and resume

Every run writes `run_manifest.json`, `environment.json`, `config.json`,
`predictions.csv`, `metrics.json`, and `timings.json`. Each case contains source
segments, retrieval, independent extractor outputs, raw GLiNER evidence,
normalized GLiNER candidates, component statuses, NLI, binding candidates, Phi,
core result, and a readable summary. Cache keys include
content, checkpoint, relevant config, and schema/template version—never labels.
Completed-case seals preserve resume behavior.

## Known limits

The core bridge currently lowers only exact action-level modalities with simple
conjunctions. Comparisons, cardinality, rich temporal rules, claims, and
state/effect targets remain unresolved rather than weakened. Windows CI cannot
validate CUDA, cached checkpoints, or the separate Linux sidecar; the real A10
commands above must be run on ModelScope and their artifacts retained before
claiming successful GPU execution.
