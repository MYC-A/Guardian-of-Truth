# Compact source addresses: technical amendment and phase 2

Registered 2026-10-08 before phase-2 inference. Phase 1 is stopped, preserved
unchanged in `phase1_transport_stop/`, and is not a quality verdict. Of its
first 8 completed records, 2 processed and 6 timed out at 90 seconds; 16 calls
were reserved before stop (8 additional abandoned calls). Server diagnostics
show approximately 13 generated tokens/second per slot. Continuing the same
timeout would primarily measure serialization/transport failure.

Phase 2 retains all 86 inputs, old labels, source view and paired blind/visible
intervention. It changes BOTH arms equally:

- Compact wire `t,a,s,p,r,v`: target, argument pointer, expected result source,
  expected JSON pointer, requesting USER source, and E/L/U status.
- No generated quote/rationale/policy text. Code resolves exact source leaves
  and obtains the requesting source text by address. This is labelled
  `CODE_SOURCE_TEXT`, not a model-selected exact quote or semantic proof.
- Request source must be a historical user text; expected source must be a
  tool result. Semantic ownership, exceptions and relation validity still
  require the separate full-packet model verifier.
- Extraction limit 900 tokens; timeout 240 seconds. Full-packet verification
  remains 900 tokens. Maximum 2 candidate verifications per row/mode, 8 workers,
  520 conservative fsynced reservations, no retries, native 32768-token
  context accounting, separate `outputs/qwen_binding_pilot/phase2_compact`.

The different prompt/schema is a new version. Phase-1 replies are not used as
phase-2 extraction answers. The original verbose module and frozen commit
remain unchanged. The amendment was motivated by timeout/throughput evidence;
no model-accuracy optimization against phase-1 labels was performed.

All other analysis and advancement rules in `PILOT_PROTOCOL.md` remain: full
coverage reported, 2 independently source-correct real FN recoveries, no new
external FP or false added causes, no negative contrast false accusation and
at least 4/6 supported unique-binding positive contrasts before expanding.
Choice-set and approval-only coverage remains explicit. This pilot is still
development and author-controlled diagnostic evidence.

```bash
PYTHONPATH=src:. LOCAL_LLAMACPP_ENDPOINT=http://127.0.0.1:8081/v1/chat/completions \
python -X utf8 -u -m experiments.guardian_binding.pilot \
  --input docs/qwen_binding_audit_20261008/pilot_phase1_inputs.jsonl \
  --output outputs/qwen_binding_pilot/phase2_compact \
  --model-id 'qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459' \
  --workers 8 --max-calls 520 --context-tokens 32768 --max-verify 2 \
  --wire compact --timeout 240
```
