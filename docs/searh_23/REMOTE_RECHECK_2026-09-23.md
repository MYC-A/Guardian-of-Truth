# Gateway recheck on public46 (2026-09-23)

This report records **new executions** of the versioned runners in
`experiments/recheck_2026/` on the Guardian Gateway. The 46 cases have been
examined repeatedly; all scores below are mechanism checks, not an unseen
competition estimate. Labels were used only for scoring.

## Environment and input identity

- Gateway execution: NVIDIA A10, CUDA available; Python 3.11.11, PyTorch
  2.9.1, Transformers 5.16.1, Accelerate 1.13.0, Clingo 5.8.2.
- Granite Guardian 3.3 8B weights were loaded from the server's local model
  directory. Mistral was called through its API using the existing server
  `.mistral.env`; the served model reported `ministral-14b-latest`.
- All eight frozen input files match the local checkout byte for byte after
  normalizing Windows CRLF to LF. The control CSV already matched without
  normalization. The server passed 16 recheck/C2 tests.
- The server repository was updated through commit `8cc7988`; each runner
  wrote a fresh `config.json`, `records.jsonl` and `summary.json` under
  `outputs/recheck_2026/`. No secret values were copied into the repository.

## Completed controls

| Run | Result | Interpretation |
|---|---|---|
| Fixed typed tool route, 46 cases | TP23 / FP16 / FN0 / TN7, F1 .7419; 165 executed tools; 16 safe-card candidates; 0 label changes | Reproduces the pgjudge baseline. A safe card is insufficient to clear the full response. |
| Frozen C2 claims into X5, 44 valid pairs | C0 and C2 both TP7 / FP0 / FN16 / TN21, F1 .4667; 0 changed labels | The saved C2 extraction did not improve this end-to-end binder. Two proposals were schema invalid. Twelve internal `PROVED_NO_ERROR` states became `UNRESOLVED`. |
| Old Granite groundedness tokens reinterpreted, 23 cases | TP2 / FP3 / FN11 / TN7, F1 .2222 | Correcting the old risk-token polarity alone does not recover S7. This is a diagnostic on saved outputs, not a matched new inference run. |

## FP reviewer: completed negative result

The new eight-operation Mistral reviewer attempted all 35 source-grounded
positive pgjudge alarms. The source-quote replay gate passed, but there were
**zero 1→0 flips**: TP23 / FP16 / FN0 / TN7, F1 .7419. On 34 of 35 reviewed
cases the model claimed that another error existed. Six cases had all cited
cards refuted with exact anchors, but four of those six are true positives;
blindly removing that guard would have lost known positives. This runner does
not reproduce the collaborator's uncommitted v3 claim (TP23 / FP4 / FN0).

## Granite custom violation criterion: completed negative result

On the 103 saved S7 suspicions covering 23 cases, a new local Granite run
with an explicit `custom_criteria` violation test gave TP13 / FP9 / FN0 /
TN1, F1 .7429 at case level (`any supported` aggregation). The first
gold-negative case alone had four of five suspicions scored as supported.
This criterion largely restores the original all-positive behavior rather
than supplying a selective independent verifier. It does not cover the
remaining 23 cases and is not a formal proof.

The matched new `groundedness` run was even less selective: on the same 23
cases it gave TP0 / FP4 / FN13 / TN6 at case level. The old risk polarity
was indeed reversed, but correcting its semantics and rerunning with the
target response in the documents did not turn Granite into a useful S7
hypothesis verifier.

## Mistral context placement: partial mechanism gain

The same Mistral API judge saw either the first 10k prompt characters or a
5k/5k head/tail selection, with the same response and prompt. On **44 cases
valid in both arms**, first-10k gave TP21 / FP19 / FN1 / TN3 (F1 .6774);
head/tail gave TP22 / FP16 / FN0 / TN6 (F1 .7333). Five of six changed
labels became correct; one became wrong. Two other cases had malformed JSON
in one arm and are excluded from this paired comparison. This confirms that
dropping the recent history was a real confound in the older holistic test.
The small number of discordant pairs does not establish a stable gain on new
data, and the corrected holistic arm still has 16 false positives on the
paired set.

## Q discriminating question: candidate-specific gain not established

The corrected Q run selected one frozen disagreement fragment from each of
12 distinct cases. The exact fragment was independently verified in the
policy; **none** of the model's own 12 copied quotes matched exactly. All
12 semantic checks returned `supports`, which is a model opinion rather
than a formal entailment test. With the same judge and case input on each
arm, baseline was TP6 / FP5 / FN0 / TN1 (F1 .7059), and adding the proposed
interpretation gave TP6 / FP2 / FN0 / TN4 (F1 .8571). The three changed
cases were all gold-negative. However, the judge's `used_candidate` field
was false for two of those three changes. The **cross-case placebo removed
exactly the same three false positives** using candidates from other cases
(two of the three had different domains). It also turned one true positive
into a false negative:
placebo TP5 / FP2 / FN1 / TN4 (F1 .7692). This strongly suggests that the
observed Q improvement comes from prompt sensitivity to an added candidate
block, rather than the correct policy interpretation. The source candidate
avoided the placebo's extra false negative on these 12 cases, but that is a
single viewed-set difference, not established causal benefit. A stricter
**cross-domain placebo removed two of the same three false positives** with
no lost true positives (TP6 / FP3 / FN0 / TN3, F1 .8000). Thus most of the
observed improvement is reproduced by irrelevant cross-domain text. The one
additional FP removed by the real candidate is a single viewed-set case.
This branch should not be promoted without an unseen, placebo-controlled
test.

## Agent tool routing: recovered interface, no marginal gain here

The first live typed run processed all 46 cases but executed only 28 tools:
the planner repeated actions 45 times and had 38 HTTP failures while other
API jobs were hitting 429. Its zero label changes are not a valid rejection
of agent routing.
The second attempt bounded invalid actions but the planner represented
card targets as JSON objects while the executor required integer indices;
it was stopped at 21 cases after only eight tools. The third variant binds
the planner's choice to a catalog of exact executable action IDs. On all 46
cases it executed 148 tools versus 165 for the fixed route, with **the same
16 safe cards on the same 14 cases** and zero label changes in either arm.
Agent calls selected 70 card checks, 66 history events, three graph paths
and nine quote lookups. Forty-two proposed action IDs were invalid, six
planner responses had invalid JSON, and three cases got no executed tools.
One graph conflict was found in a case already positive under pgjudge. The
agent averaged 9.07 seconds per case versus 0.0047 seconds for the fixed
local route. This is a valid negative for **this catalog, planner and
conservative controller**: it found no extra useful safe-card evidence or
end-to-end gain. It does not refute agents with a different evidence target
or a proven whole-response clearance rule. An isolated safe card cannot
justify a whole-response `0` without checking other possible errors.

## Artifacts

The raw `config.json`, `records.jsonl`, `summary.json` and relevant
`percase.jsonl` files from the full Gateway runs are committed under
`docs/searh_23/remote_recheck_2026/`. `manifest.json` lists byte sizes and
SHA-256 hashes. This allows case-level inspection of all numbers above.

## Decision rule

An apparent gain on this viewed public46 set is a hypothesis. It needs frozen
per-case evidence and one evaluation on previously unseen cases grouped by
scenario and response type. A model's citation is source-anchored evidence,
not a formal proof that its interpretation is correct. The original reported
v3 result (TP23 / FP4 / FN0) has no recovered per-case decisions in this
checkout; the new FP reviewer is a different, explicitly versioned test.

The next model-free effort should focus on **claim-level FP attribution**:
for each pgjudge alarm, retain the precise policy clause, triggering user
state, target response act, and any exception or contrary observation as
separate source-backed fields. Review a candidate clearance only after
checking whether the original positive contains another independently
supported error. The present reviewer failed exactly at that global step:
34 of 35 cases were declared to contain another error, including many
known false positives. Freeze the attribution protocol and test it on an
unseen scenario-grouped set before using it as a final label selector.
