# System trajectories v1: frozen evaluation protocol

Frozen on branch `codex/system-integration-step1-4-20260930` before any new
Step 3/4 implementation or prompt selection. Run
`py -3 experiments/searh_23/system_integration_v1/freeze_trajectories.py`
to regenerate the flat files; `frozen/trajectories_v1/manifest.json` records
SHA256 for each exact byte stream.

## Cases and split

- 41 complete synthetic trajectories, 21 dev and 20 sealed.
- Dev families: depot, payments, service, records.
- Sealed families: aviation, utilities, retail, field.
- Families are disjoint. Every case has a policy, user request, tool catalog,
  assistant history, ordered calls/results, target response, completeness
  assumptions, casewise gold constraints/facts/claims/reachability/verdict.
- 48 mechanism tags include all required contrast classes; per-case gold
  identifies fact provenance, exact policy/claim source spans, target action
  and evidence cutoff.
- The suite is authored, not an independent real-world sample. Its sealed
  part is sealed against algorithm/prompt/threshold tuning after this commit,
  but the gold is stored in the repository for auditability. No sealed-gold
  inspection after freeze to repair performance.

## Evaluation rules

Use only `dev_inputs.json`/`sealed_inputs.json` for inference. Read gold in the
scorer only. Do not import `freeze_trajectories.py` into the detector: its
domain-specific information is fixture authoring, never an inference rule.
Keep model and parser settings fixed between paired arms. Run the existing
detector, F6 graph controls, integrated conservative path and full path on
the same inputs where their interfaces apply. Report unadaptable inputs as
UNKNOWN/unsupported, never silently drop them.

Count casewise `ERROR`, `NO_ERROR`, and `UNKNOWN`; report decided coverage,
accuracy on decided cases, ERROR recall, NO_ERROR recall, false alarms,
missed errors hidden by UNKNOWN, and per-stage failures. Proof paths must
reference source policy spans, tool-call IDs, result indexes/JSON paths,
target action or response spans, and the temporal cutoff. Separate automatic
contract/rule acquisition from oracle-supplied `ReviewedRule` and
`ReviewedBinding` ablations.

The fixture's `agent_tool_history_complete=true` means the transcript
includes all agent tool calls; `external_world_closed=false` means a missing
result or tool call alone is never a proof that an external effect did not
happen. An explicit contrary observation can refute a present-state claim.
Later evidence cannot license an earlier action.

Do not promote a component to `scripts/predict.py` based on this suite alone.
The final transfer check still needs independent external trajectories.
