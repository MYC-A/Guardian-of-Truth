# Interim (stopped early on user request, 2026-10-08 ~02:30 UTC)

Granite 4.2-30B Q4_K_M (B2, same prompt) vs Qwen3.8-27B B2 on the same 15 completed rows (lb2_long 7, valid46 8):
Qwen 5 TP / 0 FP / 0 FN; Granite 3 TP / 0 FP / 2 FN (misses lb2L_004, airline__21::t7), 0 rows where Granite is better.
Granite: 4/8 valid46 rows went to fallback (own verdict unusable); throughput ~13 tok/s/slot x8 on A100 (llama.cpp).
Decision: Qwen stays the base model. Sample is small (15 rows) -> indicative, not a significance test.

H3 binding audit (Qwen, code-verified mismatch): 0 VERIFIED_MISMATCH on 59 dev rows (valid46 + ext_tau2 partial) -> no change.
Root cause: Qwen itself maps the entity wrongly (ext_tel_008: user phone ...2002, call used L1001, audit says MATCH).
The model-side audit inherits the reviewer's blind spot; needs a deterministic entity-attribute check instead.

## Deterministic checks (no LLM), experiments/guardian_binding/idcheck.py — designed AFTER inspecting dev errors
- A UNGROUNDED_ID (id-like arg of a non-read, non-create call never seen in user/tool/system text): 0 changes on dev and test.
  Before the create-verb exclusion it fired on 3 frozen120 "new id allowed" traps (FP) -> exclusion added.
- B ATTRIBUTE_CONFLICT (call id selects an object whose attribute, e.g. phone number, differs from the user-stated value
  of the same attribute): dev +5 TP / 0 FP. First version gave test +1 TP / +8 FP (foreign-key matches); fixed to
  "own (first) identifier + non-id attribute" AFTER seeing those test FPs -> test is no longer fully clean for B.
  0 fires on 314 other unlabelled/synthetic rows. All 5 gains are one scenario family (telecom line binding).
- C TURN_FORMAT (call + user message in one turn, only if policy text forbids doing both): 35/35 such rows are gold
  errors; QB2 already catches 34 -> +1 TP.
- QB2 | A | B | C: dev 130/8/34 F1 .861 -> 136/8/28 .883; test (lb2+lb3+lb_long, 148 rows) 71/2/2 .973 -> unchanged.
- LLM binding audit (H3): stopped; 0 verified mismatches on 77 call rows (same blind spot as the reviewer).
