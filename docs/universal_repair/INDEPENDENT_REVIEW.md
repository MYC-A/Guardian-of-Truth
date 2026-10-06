# INDEPENDENT_REVIEW — status: NOT independent (self-review)

The protocol asks for a separate code reviewer and logic reviewer. **This platform exposes no sub-agent / second-reviewer tool**,
so no independent review was performed. What follows is a structured self-review by the same agent that wrote the code; it must
not be counted as independent validation. An external reviewer should repeat it from the raw receipts (RUNBOOK.md).

## Code review (implementation, boundaries, cache/retry, aggregation)
| # | finding | severity | status |
|---|---|---|---|
| C1 | `df_copy` scoped copy missed values copied from the result of the cited tool call (new FP lb3L_012) | high | fixed A1 + test |
| C2 | strict evidence rejected the exact SUM of an addressed empty array (lost BK3e Ems aggregation) | high | fixed A2 + test |
| C3 | pool raises the number of verifier calls per row → one extra wrong SUPPORTED (lb3L_034, user had confirmed both enumerated bookings) | medium | open, measured; no post-hoc veto added |
| C4 | budget cap: `Transport` counts SENT from the durable ledger across processes, but processes were run sequentially by design; concurrent processes would share pacing incorrectly (per-process MIN_INTERVAL) | low | documented in RUNBOOK |
| C5 | ReadThrough serves exact keys only; changed requests in offline mode are NOT_EXECUTED (never a verdict) — verified by the offline report (R_wit/R_comb offline lose TPs only through NOT_EXECUTED) | — | ok |
| C6 | records loader rejects silent last-wins; retry chains validated (ext rep3: 22 chains) | — | ok |
| C7 | `*_mech` aggregation never changed a live decision → mechanical bypass is not exercised by these sets; its safety is only unit-tested | low | open |
| C8 | regex-based assertion scope / confirmation state are heuristics over NL; the tests cover EN/RU patterns only | medium | limitation |

## Logic review (sources, applicability, gold, causality, freeze)
| # | finding | status |
|---|---|---|
| L1 | A1 and A2 were found on LB3 (development); LB3 is not clean for R_fix/R_comb. Only the holdout is clean, and the A1 holdout result of R_fix/R_comb was observed before A2 (identical to V4r; A2 changed nothing there) | disclosed in PROTOCOL |
| L2 | Holdout gold: oracle labels + one annotator (this agent) dropped 15 rows (13 errors excluded) before any run, reasons in MANIFEST; no second annotator → not independently adjudicated | limitation |
| L3 | Cause judge is the same model family (ministral-14b) as the detector → not an independent judge; Gemma/Ollama BLOCKED (429 monthly limit) | limitation |
| L4 | 16 of 41 holdout positives are format-only causes (multi-call / text+call); the detector's measured recall on them is low (P3) | reported |
| L5 | R_wit removes label-TPs whose accusation the sources contradict (ext_ret_019, confirmation was given in h30/h31): label metric goes down while cause correctness goes up — measured by the cause judge, not assumed | see CAUSE_AND_GOLD_AUDIT |
| L6 | No victory claimed from a single oracle case: G3e is one row; holdout shows no change | FINAL_DECISION |
