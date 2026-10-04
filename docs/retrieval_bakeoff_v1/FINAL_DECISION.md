# Retrieval decision after the bounded experiment

There is **no demonstrated universal retrieval winner or binary F1 improvement**.
B1 remains the development-selected new method. Existing local BM25 has stronger
known-evaluation complete-set counts, and simple methods remain reasonable
baselines. Coverage/fusion and the API gap controller do not justify mandatory
extra complexity. S2G recovers two real missing Silver facts, but no admitted
cause-correct binary repair. Production and historical experiments remain intact.

The retained experiment comprises 15 original valid46 rows, 600 offline packets,
five impact and ten S2G inference calls, **90,419 actual/charged tokens**, no
retries and no hidden provider/model change. All 103 relevant regression tests
pass. Zero-HTTP replay reproduces transport/admission and dynamic gap packets on
Windows and Linux. Full comparisons, costs and source omissions are linked below.

## Comparison and interpretation

Complete known evidence alternatives at eight / twelve reads, without the source
token cap, are shown as development / known evaluation. The 20k cap leaves these
counts unchanged but changes individual sources and cost. These are reference
coverage counts, not correct-answer or binary F1 counts.

| Method | Eight reads, dev / eval | Twelve reads, dev / eval |
|---|---:|---:|
| Original A, operational | 1/8 / 0/7 | 1/8 / 0/7 |
| Existing local BM25 | 1/8 / 3/7 | 2/8 / 3/7 |
| BM25S B1, selected on development | 2/8 / 1/7 | 2/8 / 1/7 |
| BM25S B2 | 1/8 / 3/7 | 1/8 / 3/7 |
| BM25S B3 | 1/8 / 2/7 | 2/8 / 2/7 |
| Exact + graph | 1/8 / 0/7 | 1/8 / 0/7 |
| BM25 + exact | 2/8 / 1/7 | 2/8 / 1/7 |
| BM25 + exact + graph | 2/8 / 1/7 | 2/8 / 1/7 |
| RRF | 2/8 / 1/7 | 2/8 / 1/7 |
| Coverage heuristic | 2/8 / 0/7 | 2/8 / 1/7 |

A is unsupported on thirteen cases and intrinsically capped at eight reads.
On its two supported cases, A completes one set and B1 none; broader support
does not prove superior retrieval on the inherited interface. All six negative
references remain incomplete for every method/budget. Two references are partial;
two bank081 enum spans have invalid normative annotation, qualified separately
without changing frozen gold, references, selection or complete-set scores.

Targets are always mandatory and fully covered in 600/600 packets. That is an
attachment property, not evidence discovery. At eight reads B1 finds dev policy
5/13 and history 8/22; known evaluation policy 6/15 raw, 4/13 qualified, and
history 6/30. Norm/exception omissions, remote bindings and long-distance facts
remain substantial. See [all budget curves](RETRIEVAL_COMPARISON.md) and
[per-case source audit](SOURCE_COVERAGE.md).

The original valid46 archived OR baseline remains the prior TP20/FP2/FN3/TN21,
F1 0.8889; it is not replaced by this fifteen-case diagnostic. Sealed160 R0's
0.9714 is a different synthetic task. No new overall valid46 or holdout score
is claimed. Original historical A/C raw negatives with violation explanations
were already traced through raw/admitted/saved equality: Python did not invert
those labels. Current reviews additionally demonstrate policy-scope errors and
a receipt-classification defect; all are separate from mere label inconsistency.

## Answers to the twelve research questions

1. **Better than current Selector?** B1 supports more input shapes and was
   selected on frozen development criteria. Its comparable supported A case
   does not improve, so a general quality advantage is not established.
2. **Cross-domain transfer?** Four domains are exercised without domain rules.
   B1's known-evaluation complete count is only 1/7. These known examples cannot
   establish transfer to unseen domains or an independent holdout.
3. **Missed relations?** Norm applicability, USER versus ASSISTANT permission,
   remote exceptions, real profile/reservation identity, latest successful state,
   and procedural timing remain unresolved. Genuine unrelated-entity ID
   substitution is NOT_COVERED by the selected real cases.
4. **EvidenceGraph benefit?** Qualified receipt and co-recorded navigation is
   reusable. Adding graph candidates gives no consistent complete-set gain over
   simpler fusion; typed equality is not ownership or permission proof.
5. **Need BM25S?** No accuracy advantage of the library is isolated. With query
   multiplicity normalized it ranks identically to the existing implementation
   on 15/15 corpora. Frozen B2 preserves repeated query weights, which confound
   a library comparison. BM25S remains an optional implementation convenience.
6. **Need LlamaIndex?** A small SourceStore adapter is sufficient for these
   tested operations. Its BM25 wrapper delegates to BM25S; query generation can
   introduce hidden LLM calls. No whole-framework dependency is justified.
7. **PageIndex useful?** Hierarchical headings can help navigation; generic
   original-heading windows were executed here. Full PageIndex is NOT_EXECUTED,
   and no isolated PageIndex quality benefit was measured.
8. **S2G gain?** API adaptation adds two necessary Silver facts versus zero for
   deterministic extension, but its final actor failure prevents admission. No
   cause-correct admitted binary repair is measured. Official S2G is NOT_EXECUTED.
9. **When a Gap Controller?** A future conditional hypothesis is a concrete
   unresolved factual dependency after cheap exact/pair navigation fails. It
   must retain evidence and have capped extra reads. These results do not yet
   validate a trigger or justify paying it on every example.
10. **Retrieval without extra LLM?** Yes: every offline selector and deterministic
    extension executes without model calls. This does not mean its evidence is
    semantically sufficient to decide every Guardian example.
11. **Simplest next component?** Keep existing local lexical search, exact
    source windows and qualified receipt grouping as the default research
    baseline. Retain B1 as the frozen comparison candidate. First fix and test
    the review-interface classification in a separately frozen phase; then use
    a new holdout before committing to any production choice.
12. **Why no absence proof?** Explicit windows are partial parents; a subset
    omits history and norms; the reference is curated, not exhaustive. Neither
    category diversity nor model sufficiency certifies all applicable rules.
    Unknown world state, missing evidence and demonstrated process violation
    need separate representation. Admitted UNKNOWN maps to 0 only by an explicit
    binary contract and can create FN; technical rejection stays null.

## One minimal proposed component

`retrieve_evidence(original_prompt, whole_current_move, budget, profile) -> EvidencePacket`
is a research API proposal, not a newly integrated or validated composite.
The input is original text plus read/source-byte allowances (8 or 12 reads,
20k conservative source-record bound) and a fixed query profile selected before
evaluation. Gold, row IDs, business-rule mappings and reference lists are excluded.

Use SourceStore for original spans, parent IDs and hashes; existing event parsing
for the whole current move and applicable current-call declarations. Lexical
search is the main ranker, with the existing local BM25 arm as a measured simple
baseline. Exact typed operand matches and graph neighbors are navigation
operations for explicitly unresolved dependencies. Preserve unique actor/order
qualified call/result groups. Default fusion is deterministic deduplication and
ranked assembly; optional RRF remains an experimental profile with no proven
advantage. Do not add all graph candidates automatically or change profiles by
case ID.

The output contains exact sources, current targets, declarations, ordered IDs,
selection trace, source costs, unmatched candidate/dependency diagnostics and
failure reasons. Provenance includes original document/start/end, exact text,
hash, native parent, role/actor, tool and qualified pair identity. Full targets
are compulsory and charged; explicit windows are marked incomplete. If a full
mandatory source exceeds the allowance, return a budget failure rather than
silently shorten it. Ambiguous receipt pairing remains unresolved.

Coverage records available and missing categories and dependency candidates,
without fixed normative/event quotas or a completeness certificate. Potential
exception passages get ordinary original-source navigation, never special
business semantics inferred from tool names. Factual JSON receipts must remain
history rather than becoming normative by parse failure; mixed KB prose remains
a candidate whose norm authority must be checked against original provenance.
That boundary fix is required before another review experiment and has not been
silently applied to this one.

When evidence is incomplete, return unresolved questions and
`completeness_certified=false`; absence of a matching subset event is not a
negative or violation proof. Additional exact/pair/lexical reads are bounded by
remaining capacity. A future optional S2G hook can propose structured questions
and original catalog IDs after cheap navigation, but must validate namespaces
atomically, retain the seed and cap cycles/reads/model cost. A model sufficient
opinion never promotes the packet to all-policy proof.

Failure reasons include unsupported input, invalid provenance, ambiguous pair,
unread normative scope, missing factual dependency, mandatory-source budget,
context stop, invalid gap namespace, provider failure and exhausted budget.
Semantic UNKNOWN and technical null remain separate downstream outcomes.

Compared with A, this source adapter admits prose/multiple calls and original
windows across domains but introduces catalog/assembly code and a larger cost
surface. Existing BM25 adds no production dependency; BM25S/LlamaIndex, large
community graphs, embeddings and trained S2G are not required by the measured
simple baseline. More supported shapes and more facts are useful engineering
properties; a final-quality improvement remains unproven.

## Remaining errors and stopping point

Unresolved: Telecom actor-permission FN; unsupported and invented normative
claims in Silver; bank intent/action scope and actor admission; Retail ZIP
fabrication missed despite evidence access; receipt prefix classification;
semantic incompleteness of negative references; bank081 reason-code annotation;
query-weight confounding; no genuine unrelated-ID case or independent holdout.
Optional embeddings and official heavyweight retrievers remain explicitly
NOT_TESTED/NOT_EXECUTED. The [causal audit](CAUSAL_AUDIT.md),
[LLM impact](LLM_IMPACT.md), [S2G evaluation](S2G_RAG_EVALUATION.md) and
[validation](VALIDATION.md) retain these limits and raw artifacts.

Stop after saving, regression/replay, independent audits and commit/push. No
production integration or full Guardian Hybrid is authorized by this experiment.
