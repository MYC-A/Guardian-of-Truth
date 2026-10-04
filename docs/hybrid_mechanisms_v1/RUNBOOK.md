# Reproduction

Set `PYTHONPATH` to repository root and `src`. Python 3.13, Pydantic 2.13.5.
Prepare: `python -m experiments.hybrid_mechanisms.runner prepare`.
Freeze protocol/source hashes, commit and push before inference.
Run each phase using `python -m experiments.hybrid_mechanisms.runner run --phase PHASE --live`.
Order: factorial, augment, split, retrieval, extras, gate. Offline replay:
`python -m experiments.hybrid_mechanisms.runner replay`.
Scoring is separate: `python -m experiments.hybrid_mechanisms.score`.

Credentials remain in existing server environment/secret files. No key is logged
or committed. GET model metadata is preflight, not an inference attempt.
Finite server jobs use supervisor with autostart/autorestart disabled, dedicated
worktree/results/logs, and no examination-environment tool execution.

Save original request bytes/hash, raw completion, usage and ledger before deriving
predictions. Reconstruct all adaptive source traces from retained raw plans.
After each phase: offline replay, inspect failures and causes, commit and push.
Changing frozen code or prompt needs a separate protocol/phase; do not edit a
previous experimental result to accommodate new hypotheses.
