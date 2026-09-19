# AgentHallu v1 freeze and DEV adapter

This adapter creates a deterministic question-grouped split of the AgentHallu
dataset and a label-free DEV input for Guardian experiments. AgentHallu is by
Liu et al., *AgentHallu: Benchmarking Automated Hallucination Attribution of
LLM-based Agents* (2026), source
<https://github.com/liuxuannan/AgentHallu>, and is distributed under CC BY 4.0.
Keep this attribution with derived benchmark artifacts.

## Commands

```powershell
python -m benchmarks.agenthallu_v1.agenthallu_v1 freeze `
  --source-repo outputs/external_sources/AgentHallu `
  --output-manifest benchmarks/agenthallu_v1/frozen_manifest.json

python -m benchmarks.agenthallu_v1.agenthallu_v1 adapt-dev `
  --source-repo outputs/external_sources/AgentHallu `
  --manifest benchmarks/agenthallu_v1/frozen_manifest.json `
  --output-dir benchmarks/agenthallu_v1/dev
```

Both outputs are immutable: the commands fail if their destination already
exists. `adapt-dev` filters the manifest before opening source samples and
never reads LOCKED files.

## Contracts

Question grouping uses SHA-256 of the normalized question. Strings are used as
text; every other JSON value is serialized with sorted keys and compact
separators. The result is NFC normalized, stripped, and whitespace collapsed.
Hashes whose first eight hex digits modulo 10 are below 3 are LOCKED.

`input.csv` contains only `id,prompt,response`. Prompt holds the original task
and the fixed `agent_trajectory_v1` format tag. Response holds the raw history
under `events`; event order, JSON types, nulls, tool calls, and tool responses
are preserved. Labels and source metadata are stored outside model input.

`gold_binary.csv` supports trajectory-level hallucination classification.
`localization_gold.jsonl` supports attribution of the first annotated source
step. `event_ordinal` is zero-based and is emitted only when the annotated step
matches exactly one history event. Missing or duplicate matches remain
`UNMAPPABLE` or `AMBIGUOUS`. Negative cases use `NOT_APPLICABLE` and receive no
pseudo-step.

These metrics measure detection and first-step localization on AgentHallu DEV.
They do not measure Guardian's formal proof soundness and must not be presented
as hidden competition performance. LOCKED labels and trajectories stay sealed
until a separately authorized one-time evaluation.
