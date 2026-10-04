# Actual resource and transport accounting

The aggregate is reconstructed from unique durable HTTP ledgers by
`experiments/research_v3/diagnostics/replay_all.py`, not from requested case counts.
Requests reused by exact hash are charged once within a phase. Separate protocol
phases have separate ledgers; all their real HTTP calls count, even when input
text overlaps. Seven phases use 231 attempts, 228 HTTP successes and three HTTP
errors (429), with zero automatic retries.

| Phase | Attempts | Known provider tokens | Conservative charged tokens | Recorded HTTP seconds sum |
|---|---:|---:|---:|---:|
| Primary Mistral A0/A1/A2/A3 | 106 | 222,776 | 232,774 | 745.34 |
| Mistral early graph source IDs, dev | 12 | 31,492 | 51,120 | 40.69 |
| Mistral contextual role enums, dev | 15 | 19,988 | 29,410 | 36.99 |
| Gemma strict wire replication | 46 | 61,776 | 61,776 | 57.63 |
| Gemma schema-in-packet capability | 5 | 12,939 | 12,939 | 16.51 |
| Gemma contextual 32-case continuation | 31 | 51,142 | 51,142 | 33.03 |
| Gemma prospective two-family test | 16 | 20,427 | 20,427 | 16.41 |
| **Total** | **231** | **420,540** | **459,588** | **946.59** |

Known usage is the provider's prompt/completion total when supplied. Unknown usage
on errors receives a conservative request-byte/output-cap bound in the ledger;
39,048 tokens are reserved above known usage. This is a budget charge, not a claim
that the provider consumed exactly those tokens. Monetary billing was not supplied
and no verified pricing calculation was used; dollar cost is unknown. No model
weights were downloaded, no GPU inference was run and no credits/server purchases
were made. Existing remote credentials were read only in worker memory.

The 946.59 seconds are summed individual service/request times, not total project
time or normalized end-to-end latency. Some phases ran independently on the
server. Shared-cache per-arm cost attribution is also not additive: A3 depends on
forward discovery initially requested for A2. `common_case_comparison.csv` includes
that dependency when comparing standalone arm costs on the same 13 received cases.

The contextual Gemma continuation performs 31 requests for 32 cases because one
wire packet is identical. It uses 51,142 known tokens. In the primary same-model
common subset, A0 uses 16,939 known tokens, A2 48,749 and A3 74,912, with worse
3-way correctness for the formal arms. These are actual cache-attributed results,
not an equal-budget randomized efficiency study.

## Failure and durability behavior

The client writes a durable reservation before HTTP and saves the raw receipt and
usage before parsing model JSON. It disables that phase after the first transport
or HTTP failure. It does not follow redirects, wait for a quota reset, retry a
reserved/failed request or silently switch models. Missing cached stages remain
UNKNOWN. Replays never import credentials or take an HTTP code path.

The primary and two independent Mistral controls each stop at their first 429.
Controls were separately bounded experiments with different wire contracts; no
failed request was resubmitted. The Gemma provider responded to every attempt,
but HTTP 200 in its original strict phase did not imply schema compliance. The
provider adapter was separately frozen, makes the same schema model-visible and
permits one enclosing JSON fence only; it does not map verdict aliases or repair
formulas. Compiler continuation stopped at the declared capability gate.

Finite server workers use supervisor with automatic restart disabled and no
exposed ports. Existing production/business tools were not invoked. Raw requests,
replies, ledgers and protocols were copied off the server and committed. Model
request bodies contain source fixtures and schema, not authorization headers;
keys are absent from research artifacts. No unrelated shared server jobs were
stopped or modified.

All seven new phase prediction files reproduce byte-for-byte with unchanged
HTTP ledgers in the Pydantic 2.13.5 replay environment. The historical graph
replay separately uses Pydantic 2.10.3, consumes zero new tokens, and reproduces
the previous 94-response cache. Its original 399,533 tokens are historical and
excluded from the table. Source code hashes normalize CRLF for cross-platform
replay; source text and evidence spans retain original source characters.

Machine-readable totals and byte hashes:
`outputs/searh_23/semantic_hybrid_v4_diagnostics_20261004/aggregate_and_replay.json`.
Exact runtime/settings/prompt sources, request identities, manifests and raw
locations are retained under the respective phase output directory.
