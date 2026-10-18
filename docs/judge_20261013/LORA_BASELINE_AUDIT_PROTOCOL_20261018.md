# Standalone baseline and valid46 audit — 18 October 2026

User requested an independent check of the large gains and valid46 regression.
Preserve original receipts and scores; no training, prompt changes, threshold
selection or adapter changes. The original use of disable_adapter is documented:
https://huggingface.co/docs/peft/main/en/package_reference/peft_model#peft.PeftModel.disable_adapter
Documentation is not a substitute for numerical reproduction.

Select ALL46 valid rows plus16 hash-selected dev and16 hash-selected external
eval rows, without gold. Use saved exact rendered texts and token/source hashes,
not a new prompt renderer. Labels stay local. Run three SEPARATE Python processes:
vanilla AutoModelForCausalLM without any PEFT wrapper, loaded trained PEFT model
with adapter disabled, loaded PEFT model with adapter enabled. No optimization.
BF16/SDPA, same base model/tokenizer and aliases. Verify no lora parameters in the
vanilla model, and all adapter layers disabled/enabled as appropriate in the
other modes. Measure the layer count rather than assuming it. No merge. Hash
unchanged base checkpoint shards.

Independent helper reimplements alias-group score and also computes full-vocab
log_softmax route. Compare numerical scores row-by-row to frozen transfer/pilot
receipts, including all46 valid rows. Report exact equality and maximum difference,
do not silently reinterpret a mismatch as harmless. Recompute valid46 decisions
at fixed quotas .40/.50 with the original structural hard flags and original
input order; separately report score>0 and changed TP/FP. No hidden-test claim.

Separate CPU helper imports no Guardian metrics/decision code. Recompute32 quota
tables and8 ranking pairs with scikit-learn; independently reconstruct2659 raw
Compli natural train/dev/eval rows and labels from pinned upstream JSON, without
executing upstream code; test normalized full prompt/response overlap. Check
valid46 input identity against original Git CSV AND original dedicated valid run.
This audits extraction/implementation, not the semantic correctness of upstream gold
or statistical independence of shared benchmark templates. Bounds900s for3 GPU
processes; preserve partial receipts if a technical failure prevents completion.
