# Model Reliability Gate

Cycle 2 separates provider reliability from semantic quality before any P1/P2/P3
comparison. The current frozen gate contract is
`contracts/cycle2_model_gate_v2.json`. Version 2 keeps the same cases and
admission thresholds, embeds the exact JSON shape and answer vocabulary in the
system message, and omits the provider-side `response_format` extension.

## Predeclared protocol

- 16 independent structured-output calls per provider/model;
- six Guardian task families and one identical JSON schema for every call;
- temperature `0`, reasoning effort `low`, 512 output tokens;
- 180-second per-call timeout, five-second pacing, zero hidden retries;
- no policy-benchmark gold or expected gate answer enters a model prompt.

The zero-retry policy is intentional: every logical case is exactly one HTTP
attempt, so a 429 cannot disappear inside a successful retry. A later benchmark
may use a different frozen retry policy, but it must report each HTTP attempt.

Admission requires all of the following:

- at least 16 attempts;
- transport success / attempted ≥ 0.90;
- schema-valid / attempted ≥ 0.90;
- rate-limit, timeout, and 5xx ratios each ≤ 0.10;
- no more than one consecutive 429.

Semantic correctness on the micro-tasks is reported but is not an admission
threshold. It is not a substitute for the larger behavioral policy benchmark.

Every case has exactly one of four outcomes:

```text
TRANSPORT_ERROR
SCHEMA_ERROR
SEMANTIC_WRONG
SEMANTIC_CORRECT
```

The report publishes reliability (`schema_valid / attempted`), conditional
semantic quality (`correct / schema_valid`), and strict operational yield
(`correct / attempted`) separately.

## Credential boundary

The command requires an explicit ignored env file. It serializes no credential
value. TokenHarbor and NVIDIA are refused unless the operator explicitly attests
that the credential was rotated after the Cycle 1 exposure; the exposed values
must never be reused.

Example (does not run until invoked explicitly):

```powershell
python -m guardian_truth.cycle2.evaluate model-gate `
  --candidate groq=openai/gpt-oss-120b `
  --candidate openrouter=nex-agi/nex-n2.5-mini:free `
  --env-file .env
```

The machine-readable result is `outputs/cycle2/model_gate.json`. If no candidate
passes, its status is `EVALUATION_BLOCKED_BY_PROVIDER` and the P1/P2/P3 runner
must refuse to start.

## Observed Cycle 2 run

The frozen gate was executed without changing its schema or thresholds:

| Provider/model | Attempts | Transport | Schema-valid | Semantic evaluated | Result |
|---|---:|---:|---:|---:|---|
| Groq / `openai/gpt-oss-120b` | 0 | 0 | 0 | 0 | local `INVALID_API_KEY`; not an available candidate |
| TokenHarbor / `deepseek-v4-flash:free`, v1 | 16 | 0 | 0 | 0 | all 16 calls were sanitized `http_request` rejections |
| TokenHarbor / `deepseek-v4-flash:free`, v2 first run | 16 | 1 | 1 | 1 correct | 15 sanitized `http_request` rejections; not admitted |

The v2 success proves that schema-in-prompt parsing works. The other outcomes
remain transport failures, not semantic errors. A subsequent two-case diagnostic
using the unchanged v2 payload returned HTTP 200 for both a previously rejected
case and the previously successful case. This is evidence of transient route
availability, but it does not retroactively admit the provider. The complete v2
gate is repeated without changing cases, prompts, thresholds, or generation
settings, and every observed run remains visible in Git history.

The rotated credential value is never serialized. This first v2 result remained
`EVALUATION_BLOCKED_BY_PROVIDER`; it did not itself authorize model arms.

## Admission result

The unchanged v2 contract was then repeated sequentially after the two-case
route diagnostic. TokenHarbor completed 16/16 transports, produced 16/16
schema-valid objects, and answered 14/16 semantic micro-tasks correctly.
Reliability is therefore `1.0`, conditional semantic quality is `0.875`, and
strict operational yield is `0.875`; median latency was 6159 ms and p95 was
34214 ms. `deepseek-v4-flash:free` is admitted for P1/P2. Groq remains locally
unavailable and was not called. This admission does not establish P3 because no
second stronger/reasoning candidate passed the same gate.
