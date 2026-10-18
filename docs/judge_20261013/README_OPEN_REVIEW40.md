# Open answer audit + available exact MAX, quota .40

Experimental submission, GPU_UNTESTED before the owner's platform execution.
No F1, target-GPU coverage or 1800-second timing is claimed by CPU/CI checks.

One offline vLLM model, pinned Qwen3.6 AWQ. Each chunk: durable overall,
short answer-aware JSON audit, source-reference validation, exact final scoring.
Then proceed to the next chunk. Reserve remaining primary work before review;
deferred chunks may be attempted after primary. All deadlines remain unchanged.

For every row independently, rank by max(available finite exact overall, final).
Neither source replaces a larger value from the other. No global final-completeness
gate. Missing/inexact/failed values are absent, not model NO. A row with neither
score retains the existing explicit mechanical/technical binary fallback.
Apply the existing hard override and positive_rate=.40 rank quota.

The final can reject an audit concern, but MAX cannot decrease an overall score.
Scores from different prompts are not proven calibrated; MAX may amplify a false
alarm. Partial coverage may depend on length/order/deadline. A technical failure
can still leave only overall, now with quota .40. No altered labels or forced
positives are inserted to manufacture a different platform result.

Audit generation: temperature=0, top_p=1, seed=0, max_tokens=384, thinking off,
no YES/NO allowed-token restriction. Scoring: temperature=1, one token, existing
exact YES/NO contract. Incomplete JSON/length termination is not accepted as notes.
The final still scores the source without notes when transport/size validation fails.
Source-reference validity is not semantic correctness. Quotes come from code offsets.

Both audit and final use the saved actual primary context. Reserve 2048 tokens
before primary preparation for audit templates/generation/notes. Sources are never
trimmed again to squeeze notes in; notes are dropped with a reason if necessary.
The reserve can change long-row context versus 6q; this is not a matched ablation.

Entrypoint and I/O remain predict.py, id/prompt/response CSV or Parquet,
complete binary id/label output with literal/duplicate IDs preserved.
stop1380 / kill1530 / watchdog1680 seconds from predict, 1800 seconds externally.
The bundled model and runtime are unchanged; no server, network or new weights.

This candidate changes review, scheduling, partial-score aggregation and quota
together. A leaderboard delta cannot isolate their contributions. Repository
production JUDGE_CONFIG.json remains unchanged. The earlier 6q MAX archive is retained.
