# PolicyGuard probe — frozen before inference, 18 October 2026

Question: does the published specialized checkpoint provide a useful independent
signal for Guardian current-turn contextual hallucinations? No expected score is
assumed. This experiment does not train a model or modify the submission.

Model: `Rakancorle1/PolicyGuard-4B`, revision
`f9060bd92c6f7d70170e1c5239131b10027cf375`. All 13 inference files are size/hash
verified against `POLICYGUARD_PINNED_MODEL_20261018.json` before model loading.
Safetensors only; no remote code or pickle/training artifacts. Published card:
https://huggingface.co/Rakancorle1/PolicyGuard-4B .

1. Native capability check: all 300 previously frozen PolicyGuardBench auxiliary
   test rows, using their original `input` plus the model card's final instruction
   `Output violation or no_violation.` Raw prompt, no chat template. These labels
   describe entire trajectories and never become Guardian turn labels. Some
   upstream descriptions literally contain `... and N more actions`; preserve
   them and report this limitation rather than reconstruct hidden actions.
2. Transfer: frozen Compli dev520 and Guardian seen397 (valid46 overlaps seen397).
   Use the complete initial parsed system block as policy, exact history as
   context, exact response as the explicitly marked current turn. Include the
   existing Guardian JUDGE_SYSTEM definition verbatim, mapping YES/NO to the
   published labels. This is a task adaptation, not a reproduction of the paper.
   No source truncation; overflow fails explicitly. No automatic quote veto.
3. Only if native capability and transfer give credible signal, evaluate a fixed
   candidate on the untouched external family-separated eval1893. Do not select
   prompts, weights or thresholds on eval1893. Report insurance separately.

Inference: existing A6000/vLLM 0.19.1, BF16, eager, APC, seed 20261018, batches16,
max_num_batched_tokens4096, GPU utilization cap .8. Native max context8192;
transfer49152. Generation follows the card's max_new_tokens4 at temperature0.
Save exact generated text/token IDs, finish reason, input/source hashes and time.
Anything other than a complete advertised label is UNKNOWN; report coverage and
the card's separate permissive substring parser result. Do not call UNKNOWN NO.

For transfer, optionally collect exact teacher-forced log probabilities of every
token in each label after a shared newline-terminated prefix. Verify tokenization
prefix identity. Score is unnormalized logP(violation)-logP(no_violation), without
length normalization or fitted calibration. This is a full multi-token likelihood
ratio, not the production exact YES/NO one-token score. Report this difference.
One shared prefix and suffix token receipts make the calculation reviewable.

Separate analysis process reads gold only after inference and validates source
identity. Report strict label confusion/coverage; sequence-score AUROC/AP and
fixed .30/.40 quota results; existing hard overrides and pure model results are
separate. No fitted ensemble. Compare paired errors and family/trajectory groups,
not aggregate F1 alone. Native results are not estimates of competition quality.

Stopping: abort broken model/input/output contracts before interpreting quality.
If native performance is uninformative, investigate published format/checkpoint
once with primary sources; do not burn repeated GPU runs choosing by labels.
If transfer is clearly weaker and offers no complementary errors, do not repeat
or run eval1893. A useful candidate needs reproducible paired improvement and
time measurement before any competition attempt. Download and inference jobs
are supervised, finite and run sequentially with the existing Qwen jobs idle.

Secondary CPU diagnostic frozen before inspecting any transfer predictions or
quality results: equal-weight mean of the two
within-dataset score ranks (Qwen saved final and PolicyGuard full-label likelihood
ratio). Average ranks for ties, then the same .30/.40 quota and hard overrides.
No coefficient, offset, rank function or quota selected by quality. This tests
complementarity without pretending the two score scales are calibrated. It is
an additional exploratory comparison, not independent evidence or a fitted
production ensemble. Report corrections and regressions as well as F1.

Native greedy validation differs from the repository generation_config.json
default sampling (temperature.7/top_p.8/top_k20). Temperature0 was explicitly
frozen for determinism. Thus neither this probe nor its300-row subset is an exact
reproduction of the paper's12000-row evaluation. Cross-engine validation uses
the same fixed first8 native rows and greedy settings, without selecting cases
by correctness. If malformed raw outputs reproduce in Transformers, retain them
and use the already declared full-label likelihood diagnostic for transfer;
do not silently loosen the primary strict parser.

Technical preflight amendment (before any Guardian397 model inference): the
full-source adapter has maximum75678 tokens; two valid46 rows require75678 and
71296, exceeding49152. The first job correctly failed without a model call.
Guardian397 uses max_model_len81920 in a fresh output directory; all content,
instructions, labels, score and decision rules stay frozen. The existing Qwen
comparison had context trimming for these2 rows, so this is a package comparison,
not an isolated same-context model ablation. The checkpoint natively advertises
262144 tokens; this probe does not require extrapolating its position limit.

User-directed contract audit supersedes the raw-format transfer conclusion:
stop the long397 inference, audit within30minutes. Transformers on the frozen
native300 yields raw greedy F1.646154, raw repository-default sampling.628866,
raw greedy16.646154, but chat greedy16.919540 with300of300 strict labels. Thus the
raw model-card recipe was not an adequate format for this checkpoint. This is
not a full12000 reproduction. Archive the old script/raw receipts; never present
raw dev F1.192635 as a confirmed failure of correctly formatted model transfer.

Next fixed run: same dev520 source adapter, native chat_template with generation
prefix, greedy max_tokens16. Exact multi-token scoring appends each complete
label to that SAME assistant prefix (without an extra newline). Classes are
`violation`→[9971,34962] and `no_violation`→[2152,2273,24903,367] under the checked
tokenizer/prefix: no common first token. Independent Transformers first4 dev
teacher forcing confirms the old full-label sign and token selection, with
max absolute summed-logprob difference.11235 BF16 across the two engines; there
was no first-token-only scoring or reversed-label bug. No threshold/weight search.
