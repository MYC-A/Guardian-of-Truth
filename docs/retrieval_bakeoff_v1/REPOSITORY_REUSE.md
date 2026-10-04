# Retrieval libraries: pinned implementation audit

Checked 2026-10-04 against upstream code, not package descriptions alone. This
audit performed no inference, package installation, weight download, training or
foreign benchmark replication. The six upstream snapshots are reproducible;
their current HEAD revisions are not the versions of Guardian's eventual adapters.
Detailed paths, dependency notes and source hashes are in
[library_audit.json](../../outputs/retrieval_bakeoff_v1/library_audit.json).

| Project | Pinned revision | Implementation to consider | LLM requirement | Dependencies | SourceStore reuse | Main risk |
|---|---|---|---|---|---|---|
| BM25S | `57c367f4074df3cd9e70379aa3c08aa946c83b6f` | Sparse BM25 index and `retrieve()`; window-level corpus | None | NumPy required; SciPy/Numba optional; Python >=3.8 | Strong: corpus rows map to `(source_id,start,end)` | Default English stopwords and token regex lose short identifiers; relevance is not applicability |
| LlamaIndex | `962940ddc079cc21701d28d1237c84c82a7c5164` | BM25Retriever, reciprocal-rank fusion, RecursiveRetriever, node metadata | BM25 none; query generation and query-engine recursion can call LLM | BM25 integration: BM25S, PyStemmer, llama-index-core; Python >=3.10 | Strong primitives; unnecessary framework for small local fusion | Hidden model initialization, content-hash deduplication and metadata injected into model text |
| PageIndex | `6d23caf416858f2ca136840305d1f479a86f6ef7` | Markdown/PDF hierarchy and bounded parent/child navigation | Basic parsing can avoid LLM; default summaries/optimization/chat use it | Current requirements include litellm, OpenAI, openai-agents, MCP, PDF libraries | Partial: declaration/policy header tree, with original-span mapping | Generated summaries are navigation; SDK defaults introduce extra calls/concurrency |
| Microsoft GraphRAG | `769542fbf1d8e5b4c6a8677fefc34621c87894c5` | Local entity-linked context; DRIFT pending-query graph/state | Local query embeddings and answer LLM; DRIFT primer/follow-ups use LLM | Python >=3.11,<3.14; GraphRAG packages, pandas, NumPy, PyArrow, graph/NLP stack | Borrow small state/adjacency concepts; not full indexing pipeline | Extracted entities/community reports do not prove original obligations; indexing/call cost |
| HippoRAG | `2bfd831417202b49cda9da7973e141a456e16872` | Fact/dense retrieval plus personalized PageRank over phrase/passage graph | OpenIE/fact recognition use LLM; embeddings required; API injection supported | Torch, Transformers, igraph, SciPy, OpenAI/litellm; optional local embedding/vLLM packages | Partial: graph reranking of exact original sources | Content-hash identity can merge distinct provenance; model triples are not code proof |
| S2G-RAG | `5d842a67a0a99a7b545bbad0dc402ceaae0e5eff` | Trained sufficiency/gap judge, gap queries, evidence accumulation and stop loop | Local base judge + trained LoRA required even with API answer reasoner | Torch, Transformers, PEFT, TRL/Accelerate; Java/Pyserini for BM25; optional E5/FAISS | Borrow explicit bounded gaps/queries, preserve SourceStore IDs | Trained judge unavailable to generic API; truncation, sentence selection and budget-forced answer mismatch Guardian |

## Existing Guardian mechanisms first

[SourceStore](../../src/guardian_truth/source_search/store.py) preserves original
prompt/response and hashes, issues source IDs and offset-addressed quotes, and
offers exact value lookup, reads and recorded-neighbor traversal. Its
`search_sources()` uses token overlap, not BM25. A partial `read_source()` is a
window, with truncation metadata; it must not be described as a full source read.
Graph links record co-occurrence and event order, not ownership or successful
policy satisfaction.

There is already a dependency-free
[BM25 window baseline](../../experiments/searh_23/evidence_graph_search_probe/ranked_search.py):
`bm25(query,texts,k1=1.5,b=.75)` uses positive Robertson IDF, case-folded word
tokens and stable index ties. `RankedGraph` distributes windows across sources,
retains target/conversation and relevant rule spans, and labels navigation as
retrieval-only. Its
[tests](../../tests/test_evidence_graph_ranked_search.py) explicitly cover late
evidence in long observations. Reuse the scorer or record its results as the
existing baseline; BM25S's principal addition is indexed sparse scoring, not a
new semantic mechanism. Match corpus windows, tokenizer and score convention
before attributing a recall change to the library.

The inherited [coverage_plan](../../experiments/hybrid_mechanisms/runner.py) is a
small heuristic over one native target, lexical rule selection and neighboring
call/result candidates. Keep it unchanged for A; report incompatible formats or
budget omissions explicitly. It is not exhaustive obligation coverage. Existing
[EvidenceGraph](../../src/guardian_truth/evidence_graph/graph.py) already provides
source windows, declaration links and typed candidates. New fusion should rank
these references, not rewrite production or manufacture new business relations.

## Lightweight implementation choices

**BM25S.** The pinned
[implementation](https://github.com/xhluca/bm25s/blob/57c367f4074df3cd9e70379aa3c08aa946c83b6f/bm25s/__init__.py)
supports `BM25.index()`, `retrieve()`, persistence and memory-mapped loading;
corpus entries can be original reference handles. Its
[setup](https://github.com/xhluca/bm25s/blob/57c367f4074df3cd9e70379aa3c08aa946c83b6f/setup.py)
requires only NumPy. The
[tokenizer](https://github.com/xhluca/bm25s/blob/57c367f4074df3cd9e70379aa3c08aa946c83b6f/bm25s/tokenization.py)
defaults to English stopwords and a two-or-more-character word pattern. Freeze
tokenization explicitly, keep an exact ID/value channel, cap `k` to corpus size,
and retain zero-score/empty-query behavior. Index offsets as well as IDs so a
late matching window cannot become a truncated prefix read.

**LlamaIndex.** Its
[BM25 retriever](https://github.com/run-llama/llama_index/blob/962940ddc079cc21701d28d1237c84c82a7c5164/llama-index-integrations/retrievers/llama-index-retrievers-bm25/llama_index/retrievers/bm25/base.py)
already wraps BM25S and defaults to English stemming. The
[fusion retriever](https://github.com/run-llama/llama_index/blob/962940ddc079cc21701d28d1237c84c82a7c5164/llama-index-core/llama_index/core/retrievers/fusion_retriever.py)
defaults to four queries and SIMPLE fusion, not RRF. RRF uses `k=60`, zero-based
rank and `node.hash` deduplication; score objects are modified. Its constructor
resolves `Settings.llm` even when `num_queries=1` unless an explicit LLM object
is supplied. A pure local RRF over immutable source-span keys is smaller and
easier to audit. Record rank origin, weights, ties and per-channel candidates.
The [recursive retriever](https://github.com/run-llama/llama_index/blob/962940ddc079cc21701d28d1237c84c82a7c5164/llama-index-core/llama_index/core/retrievers/recursive_retriever.py)
follows registered IndexNode links; it is not a semantic gap detector. Preserve
original IDs/offsets/actors in
[node metadata](https://github.com/run-llama/llama_index/blob/962940ddc079cc21701d28d1237c84c82a7c5164/llama-index-core/llama_index/core/schema.py),
exclude navigation-only fields from model evidence, and bound recursion.

**PageIndex.** Current
[Markdown parsing](https://github.com/VectifyAI/PageIndex/blob/6d23caf416858f2ca136840305d1f479a86f6ef7/pageindex/page_index_md.py)
exposes `md_to_tree()` with summaries/descriptions disabled by default. Header
line positions are useful if mapped back to exact SourceStore offsets. For
[Flash PDF](https://github.com/VectifyAI/PageIndex/blob/6d23caf416858f2ca136840305d1f479a86f6ef7/pageindex/flash/api.py),
`summary=False,optimize=False` avoids LLM processing; normal defaults do not.
Do not deploy the chat/index SDK merely to expand a policy parent header. This
audit did not execute PageIndex parsing or chat; an adapter borrowing hierarchy
must be labelled accordingly.

**GraphRAG.**
[LocalSearchMixedContext](https://github.com/microsoft/graphrag/blob/769542fbf1d8e5b4c6a8677fefc34621c87894c5/packages/graphrag/graphrag/query/structured_search/local_search/mixed_context.py)
maps queries to embedded entities and assembles entities, relations, text units
and optional community reports under token allocations. It requires those
prepared artifacts. The
[DRIFT controller](https://github.com/microsoft/graphrag/blob/769542fbf1d8e5b4c6a8677fefc34621c87894c5/packages/graphrag/graphrag/query/structured_search/drift_search/search.py)
adds local follow-ups from primer/answer results. Its
[QueryState](https://github.com/microsoft/graphrag/blob/769542fbf1d8e5b4c6a8677fefc34621c87894c5/packages/graphrag/graphrag/query/structured_search/drift_search/state.py)
serializes action dependencies and token counters, but shuffles pending actions
without a scorer. Borrow durable typed gaps with deterministic priority; do not
inherit nondeterministic scheduling or treat community summaries as evidence.

**HippoRAG.** The
[implementation](https://github.com/OSU-NLP-Group/HippoRAG/blob/2bfd831417202b49cda9da7973e141a456e16872/src/hipporag/HippoRAG.py)
indexes passages, OpenIE triples and embeddings; `retrieve()` combines fact
selection, dense passage scoring and personalized PageRank. Its graph traversal
uses an undirected projection, so order/direction are not procedural proof.
Injected API models/embeddings are possible, but the full dependency stack is
unnecessary for co-recorded Guardian source expansion. Content-derived document
hashes can replace metadata when identical text is indexed with different
metadata. Never collapse different actors/events just because their text matches.

## Mandatory S2G-RAG separation

The official
[training code](https://github.com/nianaaa/S2G-RAG/blob/5d842a67a0a99a7b545bbad0dc402ceaae0e5eff/training/train_s2g_judge_lora.py)
trains a causal-LM sufficiency judge on question/context snapshots and structured
gap supervision. LoRA is rank 16, alpha 32, dropout .05, targeting q/k/v/o and
gate/up/down projections. The
[README](https://github.com/nianaaa/S2G-RAG/blob/5d842a67a0a99a7b545bbad0dc402ceaae0e5eff/README.md)
illustrates Llama-3.2-3B-Instruct plus a trained adapter; these are distinct from
the answer reasoner. An ordinary API prompt is not this trained judge.

In the
[official BM25 loop](https://github.com/nianaaa/S2G-RAG/blob/5d842a67a0a99a7b545bbad0dc402ceaae0e5eff/inference/inference_bm25.py),
the judge receives the question and accumulated selected evidence and returns
`sufficient` plus `gap_items`. Targets/slots/descriptions become the next lexical
query. Evidence is appended across turns; source history is maintained. Defaults
are four turns and six documents; CLI repeat removal defaults to false. The
sentence selector considers at most 40 sentences/document and selects up to six.
Judge tokenization permits truncation. Termination invokes the answer reasoner
on either a positive verdict or exhausted turns. `--gpt` changes the reasoner,
but still loads both `SUFF_BASE_PATH` and `SUFF_LORA_PATH` through Transformers
and PEFT. No official run was performed: **OFFICIAL_S2G_NOT_EXECUTED**.

A separate **S2G_INSPIRED_API_BASED** experiment may reuse typed gaps, deterministic
gap-to-query mapping, unread-source deduplication and durable evidence state. It
must charge every judge/answer call, reject invalid plans before reads, preserve
full original source windows, validate genuine booleans and stop explicitly on
read/token/HTTP limits. Sufficiency is a model judgment, not a code certificate
that all obligations or exceptions have been searched. Exhaustion cannot imply
NO_ERROR; technical stops must retain null decisions. Neither adapter results nor
foreign QA F1 may be presented as official S2G-RAG performance on Guardian.

## Candidate for this bounded bakeoff

Compare the inherited plan, existing BM25/BM25S on the same original windows,
pure lexical/exact/recorded-neighbor RRF, and a bounded variable coverage adapter.
Only BM25S warrants a small isolated dependency here. Keep the other five as
audited mechanism sources; any actually executed primitive must be recorded
separately. Match read counts and visible source bytes/tokens, freeze queries
without reference labels, and evaluate recall against independently annotated
alternative source sets. Increased retrieval recall alone is not evidence of
improved binary Guardian F1.
