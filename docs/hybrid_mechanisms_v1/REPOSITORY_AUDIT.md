# Reusable mechanisms and inherited experimental limits

This isolated worktree starts at
`6035918cdcef6d5600aecfd91bc2f01a4d5cf73c`, on
`research/hybrid-mechanisms-v1-20261004`. The audit reads retained code and raw
artifacts; no historical prediction or official label is repaired. Existing
production and earlier research code remain unchanged during this review.
There is no applicable AGENTS.md in this worktree or its ancestor directories.

## Components worth retaining

| Existing component | Reuse in this experiment | What it does not prove |
|---|---|---|
| [SourceStore](../../src/guardian_truth/source_search/store.py) | Complete immutable originals, source offsets, exact reads, typed entity lookup, bounded lexical navigation, co-recorded graph neighbors | Search absence is not semantic absence; co-recording is not ownership, permission or current truth. |
| [EvidenceGraph](../../src/guardian_truth/evidence_graph/graph.py) | Native event/target inventory, policy windows, declarations, original topology and integrity signature | Model-generated inventory, links and witnesses remain semantic hypotheses. REVIEWED is not proven policy completeness. |
| [Receipt qualification](../../src/guardian_truth/policy_table_v11/provenance.py) | Original assistant actor, valid JSON call arguments, unique call/result pairing | A call is not success. Parallel same-tool calls can remain ambiguous; a result marker alone does not prove an authorized effect. |
| [Native factual checking](../../src/guardian_truth/evidence_graph/facts.py) | Typed comparisons, native identity joins, selected-record lineage, prior chronology, strict result qualification | Correct values and joins do not establish the selected norm's meaning or role completeness. |
| [Mandatory-process research adapter](../../experiments/research_v5/process_grounding.py) | Explicit complete versus incomplete process contract; prior attempts and qualified Boolean checks; finite AND/OR | Missing world evidence never becomes false. Satisfied process requirements alone cannot certify whole-move NO_ERROR. |
| [Entity receipt view](../../experiments/research_v5/native_role_grounding.py) | Research-only alias-qualified filtering of unrelated unique observations | It does not rescue ambiguous receipts, ignore later same-entity changes or infer aliases automatically. |
| [Frozen Telecom review](../../experiments/telecom_causal_recovery/review.py) | Small source-constrained interface and actor/ID admission | Admission is not consistency, causal correctness or entailment. Its one-target assumptions are not a generic whole-move contract. |

The new experiment adds small adapters in
[experiments/hybrid_mechanisms](../../experiments/hybrid_mechanisms).
It does not replace SourceStore/EvidenceGraph or build another graph framework.

## Source and target limitations that matter

Native target inventory contains current call candidates. Actor/JSON validation
is a separate step. The old Telecom `extract()` accepts exactly one native t0
and assumes telecom policy tags; it is reused only for the explicitly disclosed
Telecom retrieval diagnostic. General source preparation retains current prose
and multiple assistant events. A current verification request is not an account
creation merely because an account-opening document shares its vocabulary.

Quote IDs qN depend on allocation order because source reads and search create
new quotations. Native IDs and exact offsets must be reconstructed consistently;
qID equality across independently mutated stores is insufficient. Search excerpts
are only 300 characters even when a returned source window is longer. Complete
reads reconstruct all bounded windows and assert exact equality with originals.
No summary becomes an independent factual source.

Original result qualification is intentionally strict. Four parallel same-tool
calls cannot be disambiguated from tool names alone. Separately, a polymorphic
read such as `get_details_by_id` can cause an unrelated bill result to shadow a
line observation in the old conservative latest-result filter. The V5 research
receipt view fixes that only when explicit typed alias relationships are supplied,
while checking original unfiltered receipt integrity first. This is an observation
validity boundary, not a license to delete inconvenient evidence.

## Historical measurements remain dataset-specific

The [binary-method audit](../research_v5/BINARY_METHOD_AUDIT.md) and its
[saved valid46 baseline table](../../outputs/research_v5/binary_audit/valid46_baselines.json)
record 46 known development rows: 23 positive and 23 negative. The archive is
aligned by exact IDs and original labels.

| Historical archive | TP | FP | FN | TN | F1 | Scope |
|---|---:|---:|---:|---:|---:|---|
| Guardian structural | 12 | 0 | 11 | 23 | 0.6857 | valid46 |
| Granite 3.3 | 16 | 2 | 7 | 21 | 0.7805 | valid46 |
| Guardian OR Granite | 20 | 2 | 3 | 21 | 0.8889 | valid46 |
| One-shot reported aggregate | 14 | 5 | 9 | 18 | 0.6667 | valid46; per-case snapshot not recovered |
| R0 counterevidence archive | 68 | 4 | 0 | 88 | 0.9714 | Different synthetic sealed160 |

These are retained historical results, not fresh inference in this experiment.
valid46 is not an independent holdout. The older formal pipeline also named R0
must not be confused with the Gemma/counterevidence variant.

V4's six identity/chronology UNKNOWN examples have an immutable original gold and
a separate [contract sidecar](../../outputs/research_v5/binary_audit/v4_label_sidecar.json).
Under complete mandatory-process history they can be ERROR: a check on another
entity or after the write does not satisfy a required prior check. Rescoring the
same Gemma A0 predictions changes TP/FP/FN from 7/3/0 to 10/0/3, and F1 from
0.8235 to 0.8696. That is a changed evaluation contract, not a model improvement.
Incomplete logs preserve UNKNOWN; absence of world authorization is not inferred.

The [actual R0 service configuration](../../service/configs/r0-service-v1.json)
guards model input at 12,000 characters. The retained
[network-disabled valid46 dry run](../../outputs/research_v5/binary_audit/r0_service_valid46_dryrun.json)
returned 11 ERROR/35 UNKNOWN, zero model calls, with UNKNOWN projected to binary
0 and F1=0.6471. Structural hits bypass the model guard; clean cases exceed it.
The sealed profile's larger outer limit still leaves an explicit inner 12k
head/tail window with omission metadata. It is disclosed truncation, but it
cannot establish full-source R0 transfer quality on valid46.

## What the last Telecom experiment actually established

The [raw-to-prediction failure audit](../telecom_causal_recovery/FAILURE_ANALYSIS.md)
and original artifacts show A/C's incorrect NO_ERROR already exists in raw model
JSON. A/B/C all explain the expired-contract prohibition; only B also outputs
ERROR. Source IDs, actor checks and replay preserve these decisions unchanged.
The frozen phase spent six calls and 45,089 known/charged tokens. One oracle-
selected positive cause recovery does not demonstrate improved valid46 F1.

AUTO retrieved normative sections, but no historical line receipt. Its final
review and payment counterfactual were BUDGET_STOP, not semantic UNKNOWN or
negative model findings. The new research must distinguish missing evidence
discovery, norm interpretation, output inconsistency and transport failure.
Decision-last, label definitions, structured decoding and model-specific behavior
are hypotheses awaiting comparable interventions.

## Engineering conclusions from inspection

Keep exact source storage, explicit target/actor inventory, strict native
receipts, typed joins, truthful coverage, separate absence contracts, bounded
transport and replay. Mechanical comparisons should remain small factual
relations with original provenance. Contradiction diagnostics should originate
from retained predictions and metadata, while acknowledging that a historical
citation can legitimately support a prerequisite.

The model remains responsible for normative scope, modality, semantic entity
roles and exception interpretation. Typed consistency can detect disagreement
between asserted fields, but cannot make a model's assertion true. New interface,
retrieval and aggregation results must be evaluated before choosing the minimal
architecture; inspection alone supports no accuracy or reliability promise.
