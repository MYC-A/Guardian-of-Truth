# Semantic hybrid V4

Start with [the architecture decision](FINAL_DECISION.md). The implemented lazy
and reverse pipelines did not outperform the contextual baseline; a promising
post-hoc chronology filter failed its prospective test. This branch preserves
the negative results and the supporting raw receipts, without production changes.

- [Experiment results and comparison tables](EXPERIMENT_RESULTS.md)
- [Failure audit with concrete cases](FAILURE_ANALYSIS.md)
- [Actual costs and transport behavior](COST_AND_TRANSPORT.md)
- [Offline reproduction](RUNBOOK.md)
- [Repository audit](REPOSITORY_AUDIT.md)
- [Frozen primary protocol](BENCHMARK_PROTOCOL.md)
- [Historical baselines](BASELINES.md)
- [Implemented architecture boundaries](ARCHITECTURE_CANDIDATES.md)
- [Verified research transfers](RESEARCH_TRANSFER.md)
- [Second-model replication protocol](SECOND_MODEL_PROTOCOL.md)
- [Development address controls](ID_CONTROL_PROTOCOL.md)

Research code: `experiments/research_v3/`. New phase artifacts:
`outputs/searh_23/semantic_hybrid_v4*_20261004/`.
The original runtime source is pinned at
`fd575bc29115680235b631e6339ca0903c0f63d1`; later adapters have their own seals.
New cases are author-controlled synthetic families, not externally blinded data.

85 targeted tests pass. The runbook verifies all seven phase prediction files
byte-for-byte with unchanged HTTP ledgers, then regenerates metrics and audits
with no new inference. Actual unique HTTP attempts: 231; known tokens: 420,540;
conservative charged tokens: 459,588; automatic retries: zero.
