# Bounded source discovery: observed coverage and failures

Independent original-source review of saved R0, R1 and coverage final replies. Exact row provenance and component annotations are in `outputs/hybrid_mechanisms_v1/retrieval_causal_logic.json`. This review made zero inference calls and left frozen artifacts unchanged. All three arms concern one already-known positive valid46 telecom case; none establishes held-out F1 improvement.

## Read contract and comparator

The controller admits at most eight **distinct complete selected sources**, with at most two planning rounds in this experiment. It validates all IDs and operations before mutating a round. Every admitted read retains exact original offsets and reconstructs the full selected source from validated windows; search snippets are navigation only. Repeated reads do not create additional evidence. MODEL_DECLARED_SUFFICIENT is a model hypothesis, not certified journal completeness. Reaching READ_LIMIT is a resource stop, not proof that the original input has been covered.

R0 reuses the historical one-shot **plan** only after exact initial catalog/request equality. It does not reuse a historical budget-stopped final answer. A new I4 final review is charged. R1 obtains a new plan from the catalog and prior-read/gap state. The coverage arm uses generic literal action-word overlap and target-operand matches plus earliest/latest receipt diversity; it does not use labels, row IDs or business-specific tool rules. Complete original declarations are supplied in every final packet separately from discovered sources.

| Arm | Planning/final HTTP in this phase | Accepted rounds / complete reads | Original source IDs read | Final raw / admitted |
|---|---|---|---|---|
| R0 historical one-shot plan | 0 new plan + 1 final | 1 / 8 | q7, q9, q17, q10, q11, q12, q15, q24 | ERROR / ERROR |
| R1 adaptive planner | 1 plan + 1 final | 0 / 0 | None | ERROR / rejected |
| Generic coverage selector | 0 model plan + 1 final | 1 / 8 | q7, q17, h5, h6, h33, h34, h9, h10 | ERROR / ERROR |

All final replies emit decision last. Both successful controllers stop at READ_LIMIT. R1 has no accepted round and a null internal stop reason; the actual termination is separately recorded as `ValueError:GAP_SOURCE_NAMESPACE_INVALID` in `retrieval/R1_plan_failure.json`. The four inference requests in this phase are the three finals and the single R1 plan; no second R1 plan was issued and no failed-plan evidence was silently admitted.

## R0: right label for the wrong cause

R0 retrieves the main policy q7 and suspension procedure q17, but spends all eight reads on normative sections. It retrieves no history. Its final ERROR claims that the assistant attempted `resume_line` without a user request or evidence of suspension and charges insufficient investigation. The original journal contains both: h32 explicitly requests restoration after payment, and h9/h10 performs a successful L1002 lookup showing Suspended and `contract_end_date=2025-01-31`. Moreover q7 does not impose the reply's blanket prerequisite that every tool call require an explicit user request.

The real current violation is the expired-contract prohibition in q7 against the explicit `2025-02-25` clock, independent of payment. R0 has read that prohibition but not its relevant state observation. Source-ID and actor admission succeeds because those IDs exist; that proves neither source entailment nor the absence asserted by the reason. This is a concrete **correct binary label with wrong cause** and demonstrates why binary F1 alone can reward a retrieval-induced accusation.

Even if the **original journal** is assumed complete, an eight-source retrieved subset is not a complete journal. An event's absence from that subset cannot establish failure to perform an obligatory check. Complete-history procedural reasoning becomes admissible only after the relevant event space has been covered under an explicit audit; it cannot inherit completeness from the original dataset merely because the underlying full input exists somewhere.

## R1: technical blockage, not measured recursive damage

The fresh first plan proposes reading q9, q17 and d9, and two searches. Its gaps put d9 in policy sources even though declarations are outside the selectable catalog, and place historical h8/h10/h34/h0 in `target_sources`, whose allowed namespace is current t0. The plan therefore fails whole-round validation **before** any read or search. q9/q17 were valid proposed reads, but there is no admitted prefix. h10 is named as a candidate; it was never retrieved. An empty visited list and an empty actual trace are the evidence of this distinction.

The final call nevertheless receives declarations plus the current target with zero discovered policies/history. It emits raw ERROR, charges missing status/ownership verification from that empty history, and invents `NO_POLICY_RETRIEVED` as a policy ID. Admission rejects those pseudo-IDs as `ADMISSION:NORM_REFERENCE_INVALID`. As with R0, unobserved checks in this subset are not established violations; original h6 and h9/h10 supply the relevant identity/status evidence. The reply's own open question about prior verification also conflicts with treating its absence as established.

This tests a planner/controller namespace failure and the behavior of a final reviewer after that failure. It does **not** test a functioning recursive search, cannot establish a negative semantic effect of recursion, and cannot support a comparison of recursive accuracy with R0. The initial prompt does provide separate source/target fields and a current-target inventory, but a future unfrozen phase should expose namespace enums prominently and record PLAN_INVALID as an explicit top-level termination status. Invalid plans should normally retain UNKNOWN or stop the final review rather than manufacture an unsupported accusation. Such changes were not retrofitted into this phase.

## Generic coverage: observed causal recovery

The generic one-shot selector reads q7/q17 and three native call/receipt pairs: customer h5/h6, bill h33/h34 and line h9/h10. Its final ERROR cites the L1002 expiry and payment not being a waiver. The decisive governing source, observed entity, date and current target now appear together. This recovers the correct core cause relative to R0 on the same known positive. The reply additionally attributes the specific expiry-related escalation requirement to q7 as well as q17; the detailed instruction resides in q17, so all-component norm fidelity is weaker than its correct core cause.

The oracle-selected I4 comparator already produced the correct expired-contract ERROR. Consequently the coverage arm demonstrates a useful evidence-selection path and repair of a **causal explanation** relative to R0, not a new binary detection or broad F1 gain. It is also one-shot code selection, not a successful adaptive model search. Native receipts remain observations; applicability, semantic aliases and state assurance require the disclosed source convention or independent audit. The eight-read limit never becomes an unrestricted current-state certificate.

## Architecture implication

Budget evidence reads for observed entity state and its caller/receipt pair as well as policy coverage. Preserve a real gap ledger for unvisited evidence, explicit plan-validation failures and the distinction between complete selected sources and complete journals. A simple coverage selector is a practical baseline before increasing planner complexity. A new paired holdout with functioning namespace-constrained plans is needed to decide whether recursive search helps. The present phase does not answer that question.
