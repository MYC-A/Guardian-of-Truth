# Frozen retrieval bakeoff protocol

Base: `f89d271b21deeb5e2820a8c9111857223ca26015`. Worktree/branch:
`Guardian-retrieval-bakeoff-v1-20261004`,
`research/retrieval-bakeoff-v1-20261004`. No production integration.

Fifteen original known valid46 cases and independently source-audited references
are frozen before retrieval scoring: eight development, seven evaluation_known.
The evaluation set is previously exposed diagnostic data, not hidden holdout.
Runtime input contains prompt/response only; original IDs and split identify
experiments but do not control retrieval. Labels/references belong to the scorer.
No selector tuning is permitted after evaluation results are revealed.

The exact code/fixture/source/parameter/package hashes are in
`outputs/retrieval_bakeoff_v1/protocol.json`. An earlier preparation draft was
retained separately before independent code review; neither draft nor current
preparation made inference calls. Commit and push the final preparation before
offline evaluation and before any model request.

## Offline design

Run unchanged imported `coverage_plan()` as A. Its intrinsic eight-read limit
and unsupported input formats are retained; do not port it silently. It reads
original complete policy sections/events. New adapters share a canonical catalog
of original events, heading boundaries and explicit <=4000-character windows.
Every window retains a SourceStore-issued ID, parent ID, original document,
offsets, actor/kind and exact text. Different read units are exposed, so compare
text cost as well as number of reads. A twelve-read allowance never modifies A.

Compare existing local BM25, actual BM25S B1 action/operands, B2 with declarations
and target prose, B3 separate literal aspects; exact+graph, BM25+exact,
BM25+exact+graph, RRF, and coverage selection. Unicode word tokenization is
explicit, without stemming or library-default stopwords. Fusion controls use
round-robin; RRF uses constant60; coverage adds available-category/actor/tool
diversity and generic potential-exception navigation. None proves applicability.
Graph candidates use qualified unique receipts and existing co-recorded edges.

Each method runs at eight and twelve retrieved reads, with and without a 20000
conservative source-token bound. UTF8 bytes of serialized complete source
records are the bound, not a claimed provider-token count. Full targets and
their declarations are mandatory and charged in text/token cost separately from
retrieved reads. Never crop text to fit. Over-budget mandatory context is an
explicit failure. Windows have explicit offsets/parent incompleteness.

Score original-span unions against independently annotated normative/history/
target/declaration/exception/entity-binding/long-distance units. At least one
known valid alternative set must be covered for complete-set success. Two
partial references remain explicitly partial; even a complete reference set
does not certify all-policy completeness or NO_ERROR. No source absence in a
subset establishes absence in the full journal.

Select the best method on development k8 only: most complete reference sets,
then required-unit recall, then least serialized source UTF8 bound, then fixed
method order. Evaluation results are reports, never selection input. Keep all
negative results and packet omissions.

## Model and S2G stages

One provider/model: Mistral `ministral-14b-2512`, temperature0, strict JSON
schema, I4 decision last with explicit labels, output1700; gap output1000.
Verify current availability before the first inference. No provider switch,
retry, weight download or local model server. Reuse the existing durable Client
with a new global ledger: **18 requests / 130000 known or conservatively charged
tokens**, input UTF8 bound plus output cap/template allowance; timeout120s.

Impact includes the first development case supported by original A plus up to
two selected S2G cases. Compare A/best/intermediate under identical review
interface and k8/20000 source bound. Unsupported A makes no model call. Limit
impact to six actual planned calls by dropping final intermediate cases in
fixed case order, preserving twelve request slots for the mandatory S2G stage.
Exact equivalent requests use the cache rather than another call.

Select S2G cases from development only: two missed best-k8/20000 reference sets
from different domains plus a complete-set control, preferring a third domain.
If unavailable, disclose the closest partial control. Freeze the exact selected
cases/packets/requests in a second commit after offline scoring and before
inference; no model-output-driven choice.

S0 uses best k12/20000. S1 uses best k8/20000 plus deterministic native
dependency/entity-neighbor extension to the same total bound. S2 starts with
the same eight-read seed, gets one gap API call, and adds at most four new
distinct original source windows to the same twelve-read/20000 source bound.
Validate namespaces before all search/read changes. Retain the seed; a failure
to retain it blocks the review. Invalid plans do not get a final reviewer call.
No repeated full reads. Preserve concrete questions, proposed/repeated IDs,
model sufficiency, source accumulation and exact final admission.

Official trained S2G-Judge/LoRA is **OFFICIAL_S2G_NOT_EXECUTED**. This explicitly
separate **S2G_INSPIRED_API_BASED** diagnostic does not inherit the paper's scores
or trained sufficiency calibration. A model sufficient=true is an opinion,
not proof. Original originals and actors remain authoritative.

Compare evidence gains and source-grounded final reasons; right ERROR with a
wrong accusation is not success. Actor/ID admission, causal scope, exceptions,
UNKNOWN and technical nulls remain separate. UNKNOWN maps to binary0 only as a
declared semantic projection; technical failures stay unscored.

After both stages: independent source/logic audit, raw/request and controller
replay without HTTP, regressions, final artifacts, commit/push, then stop.
