# Retrieval bakeoff V1

The bounded research is retained on `research/retrieval-bakeoff-v1-20261004`.
Fifteen original known cases, 600 offline packets, 15 API calls and 90,419 actual
tokens do not establish a cause-correct operational binary improvement. B1 is
the frozen development choice; existing local BM25 remains a competitive simple
baseline. S2G-inspired retrieval recovers two real Silver facts but its final
review is not admitted. Production and historical data are unchanged.

Start with [FINAL_DECISION.md](FINAL_DECISION.md) for all twelve answers and one
minimal proposed API. [RETRIEVAL_COMPARISON.md](RETRIEVAL_COMPARISON.md) contains
all ten methods at four budgets; [SOURCE_COVERAGE.md](SOURCE_COVERAGE.md) audits
missing evidence and alternative sets. Model effects are separated into
[LLM_IMPACT.md](LLM_IMPACT.md), [S2G_RAG_EVALUATION.md](S2G_RAG_EVALUATION.md),
and the independent [CAUSAL_AUDIT.md](CAUSAL_AUDIT.md).

[REPOSITORY_REUSE.md](REPOSITORY_REUSE.md) inspects six pinned upstream projects;
[DATASET.md](DATASET.md) preserves labels, source references and known-case
limitations; [BASELINE.md](BASELINE.md) exposes A's unsupported interface.
[PROTOCOL.md](PROTOCOL.md), [RUNBOOK.md](RUNBOOK.md), [VALIDATION.md](VALIDATION.md)
and [COMPLETION_AUDIT.md](COMPLETION_AUDIT.md) retain freeze, replay, tests,
independent reviews and publication requirements. Raw requests/replies and all
metrics are in [outputs/retrieval_bakeoff_v1](../../outputs/retrieval_bakeoff_v1).

Unresolved defects and limits include native prefixed receipt classification,
actor/norm-scope errors, fabricated ZIP missed by reviews, two bank081 reference
enum annotations, BM25 query-weight confounding, incomplete negative references
and lack of independent holdout. None was patched into the frozen phase.
