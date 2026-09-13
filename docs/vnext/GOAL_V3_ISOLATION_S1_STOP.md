# Goal v3 isolation v1: S1 result and stopped-run record

This is a **partial**, Goal-only experiment, not a completed 60-case score or a
preregistered `REJECT_EARLY`. S1 predictions were sealed before gold was joined.
The 36 remaining core cases and 12 stress cases are `NOT_RUN`; they must not be
counted as errors or silently inferred from the observed sample.

Evaluated semantic frontend and runner commit:
`d52d278985c65e7002cf6fb7ea756e3105bea976`. Origin of the existing
structured Goal v3 kernel: `48b84e3875b960d43956576735d543e8c4e5917b`.
Prompt SHA-256: `bfc825d47e6733f08e73d93e58dd61b78010fd671724477def39ac70674cd6ed`.
Schema SHA-256: `7ab960a03fda7951549591c5d23569b6e42481014355eda97797c97f43ff87fa`.
The exact schema, provider settings, retry rules and source hashes are in
`outputs/vnext/goal_v3_isolation_v1_inference_freeze.json`.

| Sealed S1 measure | Result |
| --- | ---: |
| Cases / physical requests / retries | 12 / 12 / 0 |
| Successful transport / valid schema | 12 / 12 |
| Correct candidate status | 9/12 |
| Full behavioral correctness | 0/12 |
| Alignment / obligation / temporal correctness | 12/12 / 4/12 / 6/12 |
| Unsupported definitive on gold UNKNOWN/BOTH | 0 |
| Candidate / certified definitive coverage | 6/12 / 0/12 |
| Reported input / output / total tokens | 10,600 / 58,542 / 69,142 |

The provider reported 58,542 output tokens although the frozen request set
`max_tokens=512` for each of 12 cases. The reason is not established: hidden
reasoning, provider accounting, or cap handling must not be guessed from this
experiment. The reported amount is provider-side usage, **not Codex tokens**.
Cost in money is not audited. At the observed usage, completing all 60 cases
would require about 346k reported provider tokens if usage stayed similar;
that is an extrapolation, not a measured cost.

The frozen S1 admission rule technically **passed** (12/12 usable schema,
9/12 exact scoped statuses, zero unsafe definitive), so its stored
`admit_S2=true` remains unchanged. However S1 sampled one member of each of
12 distinct minimal pairs, and **all 12 members failed** full behavioral
correctness. Each of those 12 pairs therefore cannot pass the frozen
both-members-correct metric. Even if all other cases were perfect, the 48-case
core could score at most **12/24 = 50% correct pairs**, below the frozen 90%
gate (at least 22/24). S3 admission and KEEP are mathematically impossible
under this v1 scorer.
The independent offline replay in
`outputs/vnext/goal_v3_isolation_v1_S1_bound_audit.json` verifies the freeze,
prediction seal, scored metrics, 12 distinct failed pairs and this upper
bound without making any API request.

The run was stopped at the S1 boundary after the user raised token-spend
concerns and this deterministic futility bound was established. **This stop
was not preregistered**; it must not be relabeled as `REJECT_EARLY`, and it
does not produce a formal S2/S3 verdict. The supported decision is that this
candidate cannot meet the frozen KEEP criteria, while 48 cases remain
unmeasured. A new version may preregister a futility/cost gate and investigate
the dominant semantic mismatches and provider token accounting; the v1
prompt, schema, scorer and predictions must remain untouched.

Historical Goal v2 was 22/22 UNRESOLVED, zero definitive certificates,
190 requests and 361,883 reported tokens on **different** cases. This S1
candidate gives no certified USER-goal verdicts, so no valid paired coverage
improvement over v2 has been established. It is not ready for Goal+Policy/Core
composition testing. No Policy parser, Policy verdict or Policy input
participated in this Goal-only run.

## Deterministic failure interpretation after sealing

The 0/12 result is **under this frozen scorer**, not evidence that all 12
semantic judgements were wholly wrong. Source-ID/entity/actor/effect grounding
passed 12/12, alignment matched 12/12 and exact candidate status matched
9/12. Field agreement was weaker: obligation 4/12 and temporal 6/12.
The scorer requires exact obligation/temporal enums for `behavioral_correct`.
Its preregistration promised behavioral equivalence, but the prompt/schema
do not fully define, for example, whether an out-of-scope action should set
`obligation_status=VIOLATED` or `NOT_APPLICABLE`, or whether
`UNKNOWN_EFFECT` and `NOT_ESTABLISHED` are equivalent for a merely attempted
mutation. This is a **measurement ambiguity**, not a license to rescore v1.

Representative sealed failures:

- `P01:b`, `P05:b`, `P06:b`, `P14:b`: correct `PROVED_ERROR` and alignment,
  but model `VIOLATED` versus gold `NOT_APPLICABLE` on the obligation axis.
  The v1 field contract did not make that distinction explicit enough.
- `P03:a`: all scored semantic fields except final status matched; extra
  `GOAL_OPEN,EFFECT_UNKNOWN` caused `_candidate_status` to return
  `UNRESOLVED` for a permitted auxiliary read. This exposes blanket UNKNOWN
  propagation in the candidate aggregation.
- `P12:a`: the true conditional cache guard and required prior step were
  not preserved; the candidate produced `BOTH` and `PREREQUISITE` rather
  than the gold `VIOLATED` and `GUARD` distinction.
- `P24:b`: candidate status was right, but the evidence actor was wrong.
  Actor-source membership validation did not establish the actor of the
  *relevant prerequisite*.

Among the 12 S1 cases, gold-UNKNOWN preservation was 3/3, false mandatory
plan violations 0, explicit-obligation exact recall 2/4, independent
violation status recall 1/1, wrong-entity status detection 1/1, and annotated
actor accuracy 0/1. These tiny denominators are diagnostics, not broad
generalization claims. No intent-versus-completion case was in S1.

### Questions from the Goal-only objective, limited to S1 evidence

| Question | Supported S1 conclusion |
| --- | --- |
| Q1, invented mandatory plan | None observed in S1; alternative-path status still failed in `P02:b`. General claim unproven. |
| Q2, explicit obligations | 2/4 exact in S1; insufficient for the 90% target. |
| Q3, future vs violated | No false future ERROR, but temporal field mismatches; distinction not reliably demonstrated. |
| Q4, independent violation with unrelated UNKNOWN | Correct on the single observed case; not a general certificate. |
| Q5, unknown decisive premise | Three gold-UNRESOLVED cases stayed UNRESOLVED; guard-specific semantics were not all correct. |
| Q6, actor/entity/intent/effect | Wrong entity 1/1, actor 0/1, failed-call status 1/1; intent/completion not measured. |
| Q7, coverage over v2 without unsafe growth | Candidate definitive 6/12 and unsafe 0/3, but certified definitive 0 and benchmarks differ; improvement unproven. |
| Q8, integration readiness | No: no general USER-goal authority certificate and frozen pair gate cannot pass. |

The next version, if pursued, should be a *new* preregistered experiment with
an explicit field ontology, source-grounded relevance of UNKNOWN, a scorer
that accepts documented behavioral equivalences, and a transport usage/futility
limit. Its evaluation must not rewrite v1 predictions, labels or gates or
pretend the remaining 48 v1 cases were run.
