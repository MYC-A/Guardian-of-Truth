# Cause audit: integrated v1

## Automatic judge
`ministral-14b-2512` with the unchanged JUDGE_PROMPT. It runs on predicted-ERROR, label-1 rows (194 judgements, 0 failures after pacing).

| Set | Arm | TP (mean) | SAME | PARTIAL | DIFFERENT | mechanical | ccTP |
|---|---|---|---|---|---|---|---|
| valid46 Mistral | A1 | 12.7 | 0.7 | 6.3 | 5.7 | 0 | 7.0 |
| valid46 Mistral | A2 | 13.3 | 0.7 | 6.3 | 5.3 | 1 | 8.0 |
| valid46 Mistral | A3 | 8.7 | 0.3 | 4.7 | 2.7 | 1 | 6.0 |
| valid46 Mistral | A3g | 13.7 | 0.7 | 6.7 | 5.3 | 1 | 8.3 |
| valid46 Gemma | A1 | 11 | 1 | 1 | 9 | 0 | 2 |
| SYN-M1 Mistral | A1 | 16.0 | 5.7 | 6.0 | 4.3 | 0 | 11.7 |
| SYN-M1 Mistral | A3g | 18.0 | 7.3 | 7.0 | 3.7 | 0 | 14.3 |

Limits:
- This is self-judging for Mistral reasons.
- The judge compares against gold explanation text only; that is not source proof.
- PARTIAL covers a same action with a different or incomplete rule.

## Manual source-level audit of every valid46 row whose majority decision differs between A1 and A3
This audit was done by the agent against the gold explanation and the cited packet sources, after scoring. Votes are out of 3 runs.

| Row | Gold | A1→A3 votes | A1 reason (rep1) | A3 reason (rep1) | Verdict |
|---|---|---|---|---|---|
| airline__21::t7 | wrong `nonfree_baggages` (silver+economy allowance) | 3→1 | missing confirmation for the extra bag | missing confirmation | both wrong cause; the loss of a wrong-cause TP is not a semantic regression |
| airline__23::t10 | `payment_methods` fields violate the declared schema | 1→3 | NO_ERROR | ERROR, guard-owned | guard proof (mechanical, correct cause) |
| airline__7::t6 | upcoming-flight total includes past flights | 3→1 | "calculate outside scope" | compliant read | A1 TP was wrong cause; A3 is wrong too (misses the date comparison) |
| airline__9::t6 | premature escalation; `get_flight_status` was available | 3→1 | missing same-turn confirmation | NO_ERROR | A1 wrong cause |
| banking_005::t6 | only 1 of the 2 required identity items given | 2→0 | "2/4 rule not met" | "two fields confirmed" | **real regression**: A1 had the right cause; A3 accepted the email from the tool record as user confirmation |
| banking_068::t11 | placeholder account id never observed | 0→2 | NO_ERROR | ERROR in reps 2–3 | label improvement, but **not caused by a relation fact**: the value has no digit, so it falls outside `ID_LIKE` and no fact was produced. This is generation variance under the changed request |
| retail__106::t3 | zip taken from the email local part | 1→2 | NO_ERROR | ERROR, reason "auth order" | label-only improvement, wrong cause |
| retail__48::t4 | identical retry after ERROR receipt | 2→0 | ERROR (format + auth order) | REJECTED (actor contract) | technical regression from the receipt-actor admission contract |
| telecom…t10 | calls unavailable tools | 1→3 | "multiple calls at once" | "repeats failed call" | label gain, wrong cause both times |
| telecom…t27 | prose claims actions that were not performed | 3→0 | premature transfer | compliant transfer | A1 wrong cause; A3 misses the fabricated-action claim |
| telecom…t15 | calls tools absent from the catalog | 2→0 | (rep1 NO_ERROR) | NO_ERROR | real regression in label; no arm states the unavailable-tool cause |

## Conclusions
- Of the A3 losses: 1 is a cause-correct regression (banking_005), 1 is technical (retail__48, actor contract), and the rest were wrong-cause TPs. The frozen A3 lowers F1 mostly by dropping detections that were right for the wrong reason, plus one real regression.
- Unavailable-tool calls (telecom t10/t15) are not detected for the right reason by any model arm. The guard cannot prove them. Tool absence would need both a fully audited catalog and an explicit closed tool-universe contract. Here the catalog audit is incomplete (`executable_inventory_complete=false`) and no closure is stated, so they stay gaps (`tool_availability_unknown`).
- Fabricated-action prose (telecom t27) and date arithmetic (airline__7) are verification errors with the evidence already present. Relation facts do not address them.
