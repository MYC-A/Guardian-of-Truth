# Model/API audit

Audit timestamp: `2026-09-11T21:37:39.1132048+03:00`  
Catalog snapshot: `2026-09-11T21:35:40.5881250+03:00`

This is a connectivity, capability, and role-smoke audit. It is not an accuracy benchmark and does not justify choosing an end-to-end winner. The exact machine-readable observations are in `outputs/next/model_manifest.json` and `outputs/next/model_role_benchmark.json`.

No credential value, length, or fingerprint was printed or recorded. The probes sent only synthetic policy, trace, and claim text. No validation rows, target labels, or gold explanations were sent.

## Decision

Use Groq `openai/gpt-oss-120b` as the first frozen remote model. It was the only configured model that combined strict structured-output support, stable transport, complete success on all four role probes, controllable reasoning, and predictable per-token pricing.

Use OpenRouter `nex-agi/nex-n2.5-mini:free` only as a zero-cost comparison or fallback. It passed all four probes, but free-model availability and rate limits are not production-stable. Do not freeze the currently configured `google/gemma-4-31b-it:free`: it returned HTTP 429 on every generation attempt.

Use Gemini `gemini-3-flash-preview` only as a strong experimental policy arm until reliability is measured on a larger repeated sample. It was much slower and returned two server errors in four identical role probes. Gemini also needs an explicit model setting; the current environment does not provide one.

Mistral and Cerebras are implemented as isolated provider profiles, but neither is admitted to an evaluation arm in this cycle. Mistral authenticated for model discovery and then returned rate-limit errors for every role and policy request. Cerebras rejected model discovery and its bounded chat probes; this is recorded as unavailability, not model-quality evidence.

NVIDIA NIM is also implemented, but the tested hosted routes fail the reliability/latency gate. DeepSeek V4 Flash and Kimi K3 each completed only two of four role tasks; Gemma 4 31B completed none. Keep NVIDIA as an optional slow-path research provider, not the default runtime.

The local backend is not currently runnable: no compatible endpoint is listening and no NVIDIA/CUDA device was detected.

## Credential and configuration audit

The new worktree had none of the provider variables in its process environment and had no local `.env`. An ignored env file in the original worktree contained usable values under the following names:

- `GROQ_API_KEY`
- `OPENROUTE_API_KEY`
- `GEMENI_API_KEY`
- `GUARDIAN_MODEL`
- `GUARDIAN_BASE_URL`
- `OPENROUTE_MODEL`

The `OPENROUTE_*` and `GEMENI_*` misspellings are accepted by the current alias logic. The later environment also contains lowercase `mistral_api_key` and `cerebras_api_key`; both lowercase names and their conventional uppercase aliases are now accepted. Each profile is pinned to its own hostname and credential. Secret values, lengths, and fingerprints remain absent from every artifact.

A separate ignored `.env` contained `GROQ_API_KEY`, but that value contained non-ASCII characters. The client rejects such a credential before network access. The usable Groq credential came from the other ignored env file.

The most important configuration bug is the missing Gemini model. `provider_config()` falls back to global `GUARDIAN_MODEL`; in this environment that is `openai/gpt-oss-120b`, which is not a Gemini model. Any Gemini benchmark must freeze `--model` or set `GEMINI_MODEL`/`GEMENI_MODEL` explicitly.

## Frozen role probes

The frozen suite contains four synthetic tasks:

1. Policy extraction without a trace.
2. Pairwise discrimination between a proposal and an unsupported completion claim.
3. Claim extraction when no execution evidence exists.
4. Local event/policy classification for an explicitly failed action.

The canonical suite hash is:

```text
sha256:ab1be6f7561a3d41ab1723f0386ac51e93db34125e33cc6ad454c9761b62b612
```

Canonicalization is UTF-8 JSON with sorted keys, compact separators, and ASCII escaping. Request settings are stored per arm and excluded from this content hash. All calls used temperature 0, non-streaming output, no retries, a 60-second timeout, and an object schema containing an enum answer plus a reason.

| Provider/model | Success | Correct | Mean successful latency | Observed p95 | Main error |
|---|---:|---:|---:|---:|---|
| Groq `openai/gpt-oss-120b` | 4/4 | 4/4 | 1797.9 ms | 2715.1 ms | none |
| OpenRouter `google/gemma-4-31b-it:free` | 0/4 | 0/4 | n/a | n/a | 4× rate limit |
| OpenRouter `nex-agi/nex-n2.5-mini:free` | 4/4 | 4/4 | 1746.8 ms | 2074.3 ms | none |
| Gemini `gemini-3-flash-preview` | 2/4 | 2/4 attempted successes | 12114.0 ms | 12507.6 ms | 2× server error |
| Mistral `mistral-small-latest` | 0/4 | 0/4 | n/a | n/a | 4× rate limit |
| Cerebras `gpt-oss-120b` | 0/4 | 0/4 | n/a | n/a | 4× request rejection |
| NVIDIA `deepseek-ai/deepseek-v4-flash-0731` | 2/4 | 2/4 attempted successes | 8756.7 ms | 9212.7 ms | 2× timeout |
| NVIDIA `google/gemma-4-31b-it` | 0/4 | 0/4 | n/a | n/a | 4× timeout |
| NVIDIA `moonshotai/kimi-k3` | 2/4 | 2/4 attempted successes | 47244.3 ms | 52975.8 ms | 2× timeout |

The p95 values use nearest-rank over at most four observations. They describe this smoke run only and must not be treated as an SLO estimate.

### Reasoning control smoke

Groq accepted both `low` and `high`; reasoning-token use increased from 20 to 229 in the tested example, and both answers were correct. Gemini accepted `low`. The OpenRouter candidate accepted both settings, but its nested usage accounting was internally inconsistent: reported reasoning tokens exceeded reported completion tokens. The system should normalize usage defensively and should never assume nested provider counters sum cleanly.

## Provider findings

### Groq

Observed from `/models`:

- HTTP 200, 14 models, 7769.1 ms catalog latency.
- `openai/gpt-oss-120b` active.
- 131072-token context and 65536-token maximum output.
- Text input/output.
- Catalog advertises tools, JSON mode, structured outputs, and reasoning.

Observed from generation:

- Four of four schema calls succeeded and returned the expected enum.
- Total role-suite usage: 948 prompt, 766 completion, 1714 total tokens.
- Estimated role-suite cost: approximately `$0.0006018`, based on catalog prices and excluding cache effects.
- One later response exposed a dynamic snapshot of 1000 request limit / 997 remaining and 8000 token limit / 7616 remaining. These values are account- and time-dependent, so the manifest marks them as observations rather than contracts.

Documented by Groq:

- Input `$0.15/M`, cached input `$0.075/M`, output `$0.60/M`.
- Free-plan baseline for this model: 30 RPM, 1000 RPD, 8000 TPM, 200000 TPD. Exact organization limits may differ.
- Strict JSON Schema and low/medium/high reasoning effort are supported.

Sources: [model](https://console.groq.com/docs/model/openai/gpt-oss-120b), [rate limits](https://console.groq.com/docs/rate-limits), [structured outputs](https://console.groq.com/docs/structured-outputs), [reasoning](https://console.groq.com/docs/reasoning).

### OpenRouter

Observed from `/models`:

- HTTP 200, 443 total models, 19 free models, 9430.0 ms catalog latency.
- Configured Gemma exists and advertises a 262144-token context, 32768 maximum completion, and `response_format`, but not the distinct `structured_outputs` capability flag.
- `nex-agi/nex-n2.5-mini:free` advertises a 262144-token context, 235929 maximum completion, `response_format`, `structured_outputs`, and reasoning controls.

Observed from generation:

- Configured Gemma returned rate-limit errors on all four attempts.
- Nex-N2.5-Mini passed all four cases and reported zero cost.
- Free-model capacity is model-specific: the same credential could call Nex while Gemma remained rate-limited.

Documented by OpenRouter:

- Free models have a shared 50 requests/day limit unless at least `$10` of credits has been purchased, in which case it is 1000/day.
- Structured output support is model- and route-dependent. A production implementation should require the parameter through routing preferences rather than trusting generic OpenAI compatibility.

Sources: [FAQ and free limits](https://openrouter.ai/docs/faq), [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [model metadata fields](https://openrouter.ai/docs/guides/overview/models), [Nex free model](https://openrouter.ai/nex-agi/nex-n2.5-mini%3Afree).

### Gemini

Observed from `/models`:

- HTTP 200, 55 models, 10132.6 ms catalog latency.
- The credential is valid for catalog access.

Observed from generation:

- `gemini-2.5-flash` and `gemini-2.5-flash-lite` returned HTTP 404 despite catalog presence.
- `gemini-3-flash-preview` generated both JSON-object and schema responses.
- Only two of four Guardian schema calls succeeded; the other two returned retryable server errors.
- Successful calls took 11.72–12.51 seconds.
- `reasoning_effort=low` was accepted in a separate smoke call.

Documented by Google:

- Gemini 3 Flash Preview has a 1M input context and up to 64K output.
- Paid pricing is `$0.50/M` input and `$3/M` output including thinking tokens. Actual cost cannot be inferred because the credential's billing tier was not queried.
- OpenAI-compatible reasoning effort is mapped to Gemini thinking controls.
- Structured output supports only a subset of JSON Schema; very large or deeply nested schemas can be rejected.
- Quotas depend on project, model, and tier, and preview models are generally more restricted. Exact active quotas must be read in AI Studio.

Sources: [OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai), [Gemini 3](https://ai.google.dev/gemini-api/docs/gemini-3), [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [structured output](https://ai.google.dev/gemini-api/docs/structured-output), [pricing](https://ai.google.dev/gemini-api/docs/pricing).

### Mistral

Observed:

- Model discovery returned HTTP 200 and included `mistral-small-latest`.
- All four frozen role probes returned `rate_limit` before a schema-valid answer.
- In a one-case policy-semantics run with matched P1/P2 budgets, P1, P2, and P3 all returned `rate_limit`.
- These failures measure current account capacity only. They are not zero semantic scores for the model.

The implementation uses Mistral's OpenAI-compatible `https://api.mistral.ai/v1` endpoint and its documented `max_tokens` request field. Sources: [API reference](https://docs.mistral.ai/api), [structured output](https://docs.mistral.ai/studio/conversations/structured-output/custom).

### Cerebras

Observed:

- Model discovery returned HTTP 403.
- All four frozen role probes were rejected before a valid structured response.
- In a one-case policy-semantics run with matched P1/P2 budgets, P1, P2, and P3 were rejected at the request layer.
- This is a transport/request result, not a semantic model failure.

The profile uses the documented `https://api.cerebras.ai/v1` endpoint and defaults to `gpt-oss-120b`. Sources: [chat completions](https://inference-docs.cerebras.ai/api-reference/chat-completions), [public models](https://inference-docs.cerebras.ai/api-reference/models/public-models), [rate limits](https://inference-docs.cerebras.ai/support/rate-limits).

### NVIDIA NIM

Observed with three separate user-provided NVIDIA credentials and exactly four attempts per model, no retries, 60-second timeout:

- `deepseek-ai/deepseek-v4-flash-0731`: two correct schema-valid responses in 8.30–9.21 seconds, then two timeouts.
- `google/gemma-4-31b-it`: four timeouts.
- `moonshotai/kimi-k3`: two timeouts followed by two correct schema-valid responses in 41.51–52.98 seconds.
- The `openai/gpt-oss-20b` credential was not benchmarked after its value was exposed by a local diagnostic exception; it must be rotated first.

All successful responses passed the same local enum/schema contract used for other providers. The implementation uses NVIDIA's documented OpenAI-compatible `https://integrate.api.nvidia.com/v1/chat/completions` route and `max_tokens` field. Source: [NVIDIA NIM LLM API reference](https://docs.api.nvidia.com/nim/re/reference/llm-apis).

## Local endpoint and hardware

Observed:

- Default `http://127.0.0.1:8000/v1/models` was unreachable.
- No relevant listener was found on ports 8000, 8080, 11434, 1234, or 5000.
- `nvidia-smi` was unavailable.
- Windows reported only `AMD Radeon (TM) Graphics`, with 512 MiB adapter memory reported by WMI.

Inference: standard CUDA local inference is not currently available. This does not rule out a future CPU or AMD-compatible backend, but no such server was running during the audit.

The runtime's local security boundary is sound: only loopback hosts are accepted and a local API key may be omitted.

## Client limitations affecting experiments

The current client has useful safeguards: endpoint validation, remote host pinning in provider profiles, request-time credential lookup, no redirects, bounded response bodies, fixed temperature 0, bounded retries, and sanitized public errors.

The following gaps should be fixed before a large model experiment:

- Local response validation proves only that content is a JSON object; it does not independently validate the supplied JSON Schema.
- Error bodies are intentionally discarded, which is safe but makes provider incompatibilities difficult to diagnose. Record sanitized provider error code/type separately.
- Latency, attempt count, rate-limit headers, requested/returned model, normalized usage, and estimated cost are not first-class transport records.
- Provider request capabilities should live in an explicit registry. The current code handles the documented Mistral/OpenRouter `max_tokens` difference, but other request-shape differences are still encoded as conditionals.
- Retry uses bounded delay but no jitter.
- OpenRouter free-model usage fields cannot be trusted without normalization.
- A catalog listing is not proof that generation is available; the Gemini 2.5 and configured OpenRouter results demonstrate this directly.

## Freeze recommendation

For the first controlled policy/compiler experiments:

1. Freeze Groq `openai/gpt-oss-120b` as P1/P2/P5 unless a pre-run repeat probe fails.
2. Use identical prompts, schema, temperature, reasoning effort, max output, and retry policy for paired arms.
3. Cache policy compilation by policy hash so later trace evaluation does not spend additional policy tokens.
4. Keep `nex-agi/nex-n2.5-mini:free` as a non-production comparison, not a guaranteed fallback.
5. Admit Gemini only to a separately labeled strong/experimental arm with retry/error metrics included in the result.
6. Repeat the frozen role suite before the first blind run, then freeze the returned model identifiers and do not substitute a provider/model after seeing labels.
