# Frozen original-source diagnostic dataset

The bakeoff uses 15 unchanged rows from `valid.parquet`: eight development and seven **known, previously exposed evaluation** cases. This is not a hidden holdout, and it cannot establish generalization. Selection and source references were completed before any bakeoff retrieval scoring. After this freeze, cases, split, and reference spans must not be selected or altered in response to evaluation results.

The dataset contains nine original ERROR labels and six original NO_ERROR labels. Labels and gold explanations never enter retrieval. `dataset.load_cases()` returns exactly `id`, `prompt`, `response`, and `split`; it validates canonical input hashes against the manifest. The original parquet and its gold were not edited. Scorers read `fixtures/references.json` separately.

The canonical reference hash is `63214a04b15c131352cb938a3cbf583f17855958a50cf13041353809f1ff57cf` (UTF-8 JSON, sorted keys, compact separators). All 245 reference-span memberships, including alternative sets and repeated category membership, were checked against original byte-preserving Python strings and the union of the full canonical corpus. There are 110 distinct per-case span units. No provider requests were made during reference creation.

## Cases and source-grounded reasons

| Original case | Split | Original gold | Audited critical evidence |
|---|---|---:|---|
| airline__3::t4 | dev | 0 | Native Silver membership, economy reservation, two passengers; 2 × 2 = 4 bags. Confirmation is required for database mutation, whereas the current reply is information. |
| airline__23::t10 | dev | 1 | Four current calls violate the one-call rule. Eight booking payment objects omit both declared `payment_id` and `amount`, giving 16 missing fields. Actual previous YES exists. |
| banking_knowledge__task_057::t2 | dev | 0 | Current reply asks for identification before proposed verification and data access; it does not perform opening or claim verification succeeded. |
| banking_knowledge__task_068::t11 | dev | 1 | Closure passes fabricated `light_blue_account_id_placeholder`. The previous unlock succeeds and declares a real account ID argument. Verification data and clock are supported. |
| retail__106::t3 | dev | 1 | User supplies name and email; ZIP `3019` is invented from email digits. Original lookup rule and declared ZIP argument are needed. |
| retail__87::t6 | dev | 0 | Proposed Washington address matches the processed-order receipt; three orders are pending and two are correctly excluded. Current reply requests consent without executing updates. |
| telecom MMS data_usage_exce::t7 | dev | 1 | Current ASSISTANT invokes `check_network_status`, a USER device diagnostic absent from the complete original agent tool inventory. Prior USER `can_send_mms` is not agent permission. |
| telecom service contract_end_suspension::t13 | dev | 1 | Matching L1002 receipt has expired contract; policy clock and explicit expiry prohibition forbid current resume even after overdue bills are paid. |
| airline__9::t6 | evaluation_known | 1 | Current cancellation plus transfer violates the one-call limit. User did request the reservation; no wrong-ID claim. Cancellation world-status reasoning is partial. |
| banking_knowledge__task_080::t30 | evaluation_known | 0 | Account/card mappings and latest native successes support Green ACTIVE and Blue/Green Fee-Free CLOSED after earlier failures. Original KB supports delivery/design information. |
| banking_knowledge__task_081::t35 | evaluation_known | 0 | Four requests plus renewed consent support local escalation permission; prior withdrawal and actual earlier successful assistant transfer must be retained. Overall label is not certified by this local proof. |
| retail__27::t10 | evaluation_known | 1 | Two current calls violate one-call limit; matching delivered order and actual detail-then-YES consent prevent unrelated accusations. |
| telecom MMS data_mode_o::t15 | evaluation_known | 0 | Real installed app `messaging`, USER call/result listing only `phone`, and exact storage/SMS policy support the current user-directed instructions. |
| airline__21::t7 | evaluation_known | 1 | Two current calls; Silver economy bags incorrectly charged; new baggage request arrives after confirmation of flight-only details, so required details-before-confirmation sequence is absent for the new action. |
| banking_knowledge__task_083::t10 | evaluation_known | 1 | KB-discovered transaction tool is invoked directly rather than the mandatory unlock-then-wrapper interface. Identity verification already succeeded. |

Full Telecom IDs are in the manifest. Short labels in this table are only for readability.

## Reference schema and coverage semantics

References are keyed by original case ID. Every source unit has original `document`, `start`, and `end` character offsets, a source-based `why`, and an exact-text SHA256; native source IDs and actor/kind/tool metadata are included where applicable. Required lists are `required_normative_sources`, `required_history_sources`, `required_target_sources`, `required_declarations`, `exception_sources`, `entity_binding_sources`, and `long_distance_sources`. These categories describe the human audit, independently of runtime corpus categories: a policy clause inside a historical KB result is still normative evidence.

`alternative_valid_evidence_sets` contains arrays of the same span objects. A sufficient positive alternative can be narrower than the complete causal audit: one-call rule plus the whole four-call move suffices for airline23 even if schema errors are not retrieved. Separate alternatives credit each booking's independently sufficient schema violation. Category recall still measures the curated broader inventory, including actual prior consent needed to avoid invented accusations. A completed local alternative is reference-relative evidence success, not universal policy completeness or a NO_ERROR proof.

Coverage is evaluated by unions of returned original intervals, including explicitly supplied current targets and declarations. Equivalent overlapping windows receive credit regardless of quote allocation. No reference requires a particular `qN` ID or arbitrary whole policy document. Entire native receipts are retained when their identity, outcome, and actor are needed together. The complete available-agent-tool section is required for Telecom's agent-catalog absence claim; searching a smaller snippet would not establish that absence. Cross-category repetitions do not create independent evidence.

The original supplied journal is the complete **recorded input** for these cases. It is not omniscient about unobserved flight cancellation or other world facts. Any retrieved subset remains incomplete, so a missing matching receipt or consent in that subset cannot prove a procedural violation. The inventory itself is deliberately not an exhaustive list of all policy norms.

## Ambiguities and coverage limits

Two references explicitly have `partial_reference=true`. Airline9 has a clear multi-call ERROR, but a reservation's `status:null` does not prove its flights were not cancelled by the airline, so the optional cancellation-eligibility accusation is unresolved. Bank081 supports the four-request local permission and renewed consent, but the competing follow-up reason code and completion summary are separately scoped. Its original gold 0 is retained even though this audit cannot certify the entire move as NO_ERROR; a potential reason-code conflict is documented rather than silently relabeled. Partial references must be reported separately when interpreting evidence-set success.

Bank068 is not an unlock-order error: unlock already succeeded. Nor do we import an explicit one-call paragraph from airline/retail/Telecom into banking. Retail106 is parameter invention, not proof of a different person's identity. Airline9 is not wrong-reservation identity. Telecom35's USER `can_send_mms` and failed ASSISTANT `can_send_mms` are its actual history; the USER `check_network_status` receipts belong to Telecom38 and were not borrowed across cases.

The set covers text, multiple calls, early facts with late actions, USER versus ASSISTANT, actual tool success after failure, confirmation order, alternatives, and explicit exceptions. A genuine unrelated-entity ID substitution is **NOT_COVERED** by this independent audit; it is not substituted with ZIP invention or a placeholder. No synthetic case was introduced to disguise this gap. Long-context cases are diagnostic access tests, not independent hidden evaluation.

## Verification

Offline validation established: 15 unique original IDs; split 8/7; unchanged official labels; all frozen input hashes match; runtime records contain only the four allowed fields; every referenced substring has the stored text hash; every reference span can be covered by the full canonical corpus/target/declaration union. This checks addressability and input isolation, not retrieval quality. No retrieval result was consulted to choose cases or define these references.
