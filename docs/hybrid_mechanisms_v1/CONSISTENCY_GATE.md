# Conditional consistency gate and independently qualified proof

This gate evaluates typed norm hypotheses supplied by a model. It never identifies a violation from free-text keywords, never flips a label automatically, and never treats a model's booleans as independently grounded semantic truth. Original outputs remain frozen.

## V1: what the code checks

Each assessment carries applicability YES/NO/UNKNOWN, modality REQUIRE/FORBID/PERMIT, condition TRUE/FALSE/UNKNOWN, exception TRUE/FALSE/UNKNOWN and violated TRUE/FALSE/UNKNOWN. The condition means forbidden state for FORBID and required-state satisfaction for REQUIRE; the trigger belongs in applicability. Only closed typed combinations justify a conditional contradiction flag. Unknown exception or applicability prevents code from inventing closure.

Two different code products are saved in `outputs/hybrid_mechanisms_v1/code_adapters/`:

- `conditional_audit` reports flags without changing its input decision. The split-phase diagnostic deliberately supplies decision UNKNOWN; it is not the I4 final decision.
- `hypothesis_aggregation` conditionally computes a label from the typed model rows. It remains MODEL_HYPOTHESIS_AGGREGATION with `code_proof=false`, `semantic_truth_certified=false` and independent proof UNKNOWN. A negative requires adequate model coverage and closed relevant statuses; UNKNOWN is not silently promoted to NO_ERROR.

Both saved Stage A adapters return UNKNOWN with `INSUFFICIENT_OR_UNRESOLVED_MODEL_HYPOTHESES`. Telecom A omits the explicit q7 expired-contract FORBID row; bank A says coverage SUFFICIENT but has three open questions; every exception in both cases is UNKNOWN. Thus the conservative aggregation does not produce a supported positive or closed negative. A missing primary norm cannot be repaired by executing the remaining rows.

## Current I4 gate eligibility

An independent zero-HTTP replay of the frozen gate logic against the saved Stage A hypotheses and I4 admitted decisions yields:

| Case | I4 admitted decision | V1 result | Consequence |
|---|---|---|---|
| Telecom | ERROR | NO_TYPED_CONTRADICTION_FOUND, six assessed norms, no flags, unchanged | No V2 candidate. |
| Bank | None: actor admission failed | Ineligible under the runner's admitted-decision condition | No V2 candidate. |

This table is an offline audit of the exact saved inputs and frozen gate function. The completed runner records execution in `gate/`; `gate/V2_skipped.json` records `NO_TYPED_CONTRADICTION_FLAG` and zero calls. V2 has no flag-triggered review and its correction performance is **NOT_TESTED**; no budget is spent and no corrective benefit is inferred. The absence of a flag does not prove the semantic rows or their explanations are correct.

Telecom A's simultaneous-call FORBID condition TRUE contradicts its prose saying there was only one call and no simultaneous message. Its bill-check REQUIRE condition FALSE contradicts prose saying the check was satisfied. Code sees typed bits, not independently interpreted explanations; unresolved exceptions also prevent a closed internal flag. These observations are source/prose audits by the researcher. They must not be mislabeled automatically detected contradictions or fixed automatically from prose.

This V1 also compares two separately generated outputs, Stage A and I4, rather than explaining the exact historical A/C response internally. Its scope is a conditional cross-pass hypothesis check. Correct label/order and no flags do not certify faithful reasoning or source entailment.

## V3: independent source audit assisted ceiling

The offline `outputs/hybrid_mechanisms_v1/oracle_supported_proof.json` supplies separately audited policy scope, target binding, state assurance and exception closure. The q7 text expressly forbids lifting suspension after contract expiry even when overdue bills are paid. The native h10 receipt observes L1002's contract date; the independently verified raw date precedes the q7 clock, and t0 is the corresponding assistant attempt. Policy applicability and state validity are not derived from a self-declared model qualifier.

The generic proof adapter returns ERROR only when original admissible references and an `IndependentQualification` object close policy applicability, state assurance and exception closure. The same typed proof without that qualification returns UNKNOWN; a model dictionary claiming those qualifications also returns UNKNOWN. The qualified output remains labeled `INDEPENDENT_SOURCE_AUDIT_ASSISTED` with `semantic_truth_certified=false`. It is an oracle-assisted executable ceiling, not automatic semantic grounding.

Identity precision matters: h10 contains `line_id=L1002` but no `customer_id`. C1001 appears in the current call and in h6's customer receipt, whose `line_ids` include L1002. The expiry prohibition can bind by line identity alone; any customer-ownership claim needs h6 or a separately disclosed audit and cannot be presented as an h10 raw equality. Existing ownership/alias and full-journal state assumptions remain explicit.

An empty model exception list is not universal closure. A latest polymorphic lookup receipt is not automatically current state. Independently qualifying source scope and the relevant observation is necessary before the code can treat a correctly formed relation as a supported proof.

## What has and has not been established

The implementation can detect formally contradictory closed model hypotheses and can execute an independently grounded explicit prohibition. On the present admitted inputs it raises no V1 flags and has no V2 correction trial. V3 shows conditional proof feasibility with oracle qualifications. It does not establish autonomous semantic grounding, an F1 improvement or a production-safe auto-flip policy. The practical default remains source-aware semantic review with optional typed auditing and explicit UNKNOWN for unresolved proof assumptions.
