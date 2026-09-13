# Goal v3 isolation v2: frozen-run protocol

Implemented-from-spec Goal-only experiment, separate from immutable historical
Goal/Plan v2 and Goal v3 isolation v1. Complete inference freeze is generated
only from committed source. No external inference is permitted before that.

The offline corpus is development-aware, not a blind holdout: 24 minimal
pairs/48 core cases across F1–F16, then 12 composition/NL stress cases.
Source inputs, authored behavioral gold, inventory/stages, implementation,
prompt/schema, provider configuration, scoring, gates and retry/repair rules
are separately identified by hashes in the complete manifest.

The package initializer imports legacy Detector modules. The isolation path
never executes a Policy parser/evaluator or consumes its verdict/features.
There is no Policy input. Code hashes for passive imported modules are
archived for reproducibility; their presence is not a Policy semantic signal.

## Inference and capture

One case/request, serial concurrency 1, 30 seconds between cases, 180-second
request timeout, temperature 0, Groq `qwen/qwen3.8-27b`, JSON Object Mode,
`max_completion_tokens=2048`. No explicit reasoning parameter (provider default
previously documented as none). Actual model access/usage is not guaranteed;
there is no exploratory ping. Actual requests retain served model and usage.

No semantic retries, samples, judges, challengers or failure-analysis calls.
At most one identical-message/model/config retry on timeout/429/5xx/connection
failure, with a 2-second backoff. Client's internal retries are disabled.
Invalid JSON/schema or semantic disagreement never triggers retry.
Repair accepts only exact JSON or an exact JSON/plain code fence; no fields,
facts, enum values or meanings are inserted or changed.

Request admission is durably recorded before calling transport. Missing
result capture on resume is UNKNOWN_NO_AUTOMATIC_RETRY, not permission to
resend. An exclusive per-stage PID lock protects live requests. A leftover
lock requires explicit verification that the recorded process is terminal
before removal. Never infer termination from file age or observation timeout.

Only schema-valid proposals plus completion hashes are stored, not raw
server errors/credentials. Model output remains a candidate. Multi-world
calculus and independent USER-fragment receipt replay run offline.

## Budget and stage boundaries

After each captured case, account for every physical attempt (including retry).
Missing/unverifiable reported totals stop further cases as an accounting
integrity failure, not proof of semantic rejection. The user explicitly
relaxed external-token economy **before freeze**. `enforce_token_ceilings=false`:
the earlier S1 24,000/S2 72,000/S3 24,000 targets are informational and do
not stop the run. Output allowance is 2,048 tokens so material readings need
not be squeezed into a smaller output. Tokens spent on failed
requests can be unreported. No financial cost is invented.

S1 is 12 frozen cases from distinct pairs. Stop as REJECT_EARLY when schema
usability <10/12, status correctness <6/12, any incorrect definitive proposal,
or optimistic maximum fully correct core pairs is below 22/24. Budget stops
are BUDGET_STOP, distinct from semantic rejection and incomplete experiments.
S2 runs the remaining 36 only after S1 admission; cumulative 48-case core
must pass every numerical gate in the frontend/gates document before S3.
Stress ≥80% is a readiness signal, not retroactive rewriting of core gates.

Seal the exact attempted stage prefix before opening gold, even on budget
stop; missing cases are NOT_RUN, never fabricated UNKNOWN predictions.
Seal/boundary/case/physical captures and prior stage seals are replay-verified
before scoring. Stage admission is recomputed from sealed artifacts before
launching the next stage, not accepted from a mutable unverified flag.

## Commands

Use `PYTHONPATH=src` from the vNext repository. The script supports:

```text
python scripts/evaluate_goal_v3_isolation_v2.py freeze
python scripts/evaluate_goal_v3_isolation_v2.py verify
python scripts/evaluate_goal_v3_isolation_v2.py batch --stage S1 --env-file <explicit env path>
python scripts/evaluate_goal_v3_isolation_v2.py score --stage S1
```

`batch` runs the stage, seals it, then scores once. No per-request agent
polling; terminal batch output is one boundary summary. While it runs, do
offline report/artifact work. Conditional S2/S3 use the same frozen script
and provider; no adaptation after seeing labels or errors.

Final report must distinguish proposals, scoped certificates, source-adapter
assumptions, safety, coverage, families/pairs, cost/unknown usage, Q1–Q8,
and KEEP/REVISE/REJECT/REJECT_EARLY. An incomplete budget/transport run cannot
claim a semantic KEEP/REJECT. General-language or Core readiness is not
proved by the controlled USER fragment; any blocker stays explicit.
