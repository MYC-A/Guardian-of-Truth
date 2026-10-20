# V13: native TRAIN-only hard-case inventory

Freeze before mining. Purpose: determine whether the current adapter still
accuses source-checked correct native examples, before spending on more training.
No training is started merely because GPU is available.

Use only tau2 rows from the pinned V4 frozen-v2 TRAIN (same 1458-row source
underlying V5). Recheck constructor predicates, schema, current-turn parsing,
complete contrast pairs and TRAIN/DEV/HOLDOUT component separation. Legacy
mechanical rows are excluded from this pass: require native execution receipts.
Do not invent explanations from future native results or from mutation metadata.
No evaluation text, label, model error or source component can become a seed.

Encode the unchanged production input, then the established V6 direct binary
verifier question (verifier_text), which explicitly requests a YES/NO answer.
Do not constrain YES/NO at a position requesting the start of a Rule/Evidence
rationale. The direct binary score is a TRAIN mining proxy, NOT the deployed
post-review verifier score or an evaluation metric. Current frozen V7 adapter;
prove all 100 modules bound on GPU. One pass,
chunk 64, temperature 1 constrained to YES/NO, seed 0. No result cache or retries.
Sort pairs by a correct twin's positive score, then positive-twin missed score,
then stable hash. Preserve both twins. Limit eight pairs per domain/family and
four per domain/family/template, round robin by bucket; at most 96 pairs.
If there are insufficient eligible pairs, report the actual count and stop;
do not fill with evaluation data, duplicate templates or rejected source rows.

Freeze scores before joining TRAIN labels for selection. Publish FP/FN counts,
families, token lengths and source-audit failures. Keep all outputs and hashes.
Mining repeats do not create new data. This stage does not train, select an
evaluation threshold, promote production or assemble a ZIP. Training needs a
separate frozen objective and an audited rationale corpus; metadata-only
predicate dictionaries are not valid explanations of the visible current turn.

Pre-inference technical revision: prepared-v1 accidentally requested a rationale
before the constrained binary token. No mining GPU call or quality metric was
produced from that version. Archive it as superseded; prepared-v2 uses the proper
binary question. The first queue is superseded while waiting for V12, before any
mining. Both versions use the same protected source and audited native pairs.
