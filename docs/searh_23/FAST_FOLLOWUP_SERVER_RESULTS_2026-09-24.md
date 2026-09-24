# Fast follow-up: server results and decision (2026-09-24)

## Protocol

Branch `codex/fast-followup-20260924`. The service-desk suite has 32 authored
cases, balanced by reference label and target response call shape (8 per cell).
The paired renamed suite has the same 32 underlying cases with all case/device
IDs and tool names changed. It is a lexical perturbation, **not 32 independent
new examples**. Both CSVs and rubrics were frozen before the first score.
Inference files contain only `id,prompt,response`; each score operation sealed
complete prediction files before reading the corresponding `expected.json`.

Original prediction-seal SHA-256:
`ae157426c0b2254d0f8dfc22527b2bf37d2ce8e96c3d93056044e0425b56db28`.
Renamed prediction-seal SHA-256:
`69b46d57a915c683970d19bc4a34e56cce2f4387d99f4bf0ee93444fdb4e393a`.
Server score artifacts are under
`outputs/searh_23/fast_followup/service_desk_v1_bae8a98_run1/` and
`outputs/searh_23/fast_followup/service_desk_v1_renamed_1084a65_run1/`.

## Frozen score (TP / FP / FN)

| Arm | Original | Renamed | Measured marginal result |
|---|---:|---:|---|
| C1, 12k | 16 / 12 / 0 | 16 / 12 / 0 | Base; 6 FP are valid tool calls in each suite. |
| C1, 24k or 60k | 16 / 12 / 0 | 16 / 12 / 0 | No decision changed. |
| C1 OR official Granite `function_call` | 16 / 12 / 0 | 16 / 12 / 0 | No decision changed; eligible criterion found 1/8 bad calls and flagged 2/8 then 1/8 good calls. |
| pgjudge | 16 / 12 / 0 | 16 / 14 / 0 | Two benign-renaming FP flips. |
| v3.1, v4, or v4-safe | 16 / 9 / 0 | 16 / 10 / 0 | Identical labels on this suite. |
| TQ over v4-safe | 16 / 9 / 0 | 16 / 10 / 0 | No label changes; original run used 67 Mistral calls. |
| C1 AND pgjudge | 16 / 11 / 0 | 16 / 11 / 0 | One FP removed in each. |
| C1 AND v4-safe | 16 / 8 / 0 | 16 / 7 / 0 | Four/five FP removed, zero TP lost **before soundness audit below**. |
| Feasibility v1 alone | 0 / 1 / 16 | 0 / 1 / 16 | Its only candidate is a permitted stock-out refusal. |
| Feasibility v2 alone | 2 / 0 / 14 | 2 / 0 / 14 | Correct refusal/handoff cases, but C1 already finds both; C1 OR v2 is unchanged. |
| Completion v1 alone | 0 / 0 / 16 | 0 / 0 / 16 | No validated candidate. |
| Completion v2 alone | 0 / 0 / 16 | 1 / 0 / 15 | One positive only after renaming; C1 OR v2 is unchanged. |
| Historical E2E R1 or R2 | 2 / 0 / 14 | 2 / 0 / 14 | Large recall loss; OR with C1 is unchanged. |

All full-coverage arms above have 32/32 predictions. `function_call` standalone
covers only the 16 target-call cases. The 12k/24k/60k C1 outputs were identical
under renaming. The C1+v4-safe paired prediction changed once, beneficially,
on the renamed identity-request case. E2E used the pinned `300dc2e` source,
not current branch code, with Mistral through its API.

## What caused the apparent veto gain

In the original suite, pgjudge itself rejected the valid user-device-test
case (one C1 FP). The other three C1 FP removals came from the **same v3.1
family H**: a cited policy span lacks an English obligation modal. Renaming
added one more clearance from that same family. The v4 history/temporal
families supplied no unique removal here. All remaining six valid-call FP
survived because v4 conservatively keeps live action calls to avoid losing TP.

Family H is logically unsound. The actual source policy says, for example,
“Before executing a device replacement or fee refund, verify the requester's
identity ... and obtain ... confirmation.” This is an imperative obligation
without `must`. On the true false-refusal case, pgjudge cited that very
clause and family H marked that card `REFUTED`; the case remained positive
only because other cards were also kept. Thus a sole-card version could lose
a TP. The apparent 4–5 FP gain cannot be promoted as a safe general veto.

Post-score, commit `ffc14d2` added a **separate, gold-free modal-safe replay**
which maps family H's unsupported `REFUTED` to `UNKNOWN` and leaves every
other v4 decision intact. Its retrospective comparison, explicitly in-sample
and outside the original prediction seal, is:

| Arm | Original | Renamed |
|---|---:|---:|
| Modal-safe refutation alone | 16 / 12 / 0 | 16 / 14 / 0 |
| C1 AND modal-safe refutation | 16 / 11 / 0 | 16 / 11 / 0 |

The single surviving veto gain is pgjudge's independent rejection. The
modal-safe replay code and per-case traces are in
`experiments/searh_23/fp_refute_modal_safe.py` and each run's
`refute_modal_safe.json`; it does not modify the frozen score.

## Feasibility stress check

After inspecting the v2 outputs, we made 16 **unlabelled, post-inspection**
variants: for both refusal/handoff cases in each lexical suite, remove one of
stock availability, identity verification, authorization, or user
confirmation. Feasibility v2 returned 0 `CANDIDATE` (10 `UNKNOWN`, 6
`NO_PROPOSAL`). This supports the narrow conditional gate on this policy; it
is not independent evidence that the model has learned all possible
prerequisites. Its positive proposals still rely on the model to list the
complete policy antecedents, and its code validator does not prove that list
is complete.

## Public46 feasibility transfer check

We also ran feasibility v2, unchanged, on all 46 label-free public inputs
after the service-desk run. All 46 completed technically: 41 `INELIGIBLE`,
4 `UNKNOWN`, 1 `NO_PROPOSAL`, **0 `CANDIDATE`**. This is an inspected public
set, not a new holdout. Crucially, the two known C1 misses
`banking_knowledge__task_003::t7` and
`banking_knowledge__task_018::t6` are assistant
`TOOL_CALL transfer_to_human_agents` turns. The feasibility arm is gated on
refusal/handoff **text**, so it never evaluates either. The third known C1
miss `retail__29::t13` reaches the arm but returns `NO_PROPOSAL`. Thus v2
recovers **0/3** known C1 false negatives on public46; its 2/0 authored
standalone result is not a demonstrated transfer benefit. Raw predictions:
`outputs/searh_23/fast_followup/public46_feasibility_v2_ffc14d2_run1/feasibility_v2.jsonl`.

## Decision

No new full classifier is ready for a general demo claim. C1 remains the
reproducible control, but 12/16 negative cases in this authored suite are
false alarms, including 6/8 valid action calls. The only large apparent
improvement depends on an invalid modal-word heuristic. The official
`function_call` criterion, larger Granite context, TQ, and historical E2E did
not fix the call branch. Feasibility v2 is a narrow, source-cited component,
not a demonstrated C1 improvement: it misses all three known public46 C1
false negatives in its current interface. Completion v2 is lexically unstable.

Next useful validation needs either a genuinely untouched contest-like set
for C1 versus a **source-backed** call-satisfaction verifier, or an official
hidden evaluation. A verifier should bind the target call to the exact
entity, amount, latest observation, user confirmation and policy trigger, and
return `UNKNOWN` when any required premise is not represented. A broad graph
or another unsourced judge is not justified by these results.
