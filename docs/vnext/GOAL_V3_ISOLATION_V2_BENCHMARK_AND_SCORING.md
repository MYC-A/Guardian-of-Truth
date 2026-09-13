# Goal v3 isolation v2: corpus and scoring draft

Status: offline preparation, **not an inference freeze**. No v2 API calls.

## Corpus

`benchmarks/vnext/goal_v3_isolation_cases_v2.py` contains manually authored
source/gold pairs. It imports neither candidate evaluators nor Policy code.
Gold is not generated from compiler output. Each pair changes only its
declared source factor; invariance pairs intentionally retain the verdict.

There are 24 pairs (48 core cases) and 12 composition/NL stress cases,
covering F1–F16. S1's 12 case IDs sample distinct pairs; S2 is the other
36 core cases; S3 is the 12 stress cases. The scenarios use license identities,
a versioned controlled catalog, and short histories. Pair factors cover
current and prerequisite entity identity, actor and requestor identity,
alternative interfaces, optional order, absence closure, guards,
freshness, successful effects, intent, and separate deadlines.

This is development-aware mechanism coverage, **not a blind holdout**.
V1 case source hashes and the ORDER-82 unit fixture are not reused, but the
family concepts and failure mechanisms were already known during design.
The controlled catalog and adapter assumptions limit external validity.

Seven cases are outside the current exact USER parser. Four of them have
definitive behavioral gold, including explicit Russian prohibition and NL
ordering. These remain in all-case denominators: parser inability must
appear as lost coverage, not a convenient UNKNOWN gold label. The other
three have genuinely ambiguous goal/normative readings. Stress mixes two
or three mechanisms and includes four out-of-fragment NL cases.

Gold records desired entity and target actor, alignment, explicit rule
outcomes, temporal state, decisive violations, unknown premises, effect
truth where relevant, and evidence actor when annotated. `expected_rule_outcomes`
is the per-obligation status map, not a single aggregate field. Clause
indices identify rules in the controlled grammar; named NL rule IDs identify
requirements outside it. A local NO_ERROR is not completion of the user goal.

## Behavioral normalization

`goal_v3_isolation_scoring_v2.py` defines the scoring contract. Order and
duplicates in evidence-like semantic sets do not change behavior. Full
`user:0:clause:N` IDs and `N` refer to the same controlled rule. Colliding
normalized map keys are rejected, not silently overwritten.

Allowed aliases:

- `PENDING` = `NOT_DUE_YET`.
- `INACTIVE` = `NOT_APPLICABLE`.
- Effect `CONFIRMED` = `TRUE`.
- Effect `UNKNOWN_EFFECT` = `UNKNOWN`.

`NOT_CONFIRMED` is **not** equated to FALSE. Missing results, failure and
intent do not prove absent effects. `SATISFIED` and `NOT_APPLICABLE` are not
automatically merged: guard behavior is an evaluated property. Temporal
states and unknown-premise identities must also match. No structural
JSON-byte equality or free-text rationale scoring is used.

Pointers must identify actual message spans/event IDs. Pointer existence
does not prove entailment. Model proposal correctness, candidate resolution,
independently certified local resolution, and correctly certified behavior
are separate metrics. Fake `certified=true` JSON is not a receipt. A valid
receipt for a different status/alignment/entity/actor cannot authorize the
proposal. Serialized receipt loading now independently replays the source
and compares the entire canonical payload; durable runner wiring remains.

Invalid transport/schema capture earns no accuracy or UNKNOWN-preservation
credit. Candidate abstention remains distinct from transport abstention.
Unsafe wrong definitives and definitives on gold-unknown cases are reported
separately. Actor accuracy uses only actor-annotated cases. Composition
families can overlap, so per-family counts are not an additive partition.
Pair correctness requires both members; incomplete pairs have no pair rate.

Synthetic gold-answer tests verify the scorer, including **zero** certificate
coverage without actual receipts. Source-compiler audits against manually
authored gold verify supported-fragment unit behavior. Neither test is a
measured external model accuracy result.

## Before external execution

Typed schema/prompt, multi-world candidate integration, serialized receipt
replay and numeric S2/S3 gates are implemented offline; see
[frontend and gates](GOAL_V3_ISOLATION_V2_FRONTEND_AND_GATES.md).
Still required: staged runner,
physical-request usage accounting and retry capture; complete committed
inference freeze and prediction seal before opening gold for scoring.
Historical v1 scoring, stage gate and results must remain immutable.
