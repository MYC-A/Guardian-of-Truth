# Native source completion: separate diagnostic mechanism

2026-10-08. `scripts/qwen_source_visibility_audit.py` reconstructs all 46
archived B2 requests from original inputs and saved neutral pre-analysis replies.
Every caller request SHA and **actual dispatched cache key** matches the frozen
record (local endpoint :8081). The caller SHA alone would be insufficient: the
Hook injects additional data after that SHA was computed.

Whole native source completion changes 7/46 source views, including two saved
FN rows. Five changed rows already have binary ERROR. This is evidence
availability, not seven recovered errors or any new model prediction.

One FN is retail36, previously identified as a possible annotation inconsistency.
The other is the telecom contract-end case: original h10 contains L1002,
status Suspended and contract_end_date 2025-01-31. It is absent from the original
ordinary review and neutral pre-analysis views. The old reviewer explicitly
leaves contract expiry unresolved. A later original-source result is therefore
a measurable retrieval opportunity. Source-call correspondence, policy scope
and semantic application still need review; a literal ID match does not prove them.

## General mechanism

`experiments/guardian_binding/source_completion.py` scans original native JSON
result events for exact typed scalar values used in current calls. Exact
terminal-field+value matches rank before value-only matches. Whole original
events retain spans, SHA, chronological order and receipt status. Possible
preceding calls are retrieval candidates; ambiguous lineage is explicitly
unauthenticated. Failed and stale results remain visible.

The helper changes no decision and has `RETRIEVAL_ONLY` authority. Existing
coverage remains unchanged; syntax-scan completeness never means semantic
closure, latest state, entity ownership or policy proof. Budget skips and parse
gaps are recorded. Values, tool names and benchmark IDs have no business rules.

This mechanism **uses current values**. It is a distinct arm from the fixed-source
value-blind pilot and must not be reported as blind retrieval.

25 helper tests and 25 independent scoring tests passed; together with blind,
compact and pilot tests, 110 passed. The source-completion helper currently has
author tests and root review. A requested additional independent code/logic
review could not execute because both subagents returned an account usage-limit
error; it is not counted as completed independent review.

## Scoring corrections before final phase-2 scoring

Gold must be inside the expected input inventory; cohorts must be disjoint.
Additions are strictly bool/null. Two unlabelled runtime external inputs are now
listed even though they are absent from the 68-key gold. Archived baseline has
72 records / 70 IDs: two duplicates differ solely in known transport `cached`
flags. The loader accepts only this metadata equivalence and records duplicate
IDs; altered raw replies, keys, admission or predictions are rejected.

No model prediction or historical gold changed for these corrections. Final
phase-2 cause adjudication remains necessary after complete inference.
