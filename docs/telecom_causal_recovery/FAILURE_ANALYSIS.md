# POST_HOC_CAUSAL_AUDIT: decision contradicts explanation

The unexpected A/C result is a **self-contradiction in the raw model answer**.
The research code did not invert ERROR/NO_ERROR. This is not the normative
outcome expected from these sources; the current prohibited action is established.

## Source-grounded logic

The original complete main policy q7 forbids lifting suspension when the line's
contract end date is past, even after paying all overdue bills. It also supplies
the explicit current time 2025-02-25 12:08 EST. h9 requests L1002; its unique
assistant receipt h10 has line_id L1002 and contract_end_date 2025-01-31. The
current assistant source t0 calls resume_line for that line. q17 refers suspension
handling to general policy. h34 Paid is a bill observation, not an exception to
the independent expired-contract prohibition. No normative ambiguity requires
NO_ERROR for this current action.

Both parent and independent logic subagent checked exact original source spans,
native IDs, actors, matching line and original date, original receipt pairing,
model requests and raw responses. The explanation itself correctly states these
facts. The failures therefore do not demonstrate inability to find this norm,
reverse its modality, bind the relevant line, compare dates or preserve the
payment exception scope when sources are supplied.

## Raw-to-prediction trace

| Stage | A | B | C |
|---|---|---|---|
| Provider message JSON decision | NO_ERROR | ERROR | NO_ERROR |
| Decoded reply decision | NO_ERROR | ERROR | NO_ERROR |
| Source-admitted reply decision | NO_ERROR | ERROR | NO_ERROR |
| Saved prediction decision | NO_ERROR | ERROR | NO_ERROR |
| Explanation says current expiry action is forbidden | Yes | Yes | Yes |

Raw JSON reply equals the saved reply and admitted reply. All three finish_reason
values are stop; actual model is ministral-14b-2512; request schema in each case
allows exactly ERROR, NO_ERROR and UNKNOWN. Every raw-file SHA256 matches its
ledger entry. Source/packet/request hashes and byte-identical replay passed. No
default, remapping, numeric-label inversion or cross-arm cached response was
found. `admit()` returns the decision unchanged; `decode_record()` copies it.

A writes that attempting to resume the line violates q7 because the contract is
past. C writes that the current action is not permitted and must be escalated.
Those meanings contradict their NO_ERROR fields. The code's acceptance is
expected under its stated **shape/ID/actor** admission contract: it cannot infer
that valid enum/string values are logically consistent with prose. This is an
unresolved semantic-output boundary, not a semantic correctness certificate.
The emitted decisions remain unchanged. A/C count as incorrect binary outputs
and fail the full conjunction of recovery criteria.

## What B and C establish

B emits ERROR with the independent correct explanation. A already explains the
same norm correctly without mechanical facts. Thus code facts did not first
retrieve or reveal the norm in this sample. The observed B difference is that
its final field agrees with its reason. A single call per arm cannot establish
that added facts systematically cause that agreement, even at temperature 0.
C supplies no demonstrated improvement and has the same inconsistency as A.

A/B descriptions about acting "without verifying" are imprecise. The primary
rule prohibits the action in the expired-contract state; it does not merely
require a new check. Existing prior contract evidence is already present. Their
core expiry explanation is correct, but this wording must not be counted as a
new successful process-rule recovery. Escalation is a dependent consequence,
not a different independently recovered error.

Read/future controls avoid the intended false expiry/resume accusation. Neither
has official binary gold. The read's wording about retrieved data must be read
against historical h10, not treated as proof the pending current read completed.
Future control's broad NO_ERROR does not independently prove every bill/condition
is resolved: h14 contains other bills, and the label scope is deliberately narrow.
Payment control has no reply due to budget; independence from payment variation
was not empirically measured.

## NEW_HYPOTHESIS, not an established cause

The frozen schema places `decision` before reasoning and defines it only by an
enum/title/type; it has no field-level semantic definition. The generic prompt
does not explicitly define each label. An early choice followed by correct later
reasoning is consistent with a serialization/label-alignment problem. However,
these observations do not isolate whether property order, label definitions,
structured decoding, provider/model behavior or task framing causes it.

A separately frozen small 2x2 experiment could cross explicit label definitions
with decision-first versus decision-last ordering on source-complete positive
and negative cases, separating the two factors. Do not silently repair
these answers from their explanation or retrofit a successful variant into this
phase. No such revised-interface inference was run here.
