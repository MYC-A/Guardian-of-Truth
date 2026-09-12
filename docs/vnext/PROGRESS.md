# vNext progress — protocol checkpoint

This is not the final decision. The offline T1 fixture stage has run; model
semantic stages and blind evaluation have not run.

Completed: isolated branch from 0199bf9; BAI integration imported without changing
incumbents; protocol/requirements; five controlled stage extensions; new pinned
150-case metadata-selected holdout excluding Cycle 2; separate ignored gold
storage; immutable input hashes and pre-gold prediction-seal utilities.

Stage counts: claim graph 41, policy Phi 16, Goal/Plan 22, tool semantics 18,
binding/temporal 32. The extension has partially annotated relation/duplicate-name
cases; score only explicitly annotated fields with disclosed denominators, never
invent unannotated gold. The old 209-span set supplies unsupported-claim regression
gold; the new response-only extension cannot establish unsupported truth alone.

The freeze manifest is a protocol/benchmark freeze, NOT a blind candidate freeze.
Prompts, executable schemas and final architecture commit must be separately
sealed before major evaluation. Historical BAI gate: 15/16 transport/schema,
14/15 semantic correctness conditional on valid response, one 429; a fresh gate
is still required before blind network predictions.

Implemented since the protocol checkpoint: immutable canonical types; strict
call/result normalization; append-only field observations and temporal queries;
all seven retrieval indexes and no top-k cap; ten-pass typed Claim Graph with
explicit unknown dispositions; policy candidates plus challenger with authoritative
closed-universe boundary; separate Goal/Plan parser; conditional version/hash-bound
T1 and grounded nontrusted T2; indexed Binder retaining duplicate-name ambiguity.
These are implementations with unit tests, NOT established model semantic gains.

Full project test command: `python -m pytest tests -q`: 726 passed.
Frozen offline T1 stage: 16/16 applicable cases exact; two missing-contract cases
NOT_APPLICABLE_T1; false no-effect=0; false causal action confirmation=0.
Real-world tool generalization and downstream gain remain NOT_ESTABLISHED.

Remaining: temporal/causal proof primitives, independent certificates,
core/escalation/adapters; all model semantic stage evaluations, stage integration,
regression and dev-only ablations;
candidate freeze; fresh gate; sealed blind predictions/gold join; all result JSON,
certificate JSONL, failure audit, result documents, final manifest and final decision.
The 23 requirement rows remain unverified until their authoritative evidence exists.

Checkpoint commits: protocol `8e9c3fb`; types/ledger `8e87649`; Claim Graph
`e69a406`; T1/T2 `9e0b2f4`; policy/Goal `f0fb124`; indexed Binder `f562c8b`;
T1 evaluator `8d2c532`; T1 pre-prediction freeze `af2e3ee`.
