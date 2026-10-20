# V14: bounded native ownership contrasts, before inference

Source tau2 revision96a3ef92329baf908ffe9dfe188cea34e8701d2a (MIT).
No evaluation dialogue, task metadata, generated model answer or observed error
seeds the cases. New short diagnostic requests use ten predefined no-argument,
read-only native device tools. No artificial history lengthening. This is a
small targeted supplement, not hundreds of independent natural trajectories.

For alternating tool names, the correct twin either guides the user under normal
policy, or calls the device tool under the original native solo-mode policy.
The incorrect twin calls that user-owned tool as assistant under normal policy.
Native role routing must reject the latter, allow the solo read, and leave DB
hashes unchanged. Source policy and available tool catalog must agree with mode.
Do not infer whole-policy correctness from successful tool execution alone.
The constructed read has an explicit user diagnostic request; it does not
perform an account write, bill payment, unsupported factual claim or transfer.

Use real complete workflow policies and native schemas. Solo catalog is the
union of original assistant and user tools because native solo make_tool_call
allows both. Normal catalog excludes user tools. Results of proof executions
remain outside model history/rationale. Explanations describe only the visible
policy, catalog and current turn. Replay production parsing and source quotes.

Split by tool group before model calls: check_wifi_status and
check_network_mode_preference reserved for a tiny diagnostic HOLDOUT; all other
tool groups proposed TRAIN. Two held-out tools are not an independent-policy
acceptance set and are not grounds for a ZIP. No unavailable human review claimed.
Apply the original external exact/near/entity exclusion, and also the V4 frozen
DEV/HOLDOUT exclusion. Reject complete pairs on a match; preserve exclusions.

No automatic training or production promotion from data preparation. Freeze
the accepted data and any later training objective before optimization. Preserve
counterexamples where direct device access is allowed: never teach a global
veto on phone-tool calls. Count original source groups rather than paraphrases.
