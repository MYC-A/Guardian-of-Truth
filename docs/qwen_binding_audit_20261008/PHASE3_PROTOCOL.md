# Source-completion phase 3: matched full valid46 diagnostic

Registered before phase-3 inference, 2026-10-08. Separate from phase-2 binding
extraction. Prior known development errors motivated this retrieval hypothesis;
valid46 is not a blind test.

## Intervention

All 46 original inputs, no selected positive subset. Reconstruct the exact
dispatched historical B2 primary requests, preserving their existing neutral
analysis hypotheses. Control receives that same wire. Completion receives only
additional/expanded native history events from the generic exact typed-value
retriever, plus refreshed source-ID schema enums. System prompt, completion
limit, original move, policies and neutral hypotheses remain identical.

The two arms change source views in 7/46 rows. For 39 identical wires, one exact
transport response is shared by both arms; no need to spend duplicate inference.
There are 53 unique frozen requests, 92 result slots. No-op decisions must be
identical and cannot contribute improvement. Both arms use fresh attempt1 in
a new phase cache; no previous detector answers are substituted as controls.

Inputs prepared by `scripts/prepare_qwen_source_completion.py`. Runtime JSONL
contains requests, source-completion retrieval receipts and old request identity;
**no labels or old detector decisions**. SHA256:
`c93c40e3f0065cd6adb7850912684072fafa3d2733fa4ba176d68aab841effea`.

## Execution and admission

Same local Qwen Q8/llama.cpp alias, reasoning off as server profile, temperature0,
32768-token native per-slot context, original1700 completion limit, 8 workers,
240s timeout, no retries, at most100 fsynced reservations. Cache-equivalent
parallel calls may both reserve budget but transport sends a single request.
No truncation. Do not launch concurrently with phase2; use a separate worktree
so its frozen runtime HEAD remains unchanged.

Each full reply must finish normally, decode without duplicate keys and validate
the locally refreshed JSON schema. Admission v2 actor normalization is retained.
ERROR/NO_ERROR/UNKNOWN and technical failure remain distinct. Admitted semantic
judgments are MODEL_JUDGMENT, never code proof. Missing/failed calls are reported.

This evaluates the **primary reviewer** source change. Downstream DF/Ems/AT are
not rerun, so primary-review metrics and an optional frozen-base additive
projection must be labelled separately from a full new B2 pipeline run.

## Scoring and next decision

Use unchanged original valid46 labels (23/23), full46 denominator. Report fresh
primary control vs completion, TP/FP/FN/TN, UNKNOWN/technical counts, explicit
UNKNOWN→0 projection and sensitivity bounds. Also report old frozen full B2
separately; do not credit ordinary repeat variation to retrieval. New gains/losses
must occur in changed-wire rows. Inspect every changed ERROR cause against the
original policy, user request, chronology and receipts, including alternative
true causes and known gold conflicts.

This is a cheap feasibility diagnostic. Any genuine paired cause-correct recovery
with no new false accusation can motivate broader matched tests and new contrasts;
it cannot establish universal improvement or change default. If no gain, preserve
the negative result and investigate extraction/semantic attention instead.

Independent subagent review of the previous compact runner and 25 scorer tests
completed. The new source-completion runner currently has9 author tests/root
review; additional independent agents could not run due account usage limits.
This review gap is explicit, not rebranded as independent approval.

```bash
PYTHONPATH=src:. LOCAL_LLAMACPP_ENDPOINT=http://127.0.0.1:8081/v1/chat/completions \
python -X utf8 -u -m experiments.guardian_binding.source_completion_pilot \
 --input docs/qwen_binding_audit_20261008/source_completion_phase3_inputs/runtime_requests.jsonl \
 --output outputs/qwen_binding_pilot/phase3_source_completion \
 --model-id 'qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459' \
 --workers 8 --max-calls 100 --timeout 240
```
