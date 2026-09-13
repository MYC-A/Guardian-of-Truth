# Goal v3 isolation: repository audit before experiment

Audit source HEAD: `48b84e3875b960d43956576735d543e8c4e5917b`
on `experiment/guardian-vnext-from-0199bf9`. `git fetch origin` completed;
`origin/experiment/guardian-vnext-from-0199bf9` equals this HEAD. The worktree
was clean at the audit. No merge/pull changed the candidate. Production V5.3,
Cycle 1, Cycle 2 and frozen Goal v2 were not modified.

## What actually exists

Goal v2 is the immutable 22-case experiment at implementation commit
`a9150076a445d7cf86eac70500aa259f058a9209`: 22/22 UNRESOLVED, zero
definitive certificates, 190 requests and 361,883 reported tokens. Its results
and failure audit are in `outputs/vnext/goal_plan_v2_*`; see
`GOAL_PLAN_RESULTS.md`. Safety conservatism did not produce useful resolution.

The latest committed Goal v3 code is `goal_alignment_records_v3.py`,
`goal_alignment_primitives_v3.py`, `goal_alignment_v3.py` and the independent
`goal_alignment_certificate_v3.py`. A separate adapter
`benchmarks/vnext/goal_alignment_fixture_contract_v3.py` accepts only one
exact pinned shipment fixture. The 36 controlled source inputs and their
reference statuses were frozen before this kernel, and source-only hashes
were separately frozen. Unit tests execute all 36 sources and verify that
definitive fixture certificates replay; they do **not** compare all 36 outputs
with gold and are not a measured v3 result.

Goal v3 evaluated implementation at audit: **none yet**. The implementation
available for the next offline baseline is commit `48b84e3`; its prompt/schema
version is **NONE** because it makes zero LLM calls. There are no
`goal_alignment_v3_*predictions*` or `goal_alignment_v3_*results*` artifacts.

The general `core.py` still imports `goals.parse_goal_plan`, not Goal v3.
`external_factual_runtime_v6.py` explicitly excludes Goal/Policy composition.
No Goal v3 + Core integrated verdict or external holdout result exists.

## Document/code divergence

`GOAL_PLAN_V3_DESIGN.md` specifies an open-vocabulary, source-grounded
Goal/Plan frontend with alternate readings, conditional guards and all-world
certificates. The committed v3 kernel implements only the **trusted structured
fixture** side of that design. It has no general USER-goal semantic extraction,
no v3 prompt/schema, no real source-authority adapter and no current-action
composition with Claim/Policy/Core. Without pinned fixture replay it returns
UNRESOLVED even if its conditional calculation looks decisive.

The existing fixture's base restriction is a SYSTEM contract about shipment
operations. It exercises the obligation checker but cannot by itself measure
the requested isolated interpretation of USER goals without a Policy layer.
The 36 existing examples are not the requested 24 minimal pairs plus 12
compositional cases; their annotation lacks the requested actor/intent/failure
and historical-state axes. Treat them as observed development diagnostics,
not the new Goal-only decision benchmark.

The new experiment therefore starts from this exact kernel and its limitation.
Any necessary Goal-only frontend/adapter extension must be versioned as
`implemented-from-spec`, with assumptions disclosed before first model call.
Policy parser/verdict will not supply any candidate, feature, label or score.
No external LLM request is authorized until the 60-case benchmark, gold,
projection, schema, scorer, gates, prompt and provider config are frozen.
