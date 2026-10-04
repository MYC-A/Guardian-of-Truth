# Independent model-stage review

**Source/transport/controller integrity passed. A frozen model-interface
classification defect is confirmed and limits causal interpretation.** No
runtime, input, selector or frozen prediction was changed. The reviewer made
zero inference calls. Evidence is in
[model_stage_code_audit.json](../../outputs/retrieval_bakeoff_v1/model_stage_code_audit.json).

The reviewed protocol is
`4a4c4bb630aac8108afe93d91a73e5eec55af884f35ca9c421ed2bf39d1ea5d5`,
frozen through commits `968a49f1` and `0c5c7b19`. All **610 model-input seal
entries** matched their saved bytes after execution.

## Actual comparison boundaries

The frozen development winner is B1; the intermediate is `local_bm25`. Impact
uses supported-A Telecom plus airline and banking diagnostic cases. Airline and
banking A remain unsupported and make no call. The final banking intermediate
is skipped to reserve the mandatory S2G slots.

| Prepared impact request | Eligibility | Full request reservation |
|---|---|---:|
| Telecom A | Supported inherited baseline | 17,836 |
| Telecom B1 | Eligible | 19,220 |
| Telecom local BM25 | Same exact wire body as Telecom B1; cache reuse | 19,220 |
| Airline B1 | Eligible | 21,780 |
| Airline local BM25 | Eligible | 22,172 |
| Banking B1 | Eligible | 25,226 |

Six eligible impact slots therefore contain five distinct wire requests. Twelve
slots are reserved for three S2G cases: airline/banking missing-reference cases
and a retail complete-reference control. The transport checks the shared
18-request/130,000-token ceiling for every request. Reservations include the
full serialized prompt/schema, output cap and template allowance; a common
20,000 source-byte bound is not an equal provider-token charge or guarantee
that every planned call will fit.

There is **no C/fusion API arm in this frozen model plan**. Its results support
offline retrieval comparisons, not binary-F1 or model-cause claims for fusion.
A retains its original, different read units; unsupported cases are technical
nulls, not clean moves. The supported Telecom A/B1 comparison has no selected
history in either packet, so it does not independently test history-based
recovery. Every eligible saved request matched the unchanged I4 body rebuilt
from its saved review packet.

## Query multiplicity and attribution

The existing scorer uses `set(terms(query))`; installed BM25S sums score columns
for every query token, including repeats. This was verified from implementation
and saved query token counts, and agrees with the separate
[equivalence diagnostic](../../outputs/retrieval_bakeoff_v1/bm25_equivalence_diagnostic.json).
Shared Unicode tokenization and k1/b parameters do not make local BM25 and B2
equivalent. Their difference cannot be attributed solely to sparse indexing.

B1/B2 contribute one lexical ranking. B3 splits available literal aspects; prose
cases can still have one aspect, while the retail control has three. C adds
exact and recorded-graph rankings. Flat RRF gives each list a vote, so lexical
vote mass varies with aspect count. B1 versus C changes query construction,
channels and sometimes fusion; it is not a single-mechanism ablation.

Within the frozen offline design, `bm25_exact_graph` versus `rrf` holds the
candidate lists fixed and changes round-robin to RRF; `rrf` versus `coverage`
holds rankings/fusion fixed and changes selection. Those are narrower contrasts.
The reviewer did not rerun or tune them.

## Preserved classification defect

`review_packet().candidate_norm()` calls strict `decode_json()` on the **entire
original native result source**, including its transport prefix. For example:

```text
h8: \t← TOOL_RESPONSE get_user_details: {
h7: \t← TOOL_RESPONSE get_reservation_details: {
```

The native parser recognizes their payloads as valid JSON. Direct JSON decoding
of the prefixed text fails, so the frozen helper puts these factual receipts
inside `normative_sources`, removes them from `history`, and admits their IDs
in the Norm schema namespace. Their original `kind=result`, `category=HISTORY`
and `role=assistant` metadata remain unchanged. Thus correct source bytes and
actor metadata do not establish correct semantic source classification.

Observed scope is **two of 18 prepared jobs**, two of 17 submitted/cache-reused
job names, and **two of 15 actual HTTP requests**: `00_S0` includes h8, and
`00_S2` includes h8+h7. If the same frozen review helper were applied to every
saved offline packet, 208 of 600 would expose this JSON-prefix problem:
airline 104, retail 60, Telecom 44, banking zero selected. The original banking
corpus nevertheless contains six JSON receipts. These are structural counts,
not a claim that every JSON result can never contain normative material.

Both affected final replies were correctly rejected as
`ADMISSION:EVIDENCE_REFERENCE_OR_ACTOR_INVALID` and remain **technical nulls**.
Raw evidence mislabels h8 as system in S0 and h8+h7 as system in S2; originals
are assistant. Their raw norm references were q10/q7/q10, not h7/h8. Placement in
the normative array could contribute to actor confusion, but **causation is not
proven**. No controlled channel-assignment counterfactual was run. The frozen
defect and replies were preserved, without post-hoc repair or reinference.

## Completed source/controller checks

The independent audit verified all **eight saved S2G packets and 94 source
records** against original slices, catalog identity, hashes, 12-read/20,000-byte
bounds and seed retention. S2 admitted at most four new distinct reads. It
verified all 15 raw/request hashes and usage records: **90,419 known and charged
tokens**, zero unknown usages, one pinned provider/model.

An independent replay ran against temporary byte-identical copies, preserving
the originals: **PASS, zero new HTTP**, 15 request records, 18 semantic rows and
all three reconstructed gap/controller outcomes. The retail plan requested
declaration ID d4 outside the readable catalog. Atomic validation rejected it
as `GAP_CANDIDATE_NAMESPACE_INVALID`: zero admitted new reads, no S2 source
packet, no final reviewer request, and a null decision rather than UNKNOWN/0.

The post-hoc metrics script is outside the freeze. Its eight source/cost checks
were independently confirmed. Its `new_required_count` counts distinct spans
from the declared category union, excluding alternative-only units; it is not
semantic sufficiency. Exact source recall and controller bounds remain valid
findings. Clean semantic-grounding, correct-cause or architecture-improvement
claims must also account for the preserved classification defect and admission
failures. No additional execution blocker was found beyond that defect.
