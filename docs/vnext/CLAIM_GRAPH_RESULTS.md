# Claim Graph v1 — completed controlled development evaluation

Authoritative results: `outputs/vnext/claim_graph_v1_results.json`; original
per-case taxonomy: `claim_graph_v1_failure_audit.json`; detailed exact-field
audit: `claim_graph_v1_detailed_audit.json`. All 41 cases completed. Predictions
were sealed before gold scoring. The exact 100 frozen source files/contracts
are preserved in `claim_graph_v1_source_archive.json`. No blind labels were read.

Both C2 and vNext achieved span precision/recall/F1 1.0 on 39 fully annotated
cases (36 positive spans). Two partially annotated cases are not detection gold.
Every deterministic span received a disposition; seven final typed nodes are
UNKNOWN. This small controlled extension is not evidence of generalization.

| Exact annotated field | vNext correct / eligible | C2 correct / eligible |
|---|---:|---:|
| kind | 31 / 37 | 32 / 38 |
| actor | 21 / 37 | unavailable |
| predicate | 16 / 36 | unavailable |
| object | 9 / 36 | unavailable |
| entity references | 26 / 37 | 22 / 36 |
| polarity | 33 / 36 | unavailable |
| modality | 35 / 36 | unavailable |
| temporal anchor | 29 / 36 | unavailable |
| source references | 35 / 36 | 36 / 36 |

One transport failure excludes one vNext kind annotation from conditional
semantic accuracy; strict kind operational yield is 31/38. Unavailable C2 fields
are not scored as zero. On paired shared annotations, entity accuracy improves
11.11 percentage points, kind is unchanged and source accuracy loses 2.78 points.
The mean shared-field gain is 2.78 points: the frozen typed-gain gate **fails**.
The span gate passes. Full typed-semantic improvement is NOT_ESTABLISHED.

Relation-type-set accuracy is 37/40 (92.5%); directed edges have no directed gold.
Unsupported-claim recall has no contextual gold and is NOT_ESTABLISHED. Binding,
fact support, certificates and end-to-end improvement were not evaluated here.

| Provider metric | C2 | vNext |
|---|---:|---:|
| requests / transport successes / valid schemas | 41 / 41 / 41 | 410 / 409 / 409 |
| per-request latency p50 / p95, ms | 4645.987 / 7339.524 | 4127.346 / 8165.553 |
| reported total tokens | 26255 | 224644 |

The vNext layout uses ten times as many requests and about 8.56 times the tokens.
These latency figures are per request, not per complete case. Billing cost is
NOT_AUDITED. There were no hidden retries. The failed kind task belongs to
`cg:negative_history:2`; a transport failure is not a semantic false negative.

## Audit before next-version changes

All 41 cases have an audit row: 35 carry CLAIM_TYPING, three CAUSAL_REASONING
and one TRANSPORT (components overlap). There are 92 eligible exact-field
mismatches: object 27, predicate 20, actor 16, entity references 11, time 7,
kind 6, polarity 3, modality 1 and source 1.

Exact matching is a representation metric, not adjudicated semantic equivalence.
For example, `archive` versus `archived` and `R-71` versus `item R-71` fail the
frozen score without necessarily expressing different propositions. Do not
retroactively change scoring or claim all 92 are semantic errors. Next-version
candidates are source-grounded canonical identifiers, narrow normalization and
cheaper enrichment after C2 detection. They require a new freeze/evaluation;
none changes the v1 result. This component is not admitted as a demonstrated
overall gain, and the full vNext cycle remains incomplete.
