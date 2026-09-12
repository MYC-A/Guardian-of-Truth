# Model Reliability Gate

Cycle 2 separates provider reliability from semantic quality before any P1/P2/P3
comparison. The frozen gate contract is
`contracts/cycle2_model_gate_v1.json`.

## Predeclared protocol

- 16 independent structured-output calls per provider/model;
- six Guardian task families and one identical JSON schema for every call;
- temperature `0`, reasoning effort `low`, 256 output tokens;
- 45-second per-call timeout, five-second pacing, zero hidden retries;
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
| TokenHarbor / `deepseek-v4-flash:free` | 16 | 0 | 0 | 0 | all 16 calls were sanitized `http_request` rejections |

TokenHarbor produced no 429, 5xx, or timeout in this run, but also no accepted
structured-output request. Therefore its semantic quality is `null`, not zero.
The rotated credential value was never serialized. Overall status is
`EVALUATION_BLOCKED_BY_PROVIDER`, so no remote P1/P2/P3 call is permitted from
this result.
