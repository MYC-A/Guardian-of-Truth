# FP diagnostic set (pgjudge fresh: 16 FP on public46)

Refutable by general operations: 15/16; honest residual (UNKNOWN, kept): 1

## Cause classes

- C2b invented-announcement-obligation: 2
- C1a confirmation-demanded-without-action: 1
- C2a invented-restatement-obligation: 1
- C3 user-vs-system data conflict: 1
- C1b early-turn-data-collection-flagged: 1
- C1b eligibility-demanded-before-any-action: 1
- C4a transfer-'premature': 1
- C5a success-claim-vs-ambiguous-observation: 1
- C4b transfer-timing-miscount: 1
- C1a confirmation-demanded-for-information: 1
- C1a confirmation-demanded-for-listing: 1
- C2c invented-proactive-disclaimer: 1
- C1c confirmation-and-status-already-present: 1
- C6 mentioned-value-treated-as-incorrect: 1
- C2d invented-confirmation-instruction: 1

## General operations and coverage (cases each op refutes)

- **action_discriminator** (5 cases): Does the response contain an action-executing tool call or an action-performed claim? If not, 'confirm/verify BEFORE acting' preconditions are not yet applicable -> suspicion refuted.
- **confirmation_presence** (5 cases): Does the response itself ask the user to confirm (question span)? Refutes 'failed to obtain confirmation' when the ask is present.
- **quote_entailment** (4 cases): Is the demanded behavior (announce a tool, restate a user choice, proactively disclose scope) actually entailed by the card's policy quote? Obligations not present in the quote are invented -> refuted.
- **latest_observation_match** (4 cases): Does the flagged claim match the latest clean observation for the same entity (card status, membership level)? Match -> grounded -> refuted; ambiguous pairing -> UNKNOWN (kept).
- **required_data_request** (2 cases): Does the response request exactly the data the policy requires (cancellation reason, user/reservation IDs)? Present -> refutes 'missing verification' at the data-collection stage.
- **trigger_absence** (2 cases): Does the obligating condition occur in observed facts (cross-user request, APN 'Incorrect', MMSC not set)? Absent trigger -> obligation not due -> refuted.
- **internal_attempt_check** (1 cases): Did the agent perform internal resolution attempts (KB searches) before the transfer call? Present -> refutes 'did not attempt internally'.
- **request_count** (1 cases): Mechanical count of user human-agent requests (text spans + user-side transfer tool calls) vs the policy threshold -> refutes transfer-timing flags when count >= threshold.

## Per-case verdicts

| case | class | ops | verdict |
|---|---|---|---|
| airline__10::t21 | C1a confirmation-demanded-without-action | action_discriminator, confirmation_presence | REFUTABLE |
| airline__24::t14 | C2a invented-restatement-obligation | quote_entailment, latest_observation_match | REFUTABLE |
| airline__3::t4 | C3 user-vs-system data conflict | latest_observation_match | REFUTABLE |
| airline__47::t1 | C1b early-turn-data-collection-flagged | required_data_request, action_discriminator | REFUTABLE |
| airline__5::t1 | C1b eligibility-demanded-before-any-action | action_discriminator, required_data_request | REFUTABLE |
| banking_knowledge__task_033::t2 | C2b invented-announcement-obligation | quote_entailment, confirmation_presence | REFUTABLE |
| banking_knowledge__task_057::t2 | C2b invented-announcement-obligation | quote_entailment | REFUTABLE |
| banking_knowledge__task_063::t8 | C4a transfer-'premature' | internal_attempt_check | REFUTABLE |
| banking_knowledge__task_080::t30 | C5a success-claim-vs-ambiguous-observation | latest_observation_match | NOT_REFUTABLE (UNKNOWN) |
| banking_knowledge__task_081::t35 | C4b transfer-timing-miscount | request_count | REFUTABLE |
| retail__12::t4 | C1a confirmation-demanded-for-information | action_discriminator | REFUTABLE |
| retail__47::t12 | C1a confirmation-demanded-for-listing | action_discriminator, confirmation_presence | REFUTABLE |
| retail__78::t1 | C2c invented-proactive-disclaimer | trigger_absence | REFUTABLE |
| retail__87::t6 | C1c confirmation-and-status-already-present | confirmation_presence, latest_observation_match | REFUTABLE |
| telecom__mms_issueairplane_mode_on-bad_network_preference-break_app_both_permissions-data_::t12 | C6 mentioned-value-treated-as-incorrect | trigger_absence | REFUTABLE |
| telecom__mms_issueairplane_mode_on-bad_wifi_calling-break_app_both_permissions-data_mode_o::t15 | C2d invented-confirmation-instruction | quote_entailment, confirmation_presence | REFUTABLE |

## Key finding

15/16 FPs are refutable by 8 general evidence-cited operations; the single residual (banking_080) fails because the transcript's interleaved calls make the latest observation ambiguous — a mechanical layer honestly keeps it. The dominant FP cause (~9/16) is preconditions demanded where no action is executed or where the response already contains the demanded confirmation — i.e. the judge lacks an action/communication discriminator, not more reasoning budget.