# Offline retrieval API

```python
from experiments.retrieval_bakeoff_v1.corpus import build_corpus
from experiments.retrieval_bakeoff_v1.adapters import (
    retrieve, rank_queries, assemble, deterministic_extension,
)
corpus = build_corpus({"prompt": original_prompt, "response": original_response})
packet = retrieve(corpus, "coverage", read_limit=8, token_limit=20000)
candidate_ids = rank_queries(corpus, [original_source_based_question])
expanded = assemble(corpus, candidate_ids, read_limit=12, token_limit=30000)
```

`Corpus` exposes `store`, `graph`, `catalog`, `sources`, `current_targets`,
`declarations`, typed `operands`, qualified original `pairs`, and
`receipt_diagnostics`. Runtime reads only original prompt/response; extra row
labels/explanations are ignored. All new methods use the same catalog. Sources
retain original document offsets, native parent source IDs and SourceStore quote
IDs. Generic heading sections are capped at explicit 4,000-character windows;
windows partition every original character without head/tail omission.

Supported methods: `A`, `local_bm25`, `B1`, `B2`, `B3`, `exact_graph`,
`bm25_exact`, `bm25_exact_graph`, `rrf`, `coverage`. Actual BM25S uses Lucene
BM25 k1=1.5/b=.75 and shared Unicode regex tokenization with no stemming or
stopword removal. The local baseline executes the existing BM25 function's
unchanged AST. B1 uses action/arguments; B2 adds declarations/current context;
B3 fuses independent literal aspects. No domain-specific query is supplied.

`A` imports the unchanged original coverage selector: one Telecom-style native
target and original tagged policy are its inherited requirements. Other inputs
are recorded as unsupported. Its intrinsic eight-read cap is unchanged at the
12-read comparison setting. Its original whole-policy sources differ from the
new catalog windows; costs and this read-unit difference are disclosed.

Results include exact `read_sources`, mandatory `current_targets` and current
call `declarations`, `selected_ids`, rankings and selection `trace`, elapsed
`seconds`, `cost`, `uncovered`, and an explicit `failure`. Eight or twelve reads
count retrieved windows/sources, while mandatory targets/declarations are
separately counted and included in cost. Token budgets use a conservative UTF8
byte bound over serialized source records; this is not provider token usage or
the eventual complete review prompt cost. No source is invisibly shortened.

`assemble` preserves addressed candidate priority and groups uniquely qualified
result/call candidates. `deterministic_extension` starts with an existing set and
adds mechanical dependencies and typed/co-recorded graph candidates. Those links
are navigation; they prove no ownership, semantic identity, authority or norm
applicability. USER calls remain USER calls, and ambiguous parallel receipts
remain unqualified. Completeness is never certified. Subset absence never proves
absence from the full log.
