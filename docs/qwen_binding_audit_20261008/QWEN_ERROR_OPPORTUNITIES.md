# Qwen B2 error opportunities: frozen offline source audit

Read-only analysis of Git revision `51160fcd0b7b9354f8a63615430aeae0c95b591a` on 2026-10-08. No model calls, SSH, baseline changes or gold changes. This document proposes experiments, not measured improvements.

Inputs are the four development CSVs under `outputs/guardian_complementarity/inputs/`. Predictions are the corresponding `B2_rep1.jsonl` Git blobs under `outputs/guardian_local_a100/llamacpp/qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/runs/`. Colon-containing paths were read with `git show`, not Windows filesystem reconstruction. Duplicate IDs retain the frozen final record; this audit found the same counts as the existing independent metrics audit. Gold paths are recorded in `scripts/qwen_branch_metrics_audit.py`: original valid.parquet, external tau2v2, tau2h frozen gold, and holdout2 frozen gold. Development rows and previously exposed holdouts are not independent new evaluation.

## Concrete error inventory

| Cohort | Labelled rows | Saved binary FN | Saved binary FP |
|---|---:|---:|---:|
| valid46 | 46 | 10 | 1 |
| ext_tau2 | 68 | 14 | 1 |
| hold_tau2h | 51 | 7 | 1 |
| hold_holdout2 | 72 | 3 | 5 |
| Total | 237 | 34 | 8 |

These are the stored binary projection, including technical failures. Of the 34 FNs, primary admission is ADMITTED for 17, REJECTED for 16, and INVALID_JSON for one. Raw primary decisions are NO_ERROR for 31 and UNKNOWN for two; one is unparsed. Thirty blind pre-passes have valid JSON and four invalid JSON; 26 were injected and eight were not. Thus simply fixing JSON/injection does not explain most misses. The four invalid pre-passes are valid airline__7, ext_ret_000, ext_air_052 and ext_ret_062; the last also has invalid primary JSON.

All eight FPs have valid, injected pre-passes. Six have primary ERROR with final owner A_adm2; two have primary NO_ERROR overridden by Ems (ext_tel_015 and hold_tel_022). On these two, changing the primary reviewer alone cannot remove the final FP unless final ownership also changes. This is a concrete mechanism boundary, not an argument for suppressing every auxiliary finding.

## What independent argument binding could cover

Twelve nontechnical FNs have gold allegations involving selection of the wrong object, parameter or variant, with a thirteenth technically invalid row:

| Alleged binding family | Frozen FN examples | Count |
|---|---|---:|
| Wrong line for user's phone | ext_tel_008/011/037, hold_tel_052/069 | 5 |
| Wrong order/item | ext_ret_010/063 | 2 |
| Wrong/ungrounded payment choice | ext_ret_021, hold_ret_026 | 2 |
| Wrong reservation | hold_air_020 | 1 |
| Wrong maximum-price variant | ext_ret_060 | 1 |
| Wrong address/order plus independent mixed message/call error | ext_ret_041 | 1 |
| Wrong maximum-price variants; primary invalid JSON | ext_ret_062 | 1 technical |

This is a hypothesis-testing shortlist based on frozen gold, not thirteen established sound recoveries. ext_ret_041 has a separate turn-format error already sufficient for its label. Some binding allegations conflict with later user confirmation or require looking beyond assistant summaries.

Hiding current argument values is useful against direct copying from the current call. It does not establish independence from errors already in the history. The saved response-blind pre-pass already reconstructs exactly the current wrong arguments on ext_ret_010 and ext_ret_060. On ext_ret_010 it copies the assistant's proposed order and the later user yes. On ext_ret_060 it copies the assistant's proposed third replacement variant rather than independently maximizing over native product evidence. ext_ret_063 similarly selects the laptop order named by the assistant. These are observed pre-pass errors, not a theoretical concern.

A useful proposed binding contract therefore requires the expected value to carry the original user constraint and native receipt(s), along with the entity/option relation connecting them. An assistant proposal or a quote containing a different value is insufficient by itself. Distinguish a user's explicit revised intent from generic assent to an assistant's misdescription. Code can verify literal typed values, receipt provenance and comparisons; applicability of the user/policy relation remains a separate semantic judgment. When evidence does not uniquely identify an expected value, emit a gap rather than manufacture a replacement ID.

## Source disagreements that limit claims

Several alleged action-mismatch FNs cannot be treated as obvious policy violations merely because the task oracle expected another next action. The inspected original endings include:

- hold_ret_014: the latest user supplies the corrected complete address and says they are good to go with updating it and processing the exchange. Gold nevertheless calls the address update an impermissible action.
- hold_air_057: the latest user explicitly asks to cancel the shown business reservation and refund the original payment method. Gold calls cancellation impermissible. Eligibility still requires the original record, but the immediate user request does not support blanket prohibition.
- hold_ret_018: the latest user explicitly accepts PayPal if Amex is unavailable; current return uses PayPal. Gold calls the action impermissible.
- hold_air_024: the latest user explicitly authorizes the shown flight changes and selected gift card; current call matches those. Gold calls the action impermissible.
- hold_ret_026: the latest user asks for a gift-card refund and confirms it. Gold expects PayPal. The actual `gift_card_0000000` remains ungrounded in observed profile evidence; this supports investigating that ID, not assuming PayPal is uniquely correct despite user intent.

These observations do not constitute complete relabeling. Preserve labels and report both original-score behavior and source-based uncertainty. They do rule out using the task mismatch text alone as the normative proof.

There is also an explicit policy/label consistency trap: valid retail__36 is labelled positive for identical old/new options, while hold_ret_025 is labelled negative despite a same-option exchange. The latter model correctly quotes the policy's different-product-option condition. Adding a universal no-op-exchange detector may increase and decrease agreement with the existing labels. This deserves source-contract adjudication before asserting that either effect represents sound progress.

## Most useful separate mechanism after binding

The source-complete expired-contract case is a concrete opportunity for **resolving an identified evidence gap**, rather than generating expected arguments. Its admitted Qwen review already identifies the exact prohibition and emits UNKNOWN because the contract end date is not established in its packet. Original h10 contains line L1002 and contract_end_date 2025-01-31; explicit policy time is 2025-02-25. The semantic norm was found; relevant native evidence did not reach or survive the review context.

An experiment can take a reviewer's unresolved condition, retrieve original prior native records matching the typed current object identifier, retain complete records and original call/result pairing, then ask the same reviewer to assess the unresolved condition. Code returns observed values and any raw date/equality comparisons without deciding which business norm applies. Avoid tool-name/row-ID branches, assistant-prose fact substitution, silently treating a later bill receipt as a newer line receipt, or inferring absence from truncated history. If later same-entity observations exist, preserve them for freshness analysis. This is a focused source-completion experiment with a direct observed failure trigger.

Other FNs require normative/precondition reasoning rather than different argument values: basic-economy and route modification restrictions (ext_air_018/052), cancellation eligibility alternatives (ext_air_065/067), removal versus replacement (ext_ret_000), direct agent calls to user/discoverable tools (three valid cases), repetition of a failed call (valid retail__48), date-filtered aggregation (valid airline__7), and escalation/available alternatives (three valid cases, with earlier documented gold caveats). An argument-only improvement cannot be advertised as covering these.

## Bounded recommendation

Run the planned response-value-blind binding experiment as a separate frozen intervention, checking original user constraints and native object evidence before normative accusation. Include right-object and user-revised-choice negatives, not only wrong-ID positives; compare complete identical cohorts and retain technical failures separately. Evaluate additions against B2 owners so a correct new candidate is not confused with a change in final decisions.

If binding repeats the saved pre-pass's assistant-summary errors, the next focused experiment should resolve explicit UNKNOWN evidence gaps using complete matching native records. The expired-contract trajectory is a diagnostic example, not a condition to encode in runtime. No new universal mechanism, F1 increase or independent generalization has been established by this offline inventory.
