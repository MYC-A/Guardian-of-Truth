# Validation and immutable phases

Research branch `research/retrieval-bakeoff-v1-20261004` starts at
`f89d271b21deeb5e2820a8c9111857223ca26015` in an isolated worktree. Historical
experiments, production code/dependencies and original valid.parquet have zero
diff against that base. The only shared-root change is four `.gitattributes`
LF rules confined to this research's new paths. No production integration ran.

| Check | Actual result / retained evidence |
|---|---|
| Freeze before evaluation | `968a49f1`: runtime, 15 cases, references, package pins and protocol committed/pushed before scoring |
| Freeze before inference | `0c5c7b19`: 600 packets, selection, model plan, exact prepared requests and 610-file byte seal committed/pushed |
| Impact checkpoint | `aea82eb3`: raw replies/requests/ledger and zero-HTTP replay committed/pushed |
| S2G checkpoint | `125ce04b`: full bounded S2G raw replies/requests, packets, source metrics and independent causal artifact committed/pushed |
| Protocol | SHA256 `4a4c4bb630aac8108afe93d91a73e5eec55af884f35ca9c421ed2bf39d1ea5d5`; original sources, code/fixtures and package versions verified before model stages |
| Reference addressability | 245 memberships / 110 distinct per-case spans match original text hashes; gold never enters runtime inputs |
| Independent offline code audit | 600 packets, 6,254 source records, 80 groups; zero text/hash/offset/actor/cost/metric discrepancies |
| Independent coverage audit | All 600 interval-union and known-alternative scores and 80 aggregates independently reproduced |
| Semantic reference limitation | Two bank081 enum spans are not normative semantics; separate qualified sidecar, frozen references unchanged |
| Query diagnostic | Query-deduplicated BM25S and old BM25 have identical full ranks on 15/15; original B2 repeated weights preserved |
| Post-inference input seal | All 610 exact frozen model-input bytes preserved on local/server; no retuned selector or replacement packet |
| S2G source integrity | Eight admitted source packets match their original catalog records, <=12 reads and <=20k source bound; all retain seed |
| Independent model-stage code audit | Eight packets / 94 source records, 15 wire/raw records, all 610 sealed inputs; separate temporary-copy replay PASS with zero HTTP; prefix classification defect confirmed in two actual requests |
| Model accounting | 15 requests/raw records; actual returned model `ministral-14b-2512` throughout; known=charged 90,419 tokens, zero unknown usage; 18/130k ceilings respected |
| Controller replay | Reconstructs Silver/bank valid plans and Retail atomic invalid stop; zero inference HTTP on Windows and Linux |
| Admission replay | Original provider-qualified wire/body/raw/ledger hashes and all saved final admissions reproduce |
| Regression | 103 passed; exact output in `outputs/retrieval_bakeoff_v1/regression_tests.txt` |
| Cause audit | Independent full-original review in `CAUSAL_AUDIT.md` and `causal_audit.json`; correct labels not credited when causes are unsupported |
| Scope/completion audit | `COMPLETION_AUDIT.md` separates actual executed stages and explicit limitations |

Preparation drafts before independent fixes are retained in `protocol_drafts`;
neither draft made inference or offline evaluation. No frozen runtime was changed
after evaluation. The discovered native-receipt candidate-norm classification
defect is disclosed, not repaired and rerun in place. Admission/schema/actor
success is not semantic correctness; tests/replay cannot certify a bug-free
policy reasoner. The original A unsupported interface, partial references and
known-case limitations remain visible.

Local preparation/scoring used isolated Python3.13.7; finite server model jobs
used isolated Python3.12.3. The five sealed library versions match on both:
BM25S0.3.12, NumPy2.4.4, Pydantic2.13.5, pandas3.0.2, pyarrow25.0.1.
Code hashes normalize repository CRLF; model-input byte seals use exact bytes.
Successful cross-environment controller replay is recorded rather than assuming
the interpreter versions are identical.

Server worktree was detached at pre-inference `0c5c7b19`. Its finite supervisor
jobs `guardian_retrieval_bakeoff_impact` and `guardian_retrieval_bakeoff_s2g`
had `autostart=false`, `autorestart=false` and both exited 0. Runtime/output
paths and commands are in RUNBOOK. Existing credentials were discovered by the
unchanged transport; secrets never enter saved request bodies or reports. No
business tool was executed. Final outputs are archived, not a service deployment.

Required reports: REPOSITORY_REUSE, DATASET, BASELINE, RETRIEVAL_COMPARISON,
SOURCE_COVERAGE, LLM_IMPACT, S2G_RAG_EVALUATION and FINAL_DECISION. The final
decision answers all twelve questions and proposes one minimal component,
explicitly as future research. Missing independent holdout, true unrelated-ID
case, trained official S2G, optional embeddings and unexecuted heavyweight
retrievers are limits, not completed accuracy claims. No additional planned
model calls remain.

Final commit/push and remote HEAD equality are checked after independent reports
are complete; the final commit contains this file, so its SHA is recorded by
Git rather than recursively inserted here.
