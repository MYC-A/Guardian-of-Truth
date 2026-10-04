# Frozen offline retrieval comparison

**B1 was selected by frozen development criteria. It is not a demonstrated universal winner.** The known evaluation split favors the local BM25/B2 arms on curated complete-set count, while coverage-aware fusion does not consistently outperform simpler search. Selection is unchanged; no evaluation-driven retuning is applied.

The matrix has 15 original known valid46 trajectories (8 development, 7 known evaluation), 10 methods and four budgets: **600 packets**. Two reference cases are explicitly partial. References use original span coverage and admissible evidence alternatives; target/declaration records are counted and costed separately from retrieved reads. This is retrieval coverage, not binary F1, proof of policy meaning, independent holdout quality or a NO_ERROR certificate.

Authoritative artifacts: [frozen summaries](../../outputs/retrieval_bakeoff_v1/offline_summary.json), [development-only selection](../../outputs/retrieval_bakeoff_v1/selection.json), [independent coverage audit](../../outputs/retrieval_bakeoff_v1/independent_coverage_audit.json), and [all retained packets](../../outputs/retrieval_bakeoff_v1/offline_packets). The independent audit reconstructed all600 span scores/costs with no discrepancies; it also identifies partial-reference and semantic-credit limits.

## Methods and comparability

| Method | Frozen mechanism | Main limitation |
|---|---|---|
| A | Unchanged imported historical `coverage_plan()` | Requires the inherited one-target Telecom/tagged-policy interface; unsupported cases remain failures; intrinsic cap stays eight. |
| local_bm25 | Existing local BM25, B2 original action/declaration/current-context query | Query terms are deduplicated by the inherited algorithm. |
| B1 | Actual BM25S, action name and literal arguments | Depends on action-name vocabulary and literal identity overlap. |
| B2 | Actual BM25S, action/arguments plus declaration/current context | Repeated query terms retain multiplicity, unlike local BM25. |
| B3 | Actual BM25S, separate literal action/operand/prose/declaration aspects fused by RRF | Splitting aspects does not discover independent normative conditions. |
| exact_graph | Typed/literal operand candidates plus qualified receipt/co-recorded graph candidates, round-robin | No lexical normative discovery; graph relations are navigation rather than ownership or current-state proofs. |
| bm25_exact | B3 lexical + exact candidates, round-robin | Candidate diversity can displace necessary contextual evidence. |
| bm25_exact_graph | B3 lexical + exact + graph, round-robin | More candidate routes do not guarantee a sufficient set. |
| rrf | Same lexical/exact/graph candidates scored by RRF k=60 | Consensus ranking can reinforce correlated matches and miss remote exceptions. |
| coverage | RRF plus generic category/actor/tool diversity and raw exception-marker hints | Diversity is a heuristic, not semantic completeness; no fixed two-policy/three-pair quota. |

All new methods share the same exact catalog. Generic headings and explicit windows preserve original offsets and native parent IDs; long sources use at most4,000-character windows. A keeps its original complete normative sections. Therefore one A read and one new window are different units; costs must accompany read-count comparisons. Mandatory current prose/all assistant events and applicable current-call declarations are supplied identically, but their presence does not establish intent or norm applicability.

## Budget curves for every method

`Complete raw/operational` counts reference alternatives satisfied before/after requiring no packet failure. Denominators are development8 and known evaluation7. `P/H` are normative/history units found over required units. UTF8 bound is summed over all15 packets and includes serialized mandatory targets/declarations. It conservatively bounds source-record tokens; it is not provider usage or the whole review-prompt token count.

### 8 retrieved sources/windows, no source-token cap

| Method | Dev complete raw/op | Eval complete raw/op | Dev P/H | Eval P/H | Retrieved reads, all15 | UTF8 bound, all15 | Packet failures |
|---|---:|---:|---|---|---:|---:|---:|
| A | 2/1 | 0/0 | 3/13; 2/22 | 2/15; 0/30 | 10 | 50,241 | 13 |
| local_bm25 | 1/1 | 3/3 | 5/13; 6/22 | 12/15; 2/30 | 120 | 254,349 | 0 |
| B1 | 2/2 | 1/1 | 5/13; 8/22 | 6/15; 6/30 | 120 | 234,243 | 0 |
| B2 | 1/1 | 3/3 | 6/13; 4/22 | 12/15; 1/30 | 120 | 249,845 | 0 |
| B3 | 1/1 | 2/2 | 6/13; 4/22 | 10/15; 4/30 | 120 | 243,726 | 0 |
| exact_graph | 1/1 | 0/0 | 0/13; 4/22 | 2/15; 4/30 | 55 | 96,920 | 0 |
| bm25_exact | 2/2 | 1/1 | 5/13; 6/22 | 7/15; 8/30 | 120 | 251,652 | 0 |
| bm25_exact_graph | 2/2 | 1/1 | 5/13; 6/22 | 7/15; 8/30 | 120 | 249,508 | 0 |
| rrf | 2/2 | 1/1 | 4/13; 7/22 | 7/15; 5/30 | 120 | 231,705 | 0 |
| coverage | 2/2 | 0/0 | 4/13; 6/22 | 6/15; 4/30 | 120 | 223,988 | 0 |

### 12 retrieved sources/windows, no source-token cap

| Method | Dev complete raw/op | Eval complete raw/op | Dev P/H | Eval P/H | Retrieved reads, all15 | UTF8 bound, all15 | Packet failures |
|---|---:|---:|---|---|---:|---:|---:|
| A | 2/1 | 0/0 | 3/13; 2/22 | 2/15; 0/30 | 10 | 50,241 | 13 |
| local_bm25 | 2/2 | 3/3 | 7/13; 12/22 | 12/15; 3/30 | 180 | 334,592 | 0 |
| B1 | 2/2 | 1/1 | 6/13; 13/22 | 6/15; 7/30 | 180 | 320,528 | 0 |
| B2 | 1/1 | 3/3 | 8/13; 7/22 | 12/15; 3/30 | 180 | 326,455 | 0 |
| B3 | 2/2 | 2/2 | 8/13; 8/22 | 10/15; 8/30 | 180 | 326,246 | 0 |
| exact_graph | 1/1 | 0/0 | 0/13; 5/22 | 2/15; 6/30 | 74 | 126,459 | 0 |
| bm25_exact | 2/2 | 1/1 | 6/13; 11/22 | 8/15; 9/30 | 180 | 332,733 | 0 |
| bm25_exact_graph | 2/2 | 1/1 | 6/13; 10/22 | 8/15; 9/30 | 180 | 334,310 | 0 |
| rrf | 2/2 | 1/1 | 7/13; 11/22 | 8/15; 8/30 | 180 | 320,716 | 0 |
| coverage | 2/2 | 1/1 | 6/13; 12/22 | 8/15; 9/30 | 180 | 307,093 | 0 |

### 8 reads plus20,000 source-record token bound per case

| Method | Dev complete raw/op | Eval complete raw/op | Dev P/H | Eval P/H | Retrieved reads, all15 | UTF8 bound, all15 | Packet failures |
|---|---:|---:|---|---|---:|---:|---:|
| A | 2/1 | 0/0 | 3/13; 2/22 | 2/15; 0/30 | 10 | 50,241 | 13 |
| local_bm25 | 1/1 | 3/3 | 6/13; 6/22 | 12/15; 2/30 | 116 | 237,486 | 0 |
| B1 | 2/2 | 1/1 | 5/13; 8/22 | 6/15; 6/30 | 117 | 217,328 | 0 |
| B2 | 1/1 | 3/3 | 5/13; 4/22 | 12/15; 1/30 | 115 | 235,626 | 0 |
| B3 | 1/1 | 2/2 | 6/13; 4/22 | 10/15; 4/30 | 116 | 229,398 | 0 |
| exact_graph | 1/1 | 0/0 | 0/13; 4/22 | 2/15; 4/30 | 55 | 96,920 | 0 |
| bm25_exact | 2/2 | 1/1 | 5/13; 6/22 | 7/15; 7/30 | 114 | 231,720 | 0 |
| bm25_exact_graph | 2/2 | 1/1 | 5/13; 6/22 | 7/15; 7/30 | 114 | 230,835 | 0 |
| rrf | 2/2 | 1/1 | 4/13; 7/22 | 7/15; 5/30 | 115 | 218,095 | 0 |
| coverage | 2/2 | 0/0 | 4/13; 6/22 | 5/15; 5/30 | 118 | 211,638 | 0 |

### 12 reads plus20,000 source-record token bound per case

| Method | Dev complete raw/op | Eval complete raw/op | Dev P/H | Eval P/H | Retrieved reads, all15 | UTF8 bound, all15 | Packet failures |
|---|---:|---:|---|---|---:|---:|---:|
| A | 2/1 | 0/0 | 3/13; 2/22 | 2/15; 0/30 | 10 | 50,241 | 13 |
| local_bm25 | 2/2 | 3/3 | 6/13; 12/22 | 12/15; 2/30 | 151 | 276,633 | 0 |
| B1 | 2/2 | 1/1 | 6/13; 12/22 | 6/15; 7/30 | 161 | 270,444 | 0 |
| B2 | 1/1 | 3/3 | 7/13; 7/22 | 12/15; 2/30 | 148 | 274,995 | 0 |
| B3 | 2/2 | 2/2 | 8/13; 8/22 | 10/15; 7/30 | 154 | 274,990 | 0 |
| exact_graph | 1/1 | 0/0 | 0/13; 4/22 | 2/15; 6/30 | 70 | 118,514 | 0 |
| bm25_exact | 2/2 | 1/1 | 6/13; 10/22 | 7/15; 8/30 | 149 | 274,588 | 0 |
| bm25_exact_graph | 2/2 | 1/1 | 6/13; 10/22 | 7/15; 8/30 | 150 | 274,447 | 0 |
| rrf | 2/2 | 1/1 | 6/13; 11/22 | 7/15; 8/30 | 158 | 272,511 | 0 |
| coverage | 2/2 | 1/1 | 6/13; 12/22 | 7/15; 8/30 | 164 | 261,483 | 0 |

The original A counts do not improve at12 because its algorithm remains capped at8. Its raw development2/8 includes one alternative satisfied by mandatory target/declaration records despite `UNSUPPORTED_BASELINE_CASE`; operational success is only1/8. Known evaluation is0/7 with7 failures. A is not a generally executable baseline on this cross-domain set, and raw reference credit must not hide that limitation.

At8 reads B1 obtains2/8 operational development sets and1/7 known evaluation set. The local BM25 arm obtains1/8 and3/7. At12 local BM25 reaches2/8 and3/7; B1 remains2/8 and1/7. Coverage obtains2/8 and0/7 at8, and2/8 and1/7 at12. This does not support automatically preferring the more elaborate coverage heuristic or claiming broad transfer from its earlier Telecom success. The20k cap leaves these complete-set counts unchanged but changes transmitted cost and potentially individual category coverage.

## Critical categories at eight reads

| Method | Declaration dev/eval | Entity binding dev/eval | Long-distance dev/eval | Exceptions dev/eval | History-missing risk cases dev/eval |
|---|---|---|---|---|---|
| A | 3/5; 0/2 | 2/12; 0/10 | 2/2; 0/4 | n/a; 0/6 | 7; 7 |
| local_bm25 | 4/5; 0/2 | 5/12; 1/10 | 2/2; 0/4 | n/a; 1/6 | 7; 7 |
| B1 | 3/5; 0/2 | 3/12; 2/10 | 1/2; 0/4 | n/a; 1/6 | 7; 7 |
| B2 | 4/5; 0/2 | 3/12; 0/10 | 1/2; 0/4 | n/a; 1/6 | 8; 7 |
| B3 | 4/5; 0/2 | 3/12; 2/10 | 1/2; 0/4 | n/a; 1/6 | 8; 7 |
| exact_graph | 4/5; 0/2 | 3/12; 2/10 | 2/2; 0/4 | n/a; 0/6 | 6; 7 |
| bm25_exact | 3/5; 0/2 | 2/12; 2/10 | 1/2; 0/4 | n/a; 1/6 | 7; 7 |
| bm25_exact_graph | 4/5; 0/2 | 3/12; 2/10 | 1/2; 0/4 | n/a; 1/6 | 7; 7 |
| rrf | 4/5; 0/2 | 5/12; 2/10 | 2/2; 0/4 | n/a; 1/6 | 6; 7 |
| coverage | 4/5; 0/2 | 4/12; 2/10 | 1/2; 0/4 | n/a; 1/6 | 6; 7 |

Target source coverage is100% in all600 packets, including failure packets. This reflects mandatory full current-target attachment, not retrieval competence. History-missing risk marks omissions from the curated reference; it is not evidence that a model actually inferred false absence. A subset never proves a mandatory event was absent from the original complete log.

## Post-hoc BM25 equivalence diagnostic

The frozen local/B2 comparison is confounded by query multiplicity. The inherited local function loops over `set(terms(query))`; BM25S sums repeated query-token columns. Expanded declarations and prose therefore reweight frequent terms in B2. Shared Unicode tokenization and identical k1=1.5/b=.75 did not make the frozen query semantics equivalent.

The separate [zero-HTTP diagnostic](../../outputs/retrieval_bakeoff_v1/bm25_equivalence_diagnostic.json) inspected all15 corpora without replacing frozen rankings. Original local/B2 complete rankings match only2/15 cases. Deduplicating BM25S query tokens in the scratch diagnostic makes the entire ranking and top8 identical to local BM25 in15/15 cases. A benign score scaling also differs: local BM25 multiplies by k1+1=2.5, which BM25S Lucene omits. After this constant adjustment maximum absolute score deviation is5.19e-5 (float32); ranking is unchanged.

This isolates no library-ranking advantage for these equivalent lexical queries. It also does not retroactively convert B2 into a deduplicated arm. All600 packets, selectedB1, frozen protocol and scores remain unchanged; any normalized query arm would require a new protocol. BM25S is a convenient implementation and research dependency, not an established accuracy improvement over the existing function.

## Interpretation and remaining limits

Pair grouping and graph expansion preserve qualified original receipts and expose navigation candidates. They do not solve ambiguous parallel results, omitted aliases, record freshness, permission, exception closure or semantic relevance. In this matrix exact/graph alone finds no required normative units in development and reaches only1/8 development complete sets,0/7 evaluation. Raw numeric/ID equality cannot substitute for policy search.

Complete-set scores are relative to curated alternatives. Some require extra discrimination/context beyond a minimal positive cause; failing them does not prove that no valid ERROR could be identified. Conversely a negative complete set is not an exhaustive inventory of every norm. The partial Banking081 reference includes declaration enum syntax credited in a normative category; it does not establish the meaning or priority of a transfer reason. That limitation is preserved, not retrospectively corrected to improve metrics.

Exact source-span fidelity does not prove linguistic or normative meaning. An explicit window from a long JSON result may fail standalone JSON decoding even though its parent is a valid structured result; a downstream text/KB candidate classifier can consequently misclassify that window. This affects reviewer presentation and must be diagnosed separately from retrieval recall. No partial JSON window is proof of a new norm.

No semantic embedding retriever, universal solver or production dependency is introduced. LLM causal impact and S2G comparisons require their own retained responses and causal audit; this offline report makes no claim of improved binary F1 or final answer correctness.
