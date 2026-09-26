# Action trigger and ordered-evidence transfer

## What was frozen and what was added after observation

At commit `c1a468c`, before any parcel inference, the branch contained a
source-anchored action trigger, four action-stage controls, two balanced
12-case parcel suites, both gold files and frozen label-free model inputs.
The suites use the same policy and history, changing only declared tool names
and retaining their descriptions. Each has six valid and six invalid proposed
calls. The original and renamed Mistral API runs used the earlier, unchanged
call-condition prompt. Scores and predictions were sealed before this audit.

The **temporal counterevidence layer was written after reading the parcel
answers**. Its parcel counts are therefore post-hoc development results. The
service-desk and hotel replays are also viewed development evidence. None is
an untouched Guardian score, and no new arm is wired into `scripts/predict.py`.

| Suite | Raw model TP/FP/FN/TN/U | Action scope TP/FP/FN/TN/U | Scope + temporal TP/FP/FN/TN/U |
| --- | --- | --- | --- |
| Parcel, original names (12) | 6/2/0/3/1 | 6/1/0/3/2 | 6/0/0/3/3 |
| Parcel, renamed tools (12) | 6/2/0/4/0 | 6/1/0/4/1 | 6/0/0/4/2 |
| Service desk, original (16) | 8/0/0/6/2 | 8/0/0/6/2 | 8/0/0/6/2 |
| Service desk, renamed (16) | 8/3/0/5/0 | 8/1/0/5/2 | 8/0/0/5/3 |
| Service desk, state changes (8) | 6/2/0/0/0 | 6/2/0/0/0 | 6/1/0/0/1 |
| Hotel one-call slice (8) | 4/4/0/0/0 | 4/1/0/0/3 | 4/1/0/0/3 |

`U` is unknown; it is **not** a true negative. Hotel retains the previously
identified disputed `pair11::ok` gold. The table is a count of supported
accusations after withdrawing specific bad reasons, not a deployable binary
score. Mapping UNKNOWN to a competition label requires a separately selected
fallback, which may restore false alarms or lose true ones.

## Trace findings

The first parcel false alarm said a prior invalid address result barred even
`read_shipment`. An exact policy clause gates **dispatch**, and the declared
tool only **reads** a shipment. The action trigger withdrew that accusation.
The second said an older invalid result was not superseded, while citing the
newer valid result for the same shipment. The temporal layer paired each check
call with its adjacent result, matched the exact shipment ID, and selected the
latest Boolean `valid` observation. It withdrew the inaccurate timing claim.
The same last-observation operation handles service-desk inventory after tool
renaming. An earlier reported successful replacement result for the same case
also disproves the renamed-suite model statement that an audit was attempted
*before* that result.

The counterchecks matter as much as the gains. The layer refuses to use a
result from another shipment/case, a failed action, a related read tool with
generic `status: completed`, an unpaired result or a positive stock result
to clear a clause that also requires identity, confirmation and authorization.
It does not infer that a generic completion status proves an external business
postcondition. One state-control false alarm remains: the model incorrectly
reads an explicit user confirmation containing `$250`. The layer cannot
settle that text claim with the current typed evidence.

## What came from adjacent systems

- [Invariant](https://github.com/invariantlabs-ai/invariant) distinguishes
  `ToolCall`, `ToolOutput` and ordered trace patterns. We transferred the
  **triggered action versus prerequisite read** distinction and result order,
  without installing its DSL. The policy still has to identify the governed
  action; quote validity alone does not do that.
- [ToolSandbox](https://github.com/apple-aiml-research/ToolSandbox) uses
  stateful tools, trace milestones and distractors. We transferred paired
  state changes, renamed tools and benign controls to the *evaluation design*.
  Guardian receives only a trace at inference, so the simulator's true state
  is not an available runtime oracle.
- [Formal runtime verification for tool-using agents](https://github.com/nikos-kekatos/formal-rv-tool-using-llm-agents)
  motivates exact same-entity, before-action witnesses. We require a paired
  result and exact ID; an approval or success for an unrelated entity does
  not count. This does not create missing policy or tool-effect semantics.

## Decision

Keep the action trigger and temporal counterevidence as **diagnostic
components**. Their exact source quotes and event IDs make the model's wrong
reasons auditable, but a withdrawn accusation returns UNKNOWN. The grammar
recognizes a narrow set of explicit `before`, `after` and latest-observation
clauses; mixed or unclear tools stay UNKNOWN. It is not a general natural
language policy compiler and has not shown a marginal gain over the current
binary submission on untouched contest data.

Reproduce the frozen parcel inputs with
`python experiments/searh_23/build_parcel_trigger_v1.py`; replay a scored
suite with `python experiments/searh_23/action_trigger_replay.py --dir
outputs/searh_23/call_condition_probe/<suite> --layer scope` or
`--layer temporal`. The replay checks the frozen-input and prediction hashes
before reading scored rows. Artifacts and per-case traces are under
`outputs/searh_23/call_condition_probe/`.
