# Retrieval corrections V2 — new phase, 2026-10-05

Research branch `research/retrieval-corrections-v2-20261004`, based on exact
multi-packet commit `a7a113e71591a7b37df78a2b2485fbb6b79aa415`.
Historical Facet Cover is imported from `98b7fd2bb034e535858d2d7bde05b652abe115f1`.
Production/main, original valid46 labels, SYN labels and historical artifacts stay unchanged.

## Offline audit before inference

Compare old/new U2 for all 46 original rows at 20k, 40k, 48k, 80k source bytes
and unbounded input. Compare old/new Facet Cover on the 15 existing addressed
reference cases at the same finite budgets. Check exact serialized source cost,
strict corrected U2 provenance, complete union coverage of reference spans and
explicit receipt/parent diagnostics. Historical Facet Cover is nondeterministic;
its baseline uses the predeclared `PYTHONHASHSEED=0`. Corrected selection is
separately tested under seeds 0/1/7/11/91.

Complete reference sets are diagnostic source coverage, not independent semantic
proof and not proof of absence in an incomplete journal. FULL_INPUT covers every
parsed source-event span, including the full original catalog; parser transport
headers, outer markers and trimmed whitespace are delimiters outside that claim.

## Bounded reviewer check

Pinned reviewer `ministral-14b-2512`, unchanged I4 prompt/schema/ID-and-actor
admission, temperature 0, max output 1700 tokens. Each arm sees exact sources
through the same review_packet function and subset-absence contract.
All request bodies, source/audit hashes and code hashes are committed before API use.

At most nine pairs / **18 requests / 130000 charged tokens**. Durable reservations
precede network access; unknown usage remains conservatively charged. Context
limit 262144 is checked conservatively, without truncation. Timeout 120 seconds,
one attempt, no retries or replacement models; a provider failure stops that provider.
Raw requests, raw responses, request hashes and usage ledger are retained.

Selection is conditional diagnostic sampling: at 20k, source-changing requests
of at most 30000 serialized bytes. For each of U2 and FC, choose up to two
known-positive and one known-negative valid rows, ranking complete-set gain,
then policy/history coverage gain, then id. The three-row per-family metrics
must not be presented as valid46 F1 or merged across methods as independent cases.

For C1 P2 choose up to two positive and one negative existing SYN rows where
ordinary complementary selection has no POLICY, corrected selection has POLICY
and genuinely new units. Both use the same corrected U2 first packet, isolating
shared normative context. The old P2 request is deliberately replayed as the
historical unguarded behavior. This compares second-stage admission/decisions;
it **does not measure the final C1 pipeline F1**. FULL/no-new guards are verified offline.

Labels, explanations and reference spans are evaluation-only. No row IDs/tool
business rules enter selectors. UNKNOWN and technical null project to binary 0;
both counts are reported separately. Incomplete/duplicate paired results are rejected.
Case ordering alternates OLD/NEW to avoid running all of one arm first.

## Interpretation and independent cause audit

All valid46 examples and references are previously used diagnostic data; SYN is
synthetic and also previously used. This phase has no independent holdout and
one reviewer sample per distinct request. Small binary gains and losses require
original-source cause review and do not establish statistical generalization.
Independent subagents review code and the meaning of any observed decision changes.
The separate cause audit remains unmeasured until every claimed improvement has
been checked against the original policy, scope, current action and tool evidence.
Historical SAME/PARTIAL reason-judge matches are gold-explanation proxies, not
source-supported proof; they are never promoted to new cause correctness.

Reproduction: set `PYTHONPATH=.:src`, `PYTHONHASHSEED=0`, then run
`python -m experiments.retrieval_corrections_v2.offline`,
`python -m experiments.retrieval_corrections_v2.historical_audit`,
`python -m experiments.retrieval_corrections_v2.runner prepare`.
Use `runner run --live` only for the bounded phase; `runner run` afterwards
replays validated caches with zero new HTTP. `runner report` rejects changed
code/data/requests or an incomplete paired inventory.
