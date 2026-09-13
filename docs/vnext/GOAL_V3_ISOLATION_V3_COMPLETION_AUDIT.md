# Goal-only decision experiment: completion audit

Scope is the attached isolated Goal v3 decision experiment, NOT successful
Goal+Policy/Core implementation. A preregistered REJECT_EARLY is an allowed
terminal outcome. Completing the decision does not imply passing semantics.

## Requirement-to-evidence check

| Attachment items | Authoritative evidence | Result |
| --- | --- | --- |
| 0: repository/HEAD/version/code-doc divergence/existing baseline | GOAL_V3_ISOLATION_REPOSITORY_AUDIT.md, original fetched HEAD 48b84e3; current implementation 889a7ac, freeze 43add4f | Audited; divergences disclosed, no silent redesign |
| 1–3: Goal versus plan, alignment categories, G1–G10 | Versioned v2 semantics/execution reused; v3 inference freeze source hashes; 1496 project tests; S1 component scores | Prepared and tested offline; external semantic failures explicitly reported |
| 4: Policy isolation | prompt_messages_v3 delegates Goal-only rejection boundary; runner has no policy input; offline injection tests | No Policy parser/verdict/features consumed |
| 5: zero calls before freeze | 889a7ac source commit, 43add4f complete freeze commit, subsequent batch tool invocation | Freeze preceded first inference |
| 6–10: 24 pairs/48 core +12 stress, F1–F16, behavioral authored gold | exact v2 corpus/gold reused; v3 inputs/gold/freeze; offline assertions 60 IDs, 24 pairs, stages12/36/12, all16 families | Complete prepared inventory, no blind-holdout claim |
| 11–14: one semantic inference, compact typed output, provenance, no critics/judges | CONFIG, immutable 12 request/result captures, S1 independent receipt audit | 12 requests/12 deliveries, zero retry/judge/challenger; all exact JSON; pointer failures retained |
| 15–18: batch wait, one-case requests, fixed concurrency/prefix | one live session37577 waited until exit0; frozen serial config, no per-request rescoring | No restart or prompt adaptation; caching savings unknown |
| 19–20: staged execution, preregistered stop | frozen gates/protocol, sealed S1 boundary/results | REJECT_EARLY; S2/S3 not admitted; no ad-hoc stop |
| 21–24: all named metrics, safety AND coverage, pairs/numerical gates | S1_results metrics/case_scores/by_family/admission; report sections5–10 | Computed; unmeasured pairs/families/core/stress explicitly null/NOT_RUN |
| 25–26: permitted verdict and no mid-run fix | S1_results admission, source/hash replay checks | REJECT_EARLY; no frozen source/prompt/gold/scorer/gate changes |
| 27–28: seal before gold, deterministic failure audit | S1 prediction_seal, physical replay, independent receipt audit, component audit | Verified; zero model calls for audit; no repaired/rescored predictions |
| 29: requests/tokens/cost and historical comparison | S1 cost:12 cases/12 requests/0retry,22555input/5946output/28501total,2375.08 per case; report baseline section | Complete reported usage; financial cost not provided; no invented pricing |
| 30: missing frontend/minimal spec implementation and assumptions | original repository audit; v2 versioned implementation; v3 protocol explicitly format-only | Restricted grammar/trusted fixture assumptions retained and disclosed |
| 31: composition only on KEEP | S1 verdict REJECT_EARLY; S2/S3 fail closed before env/network | KEEP condition not triggered; no composition promotion |
| 32: all14 report items and Q1–Q8 | GOAL_V3_ISOLATION_V3_RESULTS.md sections1–14 | Delivered with negative/limited evidence, no whole-Core claim |

Latest verification: 1496 passed in10.64s; v3 freeze/replay score intact;
independent gold-free physical audit passed; original isolation v1/v2 freezes
intact. Historical Goal/Plan v2's113 frozen sources are hash-verified intact;
its stored outputs/status document have no diff from pre-v3 d378940.

The source/format intervention is completed as a **rejected candidate**.
The original question has no positive coverage/integration answer from this
candidate. General NL, real source-authority/trace binding, unattempted F1–F16
members and composition remain unproven, not secretly substituted with a
fixture-only success. A new semantic hypothesis is a separate future task;
the frozen answers and historical results are not rewritten to improve metrics.
