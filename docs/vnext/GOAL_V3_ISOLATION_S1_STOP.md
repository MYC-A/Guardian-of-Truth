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
