# Guardian semantic grounding V5

**No automatic improvement demonstrated; decision: NEEDS_MORE_EVIDENCE.**
The original 46-row binary task now anchors the research. Original V4 gold/results
and the partial pre-steering prototype are preserved. Four full-source model calls
cost 72,543 tokens; the narrow automatic mapper failed source/role selection and
missed a real prohibition. No production change or large follow-up run.

- [Final decision and all 15 V5 answers](FINAL_DECISION.md)
- [Binary label, valid46 baseline and R0 context audit](BINARY_METHOD_AUDIT.md)
- [Source-grounded real-FN process oracle](ORACLE_PROCESS_RESULTS.md)
- [Fresh paired model results, wrong-cause audit and costs](MODEL_RESULTS.md)
- [Actual implemented relation boundary](ACTIVE_RELATION_DESIGN.md)
- [Tested contrasts and gaps](CONTRASTIVE_TESTS.md)
- [Offline runbook](RUNBOOK.md)
- [Initial repository audit](REPOSITORY_AUDIT.md)
- [Historical initial V5 protocol](BENCHMARK_PROTOCOL.md)
- [User's binary-task steering checkpoint](METHODOLOGY_STEERING.md)
- [Pre-inference diagnostic protocol](NEXT_DIAGNOSTIC_PROTOCOL.md)
- [Preserved first preparation and budget-based order revision](PREFLIGHT_REVISION.md)

Research code is under `experiments/research_v5/`; post-hoc and portable replay
tools are under `tools/`. New artifacts are under `outputs/research_v5/`.
Model source is pinned at `b33c77137db56a4f9b874403a4a3ff385ad7bd11`.
Server and Windows replay are byte-identical with unchanged HTTP ledger. 151
relevant deterministic tests pass. New stages were committed and pushed separately.
