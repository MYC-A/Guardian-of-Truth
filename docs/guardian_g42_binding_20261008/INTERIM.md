# Interim (stopped early on user request, 2026-10-08 ~02:30 UTC)

Granite 4.2-30B Q4_K_M (B2, same prompt) vs Qwen3.8-27B B2 on the same 15 completed rows (lb2_long 7, valid46 8):
Qwen 5 TP / 0 FP / 0 FN; Granite 3 TP / 0 FP / 2 FN (misses lb2L_004, airline__21::t7), 0 rows where Granite is better.
Granite: 4/8 valid46 rows went to fallback (own verdict unusable); throughput ~13 tok/s/slot x8 on A100 (llama.cpp).
Decision: Qwen stays the base model. Sample is small (15 rows) -> indicative, not a significance test.

H3 binding audit (Qwen, code-verified mismatch): 0 VERIFIED_MISMATCH on 59 dev rows (valid46 + ext_tau2 partial) -> no change.
Root cause: Qwen itself maps the entity wrongly (ext_tel_008: user phone ...2002, call used L1001, audit says MATCH).
The model-side audit inherits the reviewer's blind spot; needs a deterministic entity-attribute check instead.
