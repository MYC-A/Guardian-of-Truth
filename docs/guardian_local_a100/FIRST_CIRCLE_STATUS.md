# Fast circle: launch receipt and provisional comparison

The user transferred push ownership. Supervised guardian-fast-circle is RUNNING;
it waits for the existing Distill job without restarting it, then scores/pushes
Distill, runs native Lynx grounding and publishes the diagnostic comparison.
Code is frozen at 2993fd9b; launch receipt records the actual supervisor state.
Nine focused tests pass locally and on the A100 server. No paid API is used.

Saved valid46 B2 metrics before Distill finishes:

| model/configuration | TP | FP | FN | TN | F1 | blind prepass delivered |
|---|---:|---:|---:|---:|---:|---|
| Ministral saved baseline |14|9|9|14|.609|legacy report|
| Qwen Q8_0 non-thinking |13|1|10|22|.703|30/46|
| GPT-OSS native MXFP4/Harmony |13|4|10|19|.650|31/46|
| Compass pointwise Q8_0 |6|0|17|23|.414|36/46|
| Distill Q8_0 thinking |pending||||||

Sources: committed score JSONs at d09a7d12; this is historical score extraction,
not fresh inference, cause adjudication or independent validation. A/M/B2 runs
use the same fixed 70 inputs, but modes/output budgets differ. Technical gaps
and common valid coverage must accompany final ranking. The old comparison's
rows double-count and old unused Lynx contract are corrected in separate modules;
the untracked predecessor comparison and all running/saved results are preserved.

Largest measured delivery gap: 16/46 Qwen and 15/46 GPT-OSS B2 analyses were not
injected. Thus the current arm mixes delivered B2 and AM fallback. Repairing
context delivery belongs to a separate frozen stage-2 comparison; it must not be
silently applied to the current circle or explained as a model quality failure.
Lynx is an independent factual-grounding lane, never another policy F1 candidate.

Authoritative live progress: outputs/guardian_local_a100/continuation_20261007/state.json
and /workspace/guardian/logs/fast_circle_continuation.log on the server.
