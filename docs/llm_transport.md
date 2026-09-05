# JSON chat transport

`guardian_truth.llm_client.ChatClient` uses the Python standard library and an
OpenAI-compatible `/chat/completions` endpoint. Importing or constructing it makes
no requests. `complete(messages, schema=None)` returns `Completion(content, usage,
model)`. Content must be a JSON object; callers still validate their domain schema.

The default endpoint is `https://api.groq.com/openai/v1`, with configurable model
`openai/gpt-oss-120b`. Credentials come only from the environment variable named
by `api_key_env` (default `GROQ_API_KEY`), read when a request starts. No credential
is stored in configuration, logged, or included in public error messages. Missing
cloud credentials and keys containing non-ASCII, whitespace, or control characters
fail before transport. Set credentials outside source files and command history.

`ClientConfig.from_env()` and a default `ChatClient()` recognize:

| Variable | Default |
| --- | --- |
| `GUARDIAN_LLM_BASE_URL` | `https://api.groq.com/openai/v1` |
| `GUARDIAN_LLM_MODEL` | `openai/gpt-oss-120b` |
| `GUARDIAN_LLM_API_KEY_ENV` | `GROQ_API_KEY` |
| `GUARDIAN_LLM_TIMEOUT_SECONDS` | `30` |
| `GUARDIAN_LLM_MAX_OUTPUT_TOKENS` | `2048` |
| `GUARDIAN_LLM_MAX_RETRIES` | `2` |
| `GUARDIAN_LLM_STRICT_SCHEMA` | `true` |

The same fields can be passed directly to `ClientConfig`. Explicit configuration
does not merge environment settings. `GUARDIAN_BASE_URL` and `GUARDIAN_MODEL` are
fallback aliases; the corresponding `GUARDIAN_LLM_*` values take precedence.
`client.validate_configuration()` checks endpoint and credential syntax locally,
without calling the server. Timeout must be positive and at most 300
seconds; retries must be 0–8. The timeout is a socket operation timeout, not a total
wall-clock deadline for an entire application run.

For a local compatible server, set the base URL to, for example,
`http://127.0.0.1:8000/v1` and select that server's model. HTTP is permitted only for
literal loopback IP addresses or `localhost`; cloud endpoints require HTTPS.
Local servers can operate without a key. Set `GUARDIAN_LLM_API_KEY_ENV` to a
dedicated variable such as `LOCAL_LLM_API_KEY` when switching locally so an existing
Groq credential is not sent to the local server. A nonempty configured key is sent
as Bearer authorization. URL credentials, query strings, fragments, and every HTTP
redirect are rejected. HTTPS endpoints are configurable and should be trusted by
the operator. This client does not download models or start a local server.

Requests use `response_format={"type":"json_object"}` by default. Include an
instruction to return JSON in the supplied messages. Passing `schema=...` selects
`json_schema` with the `strict_schema` flag; only use this on a model/server known
to support it. Groq documents strict structured outputs for `openai/gpt-oss-20b`
and `openai/gpt-oss-120b`; there is no automatic switch to schema mode or fallback
that weakens a requested schema. No tools or streaming are used. See the official
[Groq structured output documentation](https://console.groq.com/docs/structured-outputs)
and [API reference](https://console.groq.com/docs/api-reference).

Only HTTP 429 and 5xx responses retry, at most `max_retries` times after the first
attempt. Delays use bounded `Retry-After` seconds/dates or exponential backoff,
with a 30-second maximum delay. Socket/network failures fail immediately with a
retryable category so an application can decide whether to repeat a potentially
billed request. HTTP authentication errors and other 4xx responses never retry.

Live integration uses the explicit `guardian-truth/0.2` User-Agent. On the observed
Groq endpoint the standard Python-urllib header received HTTP 403 while the same
key with this header succeeded. A 403 is `forbidden`, not proof of an invalid key.
HTTP 413 is `request_too_large`; 404 is `model_or_endpoint_unavailable`.
Provider TPM/TPD quotas remain separate from local character/time budgets.
The response read is capped at 8 MiB. A truncated completion (`finish_reason=length`)
fails, as do refusals, tool-call responses, malformed JSON, non-object content,
and invalid token usage metadata.

`ChatClientError.category` is a fixed machine-readable value: `configuration`,
`missing_api_key`, `invalid_api_key`, `invalid_request`, `authentication`, `forbidden`,
`redirect`, `rate_limit`, `server`, `http_request`, `timeout`, `connection`,
`transport`, `truncated`, or `invalid_response`. Public errors omit response bodies,
prompts, underlying exception text, and credentials. `retryable` describes whether
a later application attempt might succeed; it does not mean retrying indefinitely.

Tests inject a callable `transport(request, timeout) -> HTTPResponse(status, body,
headers)` and a sleep function. All committed transport tests use synthetic
credentials, mocked HTTP handlers, and fake responses; no live API is required.
