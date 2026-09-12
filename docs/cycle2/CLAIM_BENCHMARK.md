# Response-only claim benchmark

Cycle 2 freezes 209 response spans across 86 candidate responses and 11 domain
labels. The external portion contains all 169 assistant spans from the 46 rows in
`valid.parquet`; parquet projection loads only `id` and `response`. The other 40
spans are controlled minimal pairs, including 26 with independently known
supported/unsupported status. No prompt, history, tool result, policy, row label,
or explanation is extractor input.

Every span has an explicit disposition. The 152 declarative spans are annotated
as one of `ACTION_COMPLETED`, `ACTION_FAILED`, `STATE`, `ATTRIBUTION`, `INTENT`,
`REFUSAL`, `FACT`, `ABSENCE`, `PERMISSION`, or `OTHER_VERIFIABLE`; 57 questions,
requests, social utterances, and list markers are `NON_VERIFIABLE`. Gold also
contains entity, time, and source fields. Offsets are validated against the exact
response bytes and the cases hash is checked on load.

The annotation is rule-assisted semantic curation, not an independent human
double annotation. This is a limitation and should be addressed before claiming
benchmark-grade absolute numbers. Controlled minimal pairs make the relative
coverage test useful now, while the limitation remains explicit.

## C0 result

The frozen incumbent deterministic blind extractor found 16 spans, of which 15
matched a verifiable gold span: precision `0.9375`, recall `0.1020`, and kind
accuracy `0.8667` on matched spans. Unsupported-claim recall is `0.0769` (1/13).
Coverage bookkeeping is `1.0` because every declarative span is explicitly
`CLAIM`, `NON_VERIFIABLE`, or `UNKNOWN`; this does not compensate for low claim
recall. C0 therefore remains a conservative high-precision extractor, not a
complete X5 claim front end.

## Frozen C1/C2 result

All 172 remote calls ran sequentially in the predeclared order C1 then C2 for
each of 86 responses. The output schema was embedded in prompt text; provider
native structured-output mode was not used. No failed or invalid answer was
repaired or retried.

| Arm | Transport success | Schema valid | Span recall | Span precision | Unsupported recall |
|---|---:|---:|---:|---:|---:|
| C0 deterministic | 86/86 | 86/86 | 0.1020 | 0.9375 | 0.0769 |
| C1 direct offsets | 73/86 | 55/86 | 0.0068 | 0.0073 | 0.0000 |
| C2 span inventory + typed map | 86/86 | 83/86 | 0.8163 | 0.9449 | 0.9231 |

C1 had 13 truncated transports and 18 schema-invalid responses. Its semantic
failure is chiefly a boundary-coordinate failure: it predicts many plausible
claims but almost never reproduces exact response offsets. C2 removes that
unstable subproblem by constructing the response-only sentence inventory
deterministically and asking the model to type every supplied span. It raises
matched-span recall from C0's 15/147 to 120/147 while retaining high precision.

C2 is the clearest positive Cycle 2 result, but it is not yet a complete claim
verifier. On its 120 matched spans, kind accuracy is 0.5083, entity accuracy
0.5, time accuracy 0.5357, and source accuracy 0.2667. The next improvement must
therefore target typed semantics and source/entity normalization, not another
free-form span generator.

Operationally, C1 used 120,605 reported tokens with latency p50 15.75 s and p95
38.55 s. C2 used 106,779 tokens with p50 13.75 s and p95 34.29 s. Provider cost
is not claimed because the billing basis was not independently audited.
