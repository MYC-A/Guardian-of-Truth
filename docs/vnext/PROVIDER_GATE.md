# B.AI development reliability gate

The current model documentation advertises qwen3.8-flash API at zero Credits
during a temporary offer: https://docs.b.ai/llmservice/models/qwen3-8-flash/.
This is not an audit of actual account billing or a permanent-free guarantee.

Fresh connection smoke at implementation 3efd46b: HTTP 200, valid JSON,
served qwen3.8-flash, 4005.949 ms, 152 reported tokens.
Source of truth: outputs/vnext/provider_smoke_vnext_v1.json.
One smoke is NOT a repeated reliability gate.

The separate evaluate_vnext_provider_gate.py script freezes its implementation,
tasks, schemas, transport settings and admission rule before the first request.
Four controlled actor/intent/async/causality microtasks repeat three times.
All 12 attempts must succeed in transport and schema; at least 11 must be
semantically correct for admission. Sequential requests have a ten-second minimum
start interval, 180-second request timeout, no hidden retry, and schema in text.
The runner conservatively stops at the first transport failure.
Completed attempt files are immutable and resumable under identical source hashes
and configuration. A finished report cannot be overwritten.

Transport, schema and semantic errors have separate classifications and
denominators. Raw server errors and credentials are never serialized.
No blind cases or gold files are opened. Passing this controlled development gate
does not prove stage quality, blind performance, long-batch quota or safety.
A fresh gate close to the eventual frozen blind candidate is still required.
