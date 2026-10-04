# Independent completion audit

This audit checks the full retrieval-research request in the adopted attachment,
not only the implemented adapter tests. It performed no inference, selector
retuning, code/fixture modification or production integration. A completed
experiment may have negative results and explicit limitations; it must not turn
those into evidence of an unobserved improvement.

## Verified authoritative state

- Protocol SHA256 is internally valid:
  `4a4c4bb630aac8108afe93d91a73e5eec55af884f35ca9c421ed2bf39d1ea5d5`.
- All **298 frozen code/input/reference fingerprints** match current files;
  the original parquet SHA256 also matches the seal.
- **600 saved offline packets** exist: 15 original cases, ten methods, four
  read/token settings. The independent source audit checks all600 with no source,
  score or aggregate discrepancy; targets are retained in all600.
- Every retained raw response matches its ledger SHA256. All15 request bodies
  match their exact serialized wire hash and protocol identity. Verified usage
  sums independently to **90,419 known = charged tokens** across **15 attempts**;
  every response is OK and reports `ministral-14b-2512`. No unknown usage exists.
- The saved replay is PASS with zero new inference HTTP. It reconstructs both
  valid gap plans and the rejected Retail plan, as well as retained semantic
  decoding. [Replay evidence](../../outputs/retrieval_bakeoff_v1/offline_replay.json).
- The regression receipt records **103 passing relevant tests**.
  [Exact test output](../../outputs/retrieval_bakeoff_v1/regression_tests.txt),
  [reproduction commands](RUNBOOK.md). This completion auditor inspected the
  receipt; it did not independently rerun that entire suite.
- A diff against `f89d271b21deeb5e2820a8c9111857223ca26015` returned no changed
  production/source dataset or inherited hybrid/V5/Telecom implementation paths.

## Requirement-by-requirement assessment

| Request scope | Status | Current evidence and practical limit |
|---|---|---|
| Separate worktree/branch from prescribed base | PASS | Current research worktree and branch preserve the original code; commits start after f89d. No full Guardian implementation is attempted. |
| Study existing Selector, SourceStore, graph, exact references, actor and receipt logic | PASS | [REPOSITORY_REUSE.md](REPOSITORY_REUSE.md), [CODE_REVIEW.md](CODE_REVIEW.md), original imports and independent saved-packet audit. |
| Inspect actual upstream BM25S, LlamaIndex, PageIndex, GraphRAG, HippoRAG, S2G code/dependencies | PASS WITH EXECUTION LIMITS | Pinned upstream code and dependency table in REPOSITORY_REUSE plus library-audit JSON. Only BM25S is executed as a library; other frameworks are not presented as implemented benchmark arms. |
| Select approximately12–20 multi-domain original cases with source-grounded alternative references | PASS WITH REFERENCE LIMITS | Fifteen cases across airline, banking, retail and Telecom;8 dev/7 known evaluation,9 original positives/6 negatives. Long histories, prose, multi-calls, actor/order/ID/exception distinctions are represented. Two references remain partial; known evaluation is not an independent holdout. |
| Keep original labels, inputs and runtime/reference separation | PASS | Input/parquet and reference seals match; loader returns original id/prompt/response/split, while adapter reads prompt/response only. Development scoring selects hypotheses explicitly; no evaluation retuning. |
| Run unchanged A and retain its incompatible cases | PASS WITH BASELINE LIMIT | Original coverage_plan is imported unchanged.13/15 inputs are unsupported. Intrinsic eight-read limit remains unchanged at12. Raw credit from mandatory declarations is separated from operational success. |
| Actual BM25S B1/B2/B3 and inherited lexical baseline | PASS WITH COMPARABILITY LIMIT | Actual BM25S0.3.12; common Unicode tokenization; no default stemming/stopword removal. Query multiplicity differs from the inherited local function and is disclosed in a separate frozen-results-preserving diagnostic. |
| Exact/graph ablations, fusion and coverage selection | PASS WITH SEMANTIC LIMIT | Round-robin and RRF controls plus generic diversity selection. Existing unique receipts/co-recorded graph are reused without ownership, permission, freshness or semantic-identity proof. No fixed two-policy/three-pair quota. |
| Compare8/12 reads and token-capped packets honestly | PASS | Four settings, same new catalog, exact serialized source-array cost, mandatory target/declaration accounting. A whole sources and new explicit windows are different read units; costs remain visible. No invisible text pruning. |
| Critical recall, alternatives, entity/long-distance/exception coverage and false-absence risk | PASS WITH INTERPRETATION LIMIT | Independent all600 span/alternative/category audits. These are reference-relative metrics, not normative completeness, binary F1 or proof that a missing event was absent from the full input. |
| One fixed LLM with identical review interface across selected retrieval arms | PASS WITH NEGATIVE RESULT | Frozen model inputs committed before inference. Impact uses5 unique calls/22,174 tokens; supported A comparison does not improve. Correct binary labels with wrong or ungrounded causes are not credited as recovery. |
| Mandatory concluding official S2G audit and S0/S1/S2 diagnostic | PASS WITH OFFICIAL-METHOD LIMIT | Official local base/LoRA judge is not executed; API method is explicitly S2G_INSPIRED_API_BASED. Three development cases include missed sets and a complete-reference control; total reads/source-bound match and seed retention is checked. |
| Measure concrete gap recovery, erroneous gaps, repeated reads, sufficiency, cost and final causes | PASS WITH ADMISSION LIMIT | Silver adds two necessary original facts, but its final actor attribution is rejected; Banking adds no critical facts and reaches semantic UNKNOWN; Retail invalid namespace blocks its final call. No mandatory-controller improvement is established. |
| Enforce18 requests/130k tokens, no retries/fallback/weights | PASS |15 requests/90,419 verified tokens, one prescribed provider/model, reservations and retained cache reuse. Zero weight downloads/training/local model server. Metadata research GETs are not inference calls. |
| Regression tests, independent logic/source audit, replay, preserve negatives | PASS |103 tests; independent code/coverage audits; causal reports; exact-wire/raw integrity and reconstructed controller replay. Frozen defects are disclosed rather than patched after evaluation. |
| Required reports, final minimum retrieval recommendation and all12 final questions | FINAL DOCUMENT CLOSURE REQUIRED | Core reports are present. FINAL_DECISION and VALIDATION were being written when this independent audit began; verify their final contents and all links before declaring the entire request complete. |
| Final commit/push, branch/report links and then stop | FINAL PUBLICATION REQUIRED | Prior freeze/model-input/impact commits exist. The final results/report commit, remote HEAD equality and clean working state must be verified by the parent after all reviewers finish. |

## Claims that must remain constrained

The selected B1 gets2/8 operational development alternatives and1/7 known-
evaluation alternatives at eight reads. Local BM25 gets1/8 and3/7, respectively.
On the two inputs actually supported by A, A obtains1/2 complete alternatives
while B1 obtains0/2. The broader cross-domain counts therefore do not prove
B1 improves the original Selector under a matched supported-case comparison.
Method selection remains development-only despite the known-evaluation ranking.

All six original negative cases fail the curated complete-set criterion under
every offline arm/budget. That class asymmetry is a reference/coverage limitation,
not measured binary accuracy or a claim that every negative must fail review.
No new independent holdout or full-valid46 F1 improvement is reported.

The frozen Banking081 reference contains two declaration-enum spans mistakenly
credited as normative reason semantics. The independent post-freeze sidecar
excludes them for sensitivity reporting without changing frozen references,
selection or raw scores. Its local four-request permission is not a whole-move
NO_ERROR certificate. Separately the frozen review presentation misclassifies
native prefixed JSON receipts as normative candidates. Neither defect invalidates
exact-span fidelity; both limit semantic-quality claims. Their causal effect has
not been isolated by a corrected rerun.

The BM25 post-hoc diagnostic makes deduplicated BM25S queries rank identically
to the inherited local function across all15 corpora. The original frozen B2
retains repeated-token weighting. This diagnostic is not a replacement arm or
a library-ranking win, and cannot justify an evaluation-driven method change.

Official S2G, semantic embeddings, full PageIndex/GraphRAG/HippoRAG integration
and independent unseen-domain reliability remain untested. Heavy integrations
are reasonably deferred under the requested short-cycle constraints. The final
recommendation should choose a minimal experimental retrieval interface,
describe unresolved failure/extra-search conditions and avoid guaranteeing
NO_ERROR from coverage heuristics or a model sufficient=true flag.

## Completion boundary

The empirical research stages, retained evidence and numerical budget are
verified above. At this writing, publication and final-document closure remain
the parent's required final steps. This auditor does not mark the user goal
complete or authorize production integration. Final closure must inspect the
actual completed reports, final commit and remote branch rather than relying
on this checklist or an intended push.

## Parent closure after the independent audit

The parent subsequently inspected all eight requested reports plus VALIDATION,
CAUSAL_AUDIT and MODEL_STAGE_REVIEW. All twelve final questions and the minimal
API are present. Automated closure verified all local report links, the 610-file
input seal, all 298 frozen fingerprints, protected-history/production paths,
zero-HTTP replay and the 15/90,419 accounting. Evidence is
[research_closure_check.json](../../outputs/retrieval_bakeoff_v1/research_closure_check.json).
The logic reviewer found no blocking overclaim; the code reviewer independently
replayed the model/controller stage and confirmed the preserved interface defect.
This parent addendum does not rewrite the independent auditor's earlier snapshot.

Results and causal artifacts were committed/pushed in `125ce04b`. The remaining
publication step is to commit these final reports and verify remote HEAD equality
and a clean working tree; that check is performed after the report commit rather
than inserting a recursive final commit hash into this file.
