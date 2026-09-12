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
