# Small action graph and sourced fact chain — 2026-09-26

## What was tested

The repair-desk controls, gold, and label-free inputs were frozen in commit
`3c68de7` before the verifier was written. They have 12 cases, with six
violations and six valid calls. A second 12-case copy renames every tool but
keeps the declared semantics. The earlier parcel suites have the same layout.
All four suites are authored controls. The repair suite deliberately uses a
policy structure close to parcel; it is **not an independent generality test**.

`experiments/searh_23/micrograph_certificate_v1.py` compiles every policy bullet
in a narrow explicit English grammar. It links a target call to applicable
rules, pairs earlier calls/results, joins the same ID, selects the latest
relevant observation, and distinguishes reported successful actions from
checks and failed actions. Each check carries exact source event IDs and its
policy quote. The graph is internal evidence, not a long text document sent
to a judge. Unsupported policy text or an ambiguous tool/action yields
`UNKNOWN`; a completed read result cannot witness a replacement.

## Sealed replay

| Suite | TP | FP | FN | TN | UNKNOWN |
| --- | ---: | ---: | ---: | ---: | ---: |
| Repair, original tools | 6 | 0 | 0 | 6 | 0 |
| Repair, renamed tools | 6 | 0 | 0 | 6 | 0 |
| Parcel, original tools | 6 | 0 | 0 | 6 | 0 |
| Parcel, renamed tools | 6 | 0 | 0 | 6 | 0 |

These counts show that this **bounded grammar and fact join** can make binary
decisions on the cases it was designed to understand. On the viewed parcel
suite, the earlier raw Mistral call probe had TP6/FP2/FN0 in each name variant;
the micrograph has TP6/FP0/FN0. This is an in-sample mechanism comparison,
not a projected competition gain. The repair suite was frozen before the
implementation, but authored with the intended pattern and inspected during
development. Tool renaming tests that the declared descriptions rather than
the names carry the action role; it does not test new policy language.

On the existing service-desk one-call suite, the policy compiler returned
`UNKNOWN` on 14 of 16 cases; two malformed calls were found by the existing
structural check. Its prose combines identity, confirmation, authorization,
inventory, obligations to help, and response statements. The present grammar
cannot certify those cases. No Mistral API call, GPU run, full benchmark, or
competition entrypoint change was made for this experiment.

## Remaining barrier

The missing component is a reliable way to enumerate **all applicable clauses**
of an arbitrary natural-language policy and bind their action, entity, time,
and fact requirements. A graph or compressed fact chain does not by itself
solve this translation. The compiler currently treats tool results such as
`status: completed` as *reported* success of the named mutation, not proof of
external world state. It only certifies calls under its explicit grammar and
declared tool semantics. `scripts/predict.py` is unchanged.

An independent adversarial audit subsequently found three constructed
false-SAFE counterexamples against the first certificate implementation:
an omitted second condition in a paraphrase, a `customer` policy requirement
silently bound to `case_id`, and a completed replacement *request* treated as
an actual replacement. The implementation now requires an exact policy entity
key and stricter effect-tool descriptions. Model paraphrases cannot authorize
SAFE without exact source equivalence. These fixes preserve the authored
48-case replay and pass 16 targeted tests, but they do not establish general
natural-language policy coverage. See
`POLICY_LANGUAGE_PROBE_2026-09-26.md` for failed wording transfer.

The next credible test is to propose typed clauses from varied policy prose,
then validate each exact source quote and separately account for every policy
paragraph before permitting `SAFE`. Compare the frozen compiler and proposal
front end on a policy-language-disjoint suite, including conjunctions,
read-with-side-effect tools, stale results, missing or contradictory results,
and unrelated IDs. A proposed clause that cannot be grounded must keep the
answer `UNKNOWN`. Promote only after an untouched binary comparison against
the current competition baseline.

## Reproduction

Run `python experiments/searh_23/build_micrograph_controls_v1.py` to verify
the frozen repair artifacts. For each suite, run
`python experiments/searh_23/micrograph_replay_v1.py run repair` and then the
same command with `score` to check predictions against gold. Available suite
names are `repair`, `repair_renamed`, `parcel_v1`, `parcel_v1_renamed`.
`python -m pytest -q tests/test_micrograph_certificate_v1.py` checks edge
cases. Predictions, seals, and per-case scores are in
`outputs/searh_23/micrograph_controls_v1/`.

## Architectural sources

- [Invariant](https://github.com/invariantlabs-ai/invariant): typed ordered
  tool calls and outputs.
- [ToolSandbox](https://github.com/apple-aiml-research/ToolSandbox): milestone
  order, state changes, and renamed-tool controls.
- [Formal runtime verification for tool-using agents](https://github.com/nikos-kekatos/formal-rv-tool-using-llm-agents): typed prior-event witnesses with
  same-entity and temporal constraints.
